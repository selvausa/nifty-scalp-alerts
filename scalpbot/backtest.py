"""Backtest: run the setups over past sessions and simulate each trade with the
cheat sheet's exit rules on historical option prices.

Known limits (also printed with every report):
  * 5-minute candles: when a stop and a target fall in one candle, the stop is assumed first.
  * No historical bid/ask: the spread rules are not tested; a fixed slippage per fill is used.
  * Delta is worked out from option prices (Black-Scholes), not taken from a live chain.
  * Every alert is assumed taken, one lot, one position at a time.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional, Protocol

import numpy as np
import pandas as pd

from .config import Event, Rules
from .indicators import add_indicators
from .market import Ctx, build_context, session_only
from .options import Chain, Leg
from .setups import Engine, Signal, Sizing
from .state import DayState

log = logging.getLogger("scalpbot.backtest")
RISK_FREE = 0.065
FIVE = pd.Timedelta(minutes=5)


# ------------------------------------------------------------------ option maths
def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot: float, strike: float, t: float, vol: float, kind: str, r: float = RISK_FREE) -> float:
    if t <= 0 or vol <= 0:
        return max(spot - strike, 0.0) if kind == "CE" else max(strike - spot, 0.0)
    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / sq
    d2 = d1 - sq
    if kind == "CE":
        return spot * _cdf(d1) - strike * math.exp(-r * t) * _cdf(d2)
    return strike * math.exp(-r * t) * _cdf(-d2) - spot * _cdf(-d1)


def bs_delta(spot: float, strike: float, t: float, vol: float, kind: str, r: float = RISK_FREE) -> float:
    if t <= 0 or vol <= 0:
        itm = spot > strike if kind == "CE" else spot < strike
        return (1.0 if kind == "CE" else -1.0) if itm else 0.0
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    return _cdf(d1) if kind == "CE" else _cdf(d1) - 1


def implied_vol(price: float, spot: float, strike: float, t: float, kind: str) -> float:
    """Bisection; clamps to the bounds when the price is outside what any volatility gives."""
    lo, hi = 0.01, 5.0
    if price <= bs_price(spot, strike, t, lo, kind):
        return lo
    if price >= bs_price(spot, strike, t, hi, kind):
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        if bs_price(spot, strike, t, mid, kind) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def delta_from_price(price: float, spot: float, strike: float, expiry: date, now: datetime, kind: str) -> float:
    t = max((datetime.combine(expiry, time(15, 30)) - now).total_seconds(), 60.0) / (365 * 86400)
    return bs_delta(spot, strike, t, implied_vol(price, spot, strike, t, kind), kind)


# ------------------------------------------------------------------------ costs
def round_trip_cost(buys: list[float], sells: list[float], lot: int, brokerage: float = 20.0) -> float:
    """Charges for a set of fills at the cheat sheet's rates (section 7).
    `buys` and `sells` are premium prices, one entry per order."""
    bt, st = sum(buys) * lot, sum(sells) * lot
    brok = brokerage * (len(buys) + len(sells))
    exch = 0.0003553 * (bt + st)
    sebi = 10 / 1e7 * (bt + st)
    return brok + 0.0015 * st + exch + sebi + 0.00003 * bt + 0.18 * (brok + exch + sebi)


# ----------------------------------------------------------------- history source
class History(Protocol):
    fut: pd.DataFrame          # stitched near-month futures, 5-minute
    spot: pd.DataFrame         # NIFTY index, 5-minute
    vix: Optional[pd.DataFrame]
    expiries: list[date]       # all option expiries covering the range, sorted

    def option_day(self, expiry: date, strike: int, kind: str, day: date) -> Optional[pd.DataFrame]: ...


def groww_symbol(expiry: date, strike: Optional[int] = None, kind: str = "FUT") -> str:
    base = f"NSE-NIFTY-{expiry.day:02d}{expiry:%b}{expiry:%y}"
    return f"{base}-FUT" if strike is None else f"{base}-{strike}-{kind}"


def monthly_expiries(expiries: list[date]) -> list[date]:
    last: dict[tuple[int, int], date] = {}
    for e in expiries:
        last[(e.year, e.month)] = max(e, last.get((e.year, e.month), e))
    return sorted(last.values())


class RateLimited(RuntimeError):
    pass


def is_rate_limit(e: Exception) -> bool:
    text = f"{type(e).__name__} {getattr(e, 'msg', '')} {e}".lower()
    return "ratelimit" in text or "rate limit" in text or "429" in str(getattr(e, "code", ""))


class GrowwHistory:
    """Historical candles from Groww, cached on disk so a rerun costs no API calls."""

    BACKOFF = (5, 15, 30, 60, 60, 60)      # seconds to wait after each rate-limit refusal

    def __init__(self, groww, start: date, end: date, cache: Path, chunk_days: int = 7, pause: float = 0.4,
                 vix_symbol: str = ""):
        self.g, self.cache, self.chunk, self.pause = groww, cache, chunk_days, pause
        self.calls = self.failed = self.waits = 0
        self._last = 0.0
        cache.mkdir(parents=True, exist_ok=True)
        warm = start - timedelta(days=10)                  # indicator warm-up and the prior session
        self.expiries = self._expiries(warm, end + timedelta(days=40))
        if not self.expiries:
            raise RuntimeError("Groww returned no NIFTY expiries for the period")
        self._contracts: dict[date, list[str]] = {}
        self.spot = self._range("NSE-NIFTY", "CASH", warm, end)
        vs = vix_symbol or (groww.vix.groww_symbol if groww.vix else "")
        self.vix = self._range(vs, "CASH", warm, end) if vs else None
        parts, prev = [], warm - timedelta(days=1)
        for m in monthly_expiries(self.expiries):
            a, b = max(prev + timedelta(days=1), warm), min(m, end)
            if a <= b:
                parts.append(self._range(groww_symbol(m), "FNO", a, b))
            prev = m
            if m >= end:
                break
        self.fut = pd.concat([p for p in parts if not p.empty]).sort_index() if any(not p.empty for p in parts) else pd.DataFrame()
        if self.fut.empty:
            raise RuntimeError("No futures candles returned; check that expired contracts are available on your plan")

    # -- low level
    def _call(self, fn, *a, **k):
        """Every Groww request goes through here: spaced out, and retried with growing
        waits when Groww says the rate limit was hit. Other errors are raised at once."""
        for wait in (*self.BACKOFF, None):
            gap = self.pause - (_time.monotonic() - self._last)
            if gap > 0:
                _time.sleep(gap)
            self._last = _time.monotonic()
            self.calls += 1
            if self.calls % 100 == 0:
                log.info("backtest data: %d Groww requests so far", self.calls)
            try:
                return fn(*a, **k)
            except Exception as e:
                if not is_rate_limit(e):
                    raise
                if wait is None:
                    raise RateLimited(
                        "Groww kept refusing requests for its rate limit. Wait a few minutes and run the same "
                        "command again: everything downloaded so far is cached, so it resumes where it stopped. "
                        "A higher --pause (for example 1.0) spaces requests out more.") from e
                self.waits += 1
                log.info("Groww rate limit hit; waiting %ds before retrying", wait)
                _time.sleep(wait)

    def _expiries(self, a: date, b: date) -> list[date]:
        out, y, m = set(), a.year, a.month
        while (y, m) <= (b.year, b.month):
            f = self.cache / f"expiries_{y}_{m:02d}.json"
            if f.exists():
                vals = json.loads(f.read_text())
            else:
                p = self._call(self.g.api.get_expiries, "NSE", "NIFTY", y, m, timeout=15)
                vals = [str(x)[:10] for x in (p.get("expiries") or [])]
                if vals and date(y, m, 28) < date.today():
                    f.write_text(json.dumps(vals))
            out.update(date.fromisoformat(v) for v in vals)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return sorted(out)

    def _fetch(self, symbol: str, segment: str, a: date, b: date) -> pd.DataFrame:
        f = self.cache / f"{symbol.replace(' ', '_')}_{a}_{b}.csv"
        if f.exists():
            return pd.read_csv(f, index_col=0, parse_dates=True)
        from .groww import parse_candles

        err: Optional[Exception] = None
        for attempt in range(2):
            try:
                p = self._call(self.g.api.get_historical_candles,
                               "NSE", segment, symbol, f"{a} 09:00:00", f"{b} 15:45:00", "5minute", timeout=20)
                df = parse_candles(p)
                # Groww's history can run days behind: cache only chunks old enough to be complete
                # (an empty answer is cached too, so a contract with no trades is not asked for again)
                if b < date.today() - timedelta(days=7):
                    df.to_csv(f)
                return df
            except RateLimited:
                raise                                      # stop the run; never treat this as "no data"
            except Exception as e:
                err = e
                _time.sleep(1.0)
        self.failed += 1
        log.warning("No candles for %s %s..%s: %s", symbol, a, b, err)
        return pd.DataFrame(columns=["o", "h", "l", "c", "v"])

    def _range(self, symbol: str, segment: str, a: date, b: date) -> pd.DataFrame:
        parts, cur = [], a
        while cur <= b:
            nxt = min(cur + timedelta(days=self.chunk - 1), b)
            parts.append(self._fetch(symbol, segment, cur, nxt))
            cur = nxt + timedelta(days=1)
        parts = [p for p in parts if not p.empty]
        if not parts:
            return pd.DataFrame(columns=["o", "h", "l", "c", "v"])
        df = pd.concat(parts)
        return df[~df.index.duplicated(keep="last")].sort_index()

    def _symbol(self, expiry: date, strike: int, kind: str) -> str:
        """The contract's Groww symbol: built from the usual pattern, checked against
        Groww's own contract list for that expiry when it is available."""
        want = groww_symbol(expiry, strike, kind)
        if expiry not in self._contracts:
            try:
                p = self._call(self.g.api.get_contracts, "NSE", "NIFTY", expiry.isoformat(), timeout=20)
                self._contracts[expiry] = [str(c) for c in (p.get("contracts") or [])]
            except RateLimited:
                raise
            except Exception as e:
                log.warning("Contract list for %s unavailable: %s", expiry, e)
                self._contracts[expiry] = []
        lst = self._contracts[expiry]
        if not lst or want in lst:
            return want
        tail = f"-{strike}-{kind}"
        return next((c for c in lst if c.endswith(tail)), want)

    def option_day(self, expiry: date, strike: int, kind: str, day: date) -> Optional[pd.DataFrame]:
        df = self._fetch(self._symbol(expiry, strike, kind), "FNO", day, day)
        return None if df.empty else df


class HistOptions:
    """Rebuilds the option chain as it stood at one candle, from historical option candles."""

    def __init__(self, hist: History, ts: pd.Timestamp, spot: float, expiry: date, reach: int = 700):
        self.h, self.ts, self.spot, self.expiry, self.reach = hist, ts, spot, expiry, reach
        self._day: dict[tuple[int, str], Optional[pd.DataFrame]] = {}

    def day(self, strike: int, kind: str) -> Optional[pd.DataFrame]:
        k = (strike, kind)
        if k not in self._day:
            self._day[k] = self.h.option_day(self.expiry, strike, kind, self.ts.date())
        return self._day[k]

    def chain(self) -> Chain:
        atm = int(round(self.spot / 50) * 50)
        now = (self.ts + FIVE).to_pydatetime()
        legs: dict[tuple[int, str], Leg] = {}
        for kind, lo, hi in (("CE", atm - 150, atm + self.reach), ("PE", atm - self.reach, atm + 150)):
            for strike in range(lo, hi + 1, 50):
                df = self.day(strike, kind)
                if df is None:
                    continue
                upto = df[df.index <= self.ts]
                if upto.empty:
                    continue
                px = float(upto["c"].iloc[-1])
                if px <= 0:
                    continue
                legs[(strike, kind)] = Leg(strike, kind, groww_symbol(self.expiry, strike, kind), px,
                                           delta_from_price(px, self.spot, strike, self.expiry, now, kind))
        return Chain(self.spot, self.expiry.isoformat(), legs)

    def fill_quote(self, leg: Leg) -> Leg:
        return leg                                   # no historical bid/ask: the spread check stays unchecked

    def candles(self, leg: Leg) -> pd.DataFrame:
        df = self.day(leg.strike, leg.kind)
        if df is None:
            raise RuntimeError("no option candles")
        return df


# -------------------------------------------------------------------- simulation
@dataclass
class Trade:
    day: date
    setup: str
    side: str
    signal_time: datetime
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry: float = 0.0            # premium paid (buys) or net credit received (spreads)
    exit: float = 0.0             # premium received (buys) or cost to close (spreads)
    points: float = 0.0           # premium points after slippage, before charges
    rupees: float = 0.0           # one lot, after charges
    reason: str = ""
    detail: str = ""


@dataclass
class Position:
    sig: Signal
    trade: Trade
    frames: list[pd.DataFrame]            # one option-candle frame per leg
    signs: list[int]                      # +1 long leg, -1 short leg
    open: bool = False
    bars: int = 0
    stop_px: float = 0.0
    entry_fut: float = 0.0
    t1_done: bool = False
    fills_buy: list[float] = field(default_factory=list)
    fills_sell: list[float] = field(default_factory=list)


@dataclass
class Options:
    slippage: float = 0.5
    lot: int = 65
    exit_at_t1: bool = False
    use_options: bool = True
    capital: float = 0.0
    risk_pct: float = 0.5


class Backtest:
    def __init__(self, hist: History, rules: Rules, opts: Options, events: Optional[list[Event]] = None):
        self.h, self.r, self.o, self.events = hist, rules, opts, events or []
        self.trades: list[Trade] = []
        self.skipped: dict[str, int] = {}
        self.signals = 0

    def _skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    # -- helpers
    def _expiry(self, day: date) -> Optional[date]:
        return next((e for e in self.h.expiries if e >= day), None)

    @staticmethod
    def _bar(df: pd.DataFrame, ts: pd.Timestamp) -> Optional[pd.Series]:
        return df.loc[ts] if ts in df.index else None

    def _synthetic(self, fut_day: pd.DataFrame, entry_fut: float, d: int, delta: float) -> pd.DataFrame:
        """Chart-only mode: premium moves delta x index, from a nominal 100. No time decay."""
        mv = lambda col: 100 + d * delta * (fut_day[col] - entry_fut)
        o, c, a, b = mv("o"), mv("c"), mv("h"), mv("l")
        return pd.DataFrame({"o": o, "h": np.maximum(a, b), "l": np.minimum(a, b), "c": c}, index=fut_day.index)

    # -- run
    def run(self, start: date, end: date) -> list[Trade]:
        df = add_indicators(session_only(self.h.fut))
        spot = self.h.spot["c"] if self.h.spot is not None and not self.h.spot.empty else None
        eng = Engine(self.r, Sizing(self.o.capital, self.o.risk_pct, self.o.lot))
        days = sorted({d for d in df.index.date if start <= d <= end})
        for n, day in enumerate(days, 1):
            expiry = self._expiry(day)
            if expiry is None:
                self._skip("day without a known expiry")
                continue
            dte = int(np.busday_count(day, expiry))
            st = DayState(day=day.isoformat())
            pos: Optional[Position] = None
            fut_day = df[df.index.normalize() == pd.Timestamp(day)]
            for ts in fut_day.index:
                basis = 0.0
                if spot is not None and ts in spot.index:
                    basis = float(fut_day.at[ts, "c"]) - float(spot.at[ts])
                ctx = build_context(df, ts, self.h.vix, dte, self.events, basis, None, self.r.vix_fall_sharp_pct)
                if ctx is None:
                    continue
                if pos is not None:
                    if self._manage(pos, ctx, fut_day):
                        self._close_day_state(st, pos.trade)
                        pos = None
                    continue
                if st.blocked(self.r, self.o.capital):
                    continue
                opt = HistOptions(self.h, ts, ctx.spot(float(ctx.row["c"])), expiry) if self.o.use_options else None
                for sig in eng.evaluate(ctx, opt):
                    if not st.can_send(sig.key, ctx.now, self.r.cooldown_min):
                        continue
                    self.signals += 1
                    st.mark_sent(sig.key, ctx.now)
                    pos = self._prepare(sig, ctx, opt, fut_day)
                    if pos is not None:
                        st.trades += 1
                        break
            if pos is not None and pos.open:               # data ran out before the flat-by time
                self._exit(pos, pos.trade.entry_time or pos.trade.signal_time, None, "end of data")
                self._close_day_state(st, pos.trade)
            if n % 20 == 0:
                log.info("backtest: %d/%d days, %d trades", n, len(days), len(self.trades))
        return self.trades

    def _close_day_state(self, st: DayState, t: Trade) -> None:
        if t.exit_time is None:          # never filled
            st.trades -= 1
            return
        st.pnl += t.rupees
        st.consec_losses = st.consec_losses + 1 if t.rupees < 0 else 0

    # -- entry
    def _prepare(self, sig: Signal, ctx: Ctx, opt: Optional[HistOptions], fut_day: pd.DataFrame) -> Optional[Position]:
        sm = sig.sim
        tr = Trade(ctx.now.date(), sig.setup, sig.side, ctx.now)
        if sm["kind"] == "buy":
            leg = sm["leg"]
            if opt is not None and leg is not None:
                frame = opt.day(leg.strike, leg.kind)
                tr.detail = f"{leg.label} delta {abs(leg.delta):.2f}"
                delta = abs(leg.delta)
            elif opt is None:
                lo, hi = (0.60, 0.80) if ctx.dte <= 0 else (0.50, 0.65) if ctx.dte == 1 else (0.45, 0.55)
                delta = (lo + hi) / 2
                frame = self._synthetic(fut_day, float(ctx.row["c"]), sm["d"], delta)
                tr.detail = f"chart-only, delta {delta:.2f} assumed"
            else:
                self._skip("no option prices for the strike")
                return None
            if frame is None:
                self._skip("no option prices for the strike")
                return None
            p = Position(sig, tr, [frame], [1])
            p.entry_fut, sm["_delta"] = float(ctx.row["c"]), delta
            return p
        spreads = sm.get("spreads")
        if opt is None or not spreads:
            self._skip("credit spread without option prices")
            return None
        frames, signs = [], []
        for s in spreads:
            for leg, sign in ((s.short, -1), (s.hedge, 1)):
                f = opt.day(leg.strike, leg.kind)
                if f is None:
                    self._skip("no option prices for a spread leg")
                    return None
                frames.append(f)
                signs.append(sign)
        tr.detail = " + ".join(s.label for s in spreads)
        return Position(sig, tr, frames, signs)

    def _fill(self, pos: Position, ctx: Ctx) -> bool:
        """Fill at the open of the candle after the signal. False = no fill, drop the trade."""
        sm, slip = pos.sig.sim, self.o.slippage
        bars = [self._bar(f, ctx.ts) for f in pos.frames]
        if any(b is None for b in bars):
            self._skip("no option candle at entry")
            return False
        if sm["kind"] == "buy":
            if abs(float(ctx.row["o"]) - pos.entry_fut) > 3.0:
                self._skip("index moved more than 3 points before entry")
                return False
            px = float(bars[0]["o"]) + slip
            pos.fills_buy.append(px)
            pos.trade.entry = px
            pos.stop_px = px - 1.5 * sm["S"] * sm["_delta"]
        else:
            credit = 0.0
            for b, sign in zip(bars, pos.signs):
                px = float(b["o"]) + sign * slip          # buy the hedge higher, sell the short lower
                (pos.fills_buy if sign > 0 else pos.fills_sell).append(px)
                credit -= sign * px
            need = self.r.min_credit_condor if len(pos.frames) == 4 else self.r.min_credit
            if credit < need:
                self._skip("credit below the minimum at entry")
                return False
            pos.trade.entry = credit
        pos.open, pos.trade.entry_time = True, ctx.ts.to_pydatetime()
        return True

    # -- exit
    def _exit(self, pos: Position, when, px: Optional[float], reason: str) -> None:
        tr, slip, lot = pos.trade, self.o.slippage, self.o.lot
        if pos.sig.sim["kind"] == "buy":
            if px is None:
                last = pos.frames[0][pos.frames[0].index <= pd.Timestamp(when)]
                px = float(last["c"].iloc[-1]) if not last.empty else tr.entry
            px = max(px - slip, 0.05)
            pos.fills_sell.append(px)
            tr.exit, tr.points = px, px - tr.entry
        else:
            cost = 0.0
            for f, sign in zip(pos.frames, pos.signs):
                last = f[f.index <= pd.Timestamp(when)]
                c = float(last["c"].iloc[-1]) if not last.empty else 0.0
                fill = max(c - sign * slip, 0.05)          # buy back the short higher, sell the hedge lower
                (pos.fills_sell if sign > 0 else pos.fills_buy).append(fill)
                cost -= sign * fill
            tr.exit, tr.points = cost, tr.entry - cost
        tr.rupees = tr.points * lot - round_trip_cost(pos.fills_buy, pos.fills_sell, lot)
        tr.exit_time, tr.reason = pd.Timestamp(when).to_pydatetime(), reason
        self.trades.append(tr)

    def _manage(self, pos: Position, ctx: Ctx, fut_day: pd.DataFrame) -> bool:
        """Advance one candle. Returns True when the position is finished (closed or never filled)."""
        if not pos.open:
            if not self._fill(pos, ctx):
                return True
        pos.bars += 1
        sm, row, now = pos.sig.sim, ctx.row, ctx.now
        if sm["kind"] == "buy":
            d, bar = sm["d"], self._bar(pos.frames[0], ctx.ts)
            flat = time(14, 45) if sm["expiry_day"] else time(15, 0)
            if bar is not None and float(bar["l"]) <= pos.stop_px:        # stop first: the conservative reading
                self._exit(pos, ctx.ts, pos.stop_px, "stop after T1 (entry+2)" if pos.t1_done else "disaster stop")
                return True
            reach = d * (float(row["h"] if d > 0 else row["l"]) - pos.entry_fut)
            if not pos.t1_done and reach >= sm["t1_pts"]:
                pos.t1_done = True
                if self.o.exit_at_t1:
                    self._exit(pos, ctx.ts, pos.trade.entry + sm["t1_pts"] * sm["_delta"], "T1")
                    return True
                pos.stop_px = pos.trade.entry + 2.0       # one lot: stop to entry + 2, trail under the 9 EMA
            close = float(row["c"])
            if pos.t1_done and d * (close - float(row["ema9"])) < 0:
                self._exit(pos, ctx.ts, None, "9 EMA trail")
                return True
            if not pos.t1_done and d * (close - sm["inval"]) < 0:
                self._exit(pos, ctx.ts, None, "invalidation close")
                return True
            if not pos.t1_done and pos.bars == 3 and d * (close - pos.entry_fut) < 0.5 * sm["S"]:
                self._exit(pos, ctx.ts, None, "time stop")
                return True
            if now.time() >= flat:
                self._exit(pos, ctx.ts, None, "flat-by time")
                return True
            return False
        # credit spread: judged on candle closes (legs have no shared intrabar high)
        bars = [self._bar(f, ctx.ts) for f in pos.frames]
        flat = time(13, 30) if (pos.sig.setup == "S1" and sm["expiry_day"]) else time(15, 0)
        if all(b is not None for b in bars):
            value = -sum(sign * float(b["c"]) for b, sign in zip(bars, pos.signs))
            credit, close = pos.trade.entry, float(row["c"])
            if value >= 1.5 * credit:
                self._exit(pos, ctx.ts, None, "1.5x credit stop")
                return True
            stop = sm["stop"]
            hit = False
            if stop[0] == "range":
                hit = close > stop[2] + stop[3] or close < stop[1] - stop[3]
            elif stop[0] == "vwap":
                hit = stop[1] * (close - float(row["vwap"])) < 0
            elif stop[0] == "extreme":
                hit = stop[2] * (close - stop[1]) > 0
            if hit:
                self._exit(pos, ctx.ts, None, "index stop")
                return True
            if value <= 0.5 * credit:
                self._exit(pos, ctx.ts, None, "50% target")
                return True
        if now.time() >= flat:
            self._exit(pos, ctx.ts, None, "flat-by time")
            return True
        return False


# ------------------------------------------------------------------------ report
def summarise(trades: list[Trade]) -> pd.DataFrame:
    rows = []
    groups = {}
    for t in trades:
        groups.setdefault(t.setup, []).append(t)
    for name, ts in sorted(groups.items()) + ([("ALL", trades)] if trades else []):
        pts = np.array([t.points for t in ts])
        rs = np.array([t.rupees for t in ts])
        wins, losses = rs[rs > 0], rs[rs <= 0]
        aw, al = (wins.mean() if len(wins) else 0.0), (-losses.mean() if len(losses) else 0.0)
        rows.append({
            "setup": name, "trades": len(ts), "win %": 100 * len(wins) / len(ts),
            "avg win ₹": aw, "avg loss ₹": al,
            "break-even win %": 100 * al / (aw + al) if aw + al > 0 else float("nan"),
            "net points": pts.sum(), "net ₹ (1 lot)": rs.sum(),
            "worst trade ₹": rs.min(), "max drawdown ₹": float((np.maximum.accumulate(rs.cumsum()) - rs.cumsum()).max()),
        })
    return pd.DataFrame(rows)


CAVEATS = """Read this before trusting the numbers:
 - 5-minute candles: a stop and a target inside one candle count as the stop.
 - No historical bid/ask: the spread rules were not applied; {slip} points of slippage per fill assumed.
 - Delta comes from option prices (Black-Scholes), so strike picks can differ slightly from live.
 - Every alert is taken at the next candle's open, one lot of {lot}, charges at today's rates.
 - Lot size, expiry day and session hours changed over 2024-2026; older periods fit the rules less well.
 - Days to expiry count weekdays, so a holiday can shift the Monday/Tuesday rules by a day.
 - S1: the whole condor is closed on an index stop (the sheet closes only the threatened side).
 - Expected move uses the VIX formula every day (live uses the ATM straddle on expiry day).
 - Groww's history can run a few days behind, so the most recent sessions may be missing."""


def report(bt: Backtest, start: date, end: date) -> str:
    out = [f"Backtest {start} to {end} · {bt.signals} alerts · {len(bt.trades)} trades simulated"
           + ("" if bt.o.use_options else " · CHART-ONLY (no option prices, sells skipped, no time decay)")]
    if bt.trades:
        df = summarise(bt.trades)
        fmt = {c: (lambda v: f"{v:,.0f}") for c in df.columns if "₹" in c or c == "net points"}
        fmt.update({"win %": lambda v: f"{v:.0f}", "break-even win %": lambda v: f"{v:.0f}"})
        out += ["", df.to_string(index=False, formatters=fmt), ""]
        out.append("A setup has an edge here only if its win % is above its break-even win %.")
        reasons: dict[str, int] = {}
        for t in bt.trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
        out.append("Exits: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    else:
        out.append("No trades.")
    if bt.skipped:
        out.append("Alerts not traded: " + ", ".join(f"{k} {v}" for k, v in sorted(bt.skipped.items(), key=lambda x: -x[1])))
    out += ["", CAVEATS.format(slip=bt.o.slippage, lot=bt.o.lot)]
    return "\n".join(out)


def write_trades(trades: list[Trade], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "setup", "side", "signal_time", "entry_time", "exit_time", "entry", "exit",
                    "points", "rupees_1lot", "exit_reason", "detail"])
        for t in trades:
            w.writerow([t.day, t.setup, t.side, t.signal_time, t.entry_time, t.exit_time, f"{t.entry:.2f}",
                        f"{t.exit:.2f}", f"{t.points:.2f}", f"{t.rupees:.0f}", t.reason, t.detail])
