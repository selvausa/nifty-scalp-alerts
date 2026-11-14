"""The six setups from the cheat sheet, evaluated on a closed 5-minute candle.

Every threshold is an untested heuristic from the sheet. A signal is produced only
when no check fails; checks that could not be run (no option data) are marked None.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import time as dtime, timedelta
from typing import Optional

from .config import Rules
from .market import Ctx, session_low_width_recent
from .options import (
    Chain, CreditSpread, Leg, OptionsData, buy_delta_range, buy_spread_ok, legs_liquid, pick_buy,
    pick_credit_spread, sell_delta_range,
)


@dataclass
class Check:
    name: str
    ok: Optional[bool]
    detail: str = ""

    def __post_init__(self):
        # numpy booleans are not `False`; normalise so a failed check can never read as passed
        if self.ok is not None:
            self.ok = bool(self.ok)


@dataclass
class Signal:
    setup: str                  # B1..B3, S1..S3
    title: str
    side: str                   # e.g. "BUY CE", "BULL PUT SPREAD"
    key: str                    # dedupe key
    checks: list[Check]
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Sizing:
    capital: float = 0.0
    risk_pct: float = 0.5
    lot_size: int = 65

    def lots(self, risk_per_lot: float, half: bool) -> Optional[str]:
        if self.capital <= 0 or risk_per_lot <= 0:
            return None
        budget = self.capital * self.risk_pct / 100
        n = math.floor(budget / risk_per_lot)
        if half:
            n = n // 2
        if n < 1:
            return f"0 lots: one lot risks ₹{risk_per_lot:,.0f}, budget ₹{budget:,.0f}" + (" (half size)" if half else "")
        return f"{n} lot{'s' if n > 1 else ''} (risk ₹{n * risk_per_lot:,.0f} of ₹{budget:,.0f} budget{', half size' if half else ''})"


def _passed(checks: list[Check]) -> bool:
    return all(c.ok is not False for c in checks)


def _f(x: float) -> str:
    return f"{x:,.1f}"


class Engine:
    def __init__(self, rules: Rules, sizing: Sizing):
        self.r = rules
        self.sz = sizing
        self.rejects: list[str] = []   # why each setup did not fire on the last candle

    # ------------------------------------------------------------------ public
    def evaluate(self, ctx: Ctx, opt: Optional[OptionsData]) -> list[Signal]:
        self.rejects = []
        self._chain: Optional[Chain] = None
        out: list[Signal] = []
        for fn in (self._b1, self._b2, self._b3, self._s1, self._s2, self._s3):
            for sig in fn(ctx, opt):
                if _passed(sig.checks):
                    out.append(sig)
                else:
                    bad = [c.name for c in sig.checks if c.ok is False]
                    self.rejects.append(f"{sig.setup} {sig.side}: " + "; ".join(bad))
        return out

    def _get_chain(self, opt: OptionsData) -> Chain:
        if self._chain is None:
            self._chain = opt.chain()
        return self._chain

    # ------------------------------------------------------------- buy helpers
    def _levels_inside(self, ctx: Ctx, entry: float, d: int, dist: float) -> list[str]:
        lo, hi = (entry, entry + dist) if d > 0 else (entry - dist, entry)
        hit = [f"{n} {_f(v)}" for n, v in (("PDH", ctx.pdh), ("PDL", ctx.pdl)) if lo < v <= hi or (d < 0 and lo <= v < hi)]
        s_lo, s_hi = ctx.spot(lo), ctx.spot(hi)
        k = math.floor(s_hi / 100) * 100 if d > 0 else math.ceil(s_lo / 100) * 100
        if (d > 0 and s_lo < k <= s_hi) or (d < 0 and s_lo <= k < s_hi):
            hit.append(f"{int(k)} strike")
        return hit

    def _buy_common(self, ctx: Ctx, d: int, inval: float, level_check: bool, t1_cap: Optional[float] = None,
                    chop_veto: bool = True):
        """Shared buy rules. Returns (checks, S, T1 points)."""
        r, entry = self.r, float(ctx.row["c"])
        S = max(d * (entry - inval), float(ctx.row["atr"]))
        t1 = 2 * S
        if t1_cap is not None and 0 < t1_cap < t1:
            t1 = t1_cap
        cs = [Check("Stop size S is 10-20 points", r.s_min <= S <= r.s_max, f"S={_f(S)}")]
        if level_check:
            hit = self._levels_inside(ctx, entry, d, t1)
            cs.append(Check("No PDH/PDL or 100-strike inside T1", not hit, ", ".join(hit)))
        move_dir = 1 if entry >= ctx.day_open else -1
        used = ctx.day_range / ctx.em if ctx.em and not math.isnan(ctx.em) else float("nan")
        cs.append(Check("Day range under 100% of expected move (this direction)",
                        None if math.isnan(used) else not (used >= 1 and move_dir == d), f"{used:.0%} used"))
        # The sheet's chop rule vetoes pullback buys. A breakout (B2, B3) starts from a
        # range by definition, so there it is shown as a warning instead of a veto.
        chop = float(ctx.row["adx"]) < r.adx_trend and ctx.vwap_crosses_10 >= 3
        if chop_veto:
            cs.append(Check("Not chopping across VWAP with ADX below 20", not chop,
                            f"ADX {ctx.row['adx']:.0f}, {ctx.vwap_crosses_10} VWAP crosses"))
        self._chop = chop
        cs.append(Check("No event block", not ctx.buys_blocked_by_event,
                        ", ".join(e.name for e in ctx.events)))
        return cs, S, t1

    def _buy_option(self, ctx: Ctx, opt: Optional[OptionsData], d: int, need_break: bool):
        """Strike pick, spread rule and (B2/B3) the option's own breakout. Returns (checks, leg)."""
        lo, hi = buy_delta_range(ctx.dte)
        if opt is None:
            cs = [Check(f"Strike delta {lo:.2f}-{hi:.2f}, spread rule", None, "option data not checked")]
            if need_break:
                cs.append(Check("Option 5-min close above its prior 3 highs", None, "not checked"))
            return cs, None
        leg = pick_buy(self._get_chain(opt), d, ctx.dte)
        if leg is None:
            return [Check(f"Strike with delta {lo:.2f}-{hi:.2f}", False, "none in range")], None
        leg = opt.fill_quote(leg)
        cs = [Check(f"Strike delta {lo:.2f}-{hi:.2f}", True, f"{leg.label} Δ{abs(leg.delta):.2f}")]
        sp = leg.spread
        cs.append(Check("Spread at most ₹0.50 and 0.5%", buy_spread_ok(leg, self.r),
                        "no bid/ask" if sp is None else f"₹{sp:.2f} on ₹{leg.ltp:.1f}"))
        if need_break:
            ok, det = None, "no option candles"
            try:
                oc = opt.candles(leg)
                oc = oc[oc.index <= ctx.ts]
                if len(oc) >= 4 and oc.index[-1] == ctx.ts:
                    ok = float(oc["c"].iloc[-1]) > float(oc["h"].iloc[-4:-1].max())
                    det = f"close {oc['c'].iloc[-1]:.1f} vs {oc['h'].iloc[-4:-1].max():.1f}"
            except Exception as e:  # data problem must not hide the index signal
                det = f"option candles failed: {e}"
            cs.append(Check("Option 5-min close above its prior 3 highs", ok, det))
        return cs, leg

    def _buy_signal(self, ctx, opt, setup, title, d, inval, inval_text, cs, level_check, need_break,
                    t1_cap=None, extra_target=None) -> Signal:
        common, S, t1 = self._buy_common(ctx, d, inval, level_check, t1_cap, chop_veto=setup == "B1")
        cs = cs + common
        if ctx.bias in ("UP", "DOWN") and setup != "B1":
            cs.append(Check("15-min bias not against the trade", (ctx.bias == "UP") == (d > 0), ctx.bias))
        leg = None
        if _passed(cs):   # only spend option-data calls on candles that pass the chart checks
            ocs, leg = self._buy_option(ctx, opt, d, need_break)
            cs = cs + ocs
        entry = float(ctx.row["c"])
        side = "BUY CE" if d > 0 else "BUY PE"
        expiry_day = ctx.dte <= 0
        flat = "14:45" if expiry_day else "15:00"
        half = expiry_day or (ctx.vix > self.r.vix_half_size and ctx.vix_rising)
        lines = [
            f"Entry: limit within 60s and within 3 index pts of {_f(entry)} (fut); else skip",
            f"Invalidation: 5-min close {'below' if d > 0 else 'above'} {_f(inval)} ({inval_text})",
            f"S = {_f(S)} pts · T1 = {_f(entry + d * t1)} (fut, {'+' if d > 0 else '-'}{_f(t1)})"
            + (f" · then {extra_target}" if extra_target else ""),
        ]
        data = {"entry": entry, "inval": inval, "S": S, "t1": entry + d * t1}
        if leg is not None:
            dl = abs(leg.delta)
            stop_pts, t1_pts = 1.5 * S * dl, t1 * dl
            lines.insert(0, f"Strike: {leg.label} @ ₹{leg.ltp:.1f} (Δ {dl:.2f}"
                            + (f", spread ₹{leg.spread:.2f}" if leg.spread is not None else "") + ")")
            lines.append(f"Premium: disaster stop ₹{max(leg.ltp - stop_pts, 0):.1f} (-{stop_pts:.1f}) · "
                         f"T1 ₹{leg.ltp + t1_pts:.1f} (+{t1_pts:.1f})")
            lots = self.sz.lots(stop_pts * self.sz.lot_size + self.r.buy_cost, half)
            if lots:
                lines.append(f"Size: {lots}")
            data.update(strike=leg.label, premium=leg.ltp, delta=dl)
        elif half:
            lines.append("Size: half")
        ts_by = (ctx.now + timedelta(minutes=15)).strftime("%H:%M")
        lines.append(f"Time stop: exit if not at +0.5R by {ts_by} · flat by {flat}")
        lines.append("After T1: 2+ lots book half, trail under 9 EMA; 1 lot stop to entry+2, trail")
        notes = []
        if self._chop and setup != "B1":
            notes.append(f"ADX {ctx.row['adx']:.1f} is below 20 with {ctx.vwap_crosses_10} VWAP crosses in 10 candles: "
                         "the break is coming out of chop and may fail")
        if ctx.vix > self.r.vix_half_size and ctx.vix_rising:
            notes.append(f"VIX {ctx.vix:.1f} above 18 and rising: half size")
        if expiry_day:
            notes.append("Expiry day: ITM strike, half size, flat by 14:45")
        return Signal(setup, title, side, f"{setup}:{d}", cs, lines, notes, data)

    # --------------------------------------------------------------------- B1
    def _b1(self, ctx: Ctx, opt):
        if not (ctx.within("10:15", "11:30") or ctx.within("13:15", "14:45")):
            return
        row = ctx.row
        for d in (1, -1):
            want = "UP" if d > 0 else "DOWN"
            if ctx.bias != want:
                continue   # the core filter; skip quietly
            ext = float(row["l"] if d > 0 else row["h"])
            c = float(row["c"])
            touched = [n for n, L in (("VWAP", float(row["vwap"])), ("20 EMA", float(row["ema20"])))
                       if d * (ext - L) <= 1.0 and d * (c - L) > 0]
            cs = [
                Check(f"15-min bias {want}", True),
                Check("Candle touched VWAP or 20 EMA and closed beyond the 9 EMA",
                      bool(touched) and d * (c - float(row["ema9"])) > 0 and d * (c - float(row["vwap"])) > 0,
                      " and ".join(touched) or "no touch"),
                Check("Volume at least the prior candle's", float(row["v"]) >= float(ctx.prev["v"]),
                      f"{row['v']:,.0f} vs {ctx.prev['v']:,.0f}"),
                Check("ADX(14) is 20 or more", float(row["adx"]) >= self.r.adx_trend, f"{row['adx']:.0f}"),
            ]
            band = float(row["vwap"]) + d * float(row["vwap_sd"])
            yield self._buy_signal(ctx, opt, "B1", "VWAP pullback", d, ext,
                                   "pullback candle " + ("low" if d > 0 else "high"), cs,
                                   level_check=True, need_break=False, t1_cap=d * (band - c))

    # --------------------------------------------------------------------- B2
    def _b2(self, ctx: Ctx, opt):
        if not ctx.within("09:45", "11:30") or ctx.or30 is None or len(ctx.today) < 7:
            return
        lo, hi = ctx.or30
        row, c = ctx.row, float(ctx.row["c"])
        d = 1 if c > hi else -1 if c < lo else 0
        if d == 0:
            return
        earlier = ctx.today["c"].iloc[6:-1]
        first = not ((earlier > hi) | (earlier < lo)).any()
        if not first:
            return   # only the first close outside the range counts; skip quietly
        mid = (float(row["h"]) + float(row["l"])) / 2
        width = hi - lo
        em_ok = None if math.isnan(ctx.em) else width <= self.r.or_width_em_max * ctx.em
        cs = [
            Check("First 5-min close outside the opening range, in the outer half of its own range",
                  d * (c - mid) >= 0, f"range {_f(lo)}-{_f(hi)}"),
            Check("Break volume at least the opening-range average", float(row["v"]) >= ctx.or30_avg_vol,
                  f"{row['v']:,.0f} vs {ctx.or30_avg_vol:,.0f}"),
            Check("Range width at most 0.4 x expected move", em_ok, f"{_f(width)} vs EM {_f(ctx.em)}"),
            Check("Not an event day", not ctx.is_event_day),
            Check("No gap open beyond PDH/PDL", ctx.pdl <= ctx.day_open <= ctx.pdh, f"open {_f(ctx.day_open)}"),
        ]
        edge = hi if d > 0 else lo
        nxt = sorted((v for v in (ctx.pdh, ctx.pdl, ctx.r1, ctx.s1) if d * (v - c) > 0), key=lambda v: abs(v - c))
        yield self._buy_signal(ctx, opt, "B2", "Opening-range breakout", d, edge, "broken range edge", cs,
                               level_check=True, need_break=True,
                               extra_target=f"next level {_f(nxt[0])}" if nxt else None)

    # --------------------------------------------------------------------- B3
    def _b3(self, ctx: Ctx, opt):
        if not ctx.within("13:15", "14:45") or len(ctx.today) < 12:
            return
        row, c = ctx.row, float(ctx.row["c"])
        if any(map(lambda k: row[k] != row[k], ("bb_up", "bb_lo", "bb_mid"))):
            return
        d = 1 if c > float(row["bb_up"]) else -1 if c < float(row["bb_lo"]) else 0
        if d == 0 or not session_low_width_recent(ctx.today, self.r.squeeze_lookback):
            return   # no squeeze release on this candle; skip quietly
        prior6 = ctx.today.iloc[-7:-1]
        swing = float(prior6["h"].max() if d > 0 else prior6["l"].min())
        avg10 = float(ctx.today["v"].iloc[-11:-1].mean())
        cs = [
            Check("Band width made its session low within the prior 6 candles", True),
            Check("Close outside the band and beyond the squeeze range", d * (c - swing) > 0, f"swing {_f(swing)}"),
            Check("Break volume at least 1.5 x the prior-10 average", float(row["v"]) >= self.r.b3_vol_mult * avg10,
                  f"{row['v']:,.0f} vs {avg10:,.0f}"),
            Check("VIX not falling sharply on the break", not ctx.vix_fall_sharp, f"VIX {ctx.vix:.2f}"),
        ]
        yield self._buy_signal(ctx, opt, "B3", "Squeeze release", d, float(row["bb_mid"]), "20-SMA mid-band", cs,
                               level_check=False, need_break=True)

    # ------------------------------------------------------------ sell helpers
    def _sell_common(self, ctx: Ctx) -> list[Check]:
        vix_ok = None if math.isnan(ctx.vix_chg_pct) else ctx.vix_chg_pct <= self.r.vix_up_block_pct
        return [
            Check("India VIX not up more than 5% on the day", vix_ok, f"{ctx.vix_chg_pct:+.1f}%"),
            Check("Not an event day", not ctx.is_event_day, ", ".join(e.name for e in ctx.events)),
            Check("Before 13:30 (no new spreads after)", ctx.t <= dtime(13, 30)),
        ]

    def _spread_checks(self, opt: Optional[OptionsData], spreads: list[Optional[CreditSpread]], min_credit: float):
        if opt is None:
            return [Check(f"Strikes, credit at least {min_credit:.0f}, leg spreads at most ₹0.15", None,
                          "option data not checked")], None
        if any(s is None for s in spreads):
            return [Check("Short strike in the delta range past the level, with a 100-point hedge", False,
                          "none found")], None
        legs = [opt.fill_quote(l) for s in spreads for l in (s.short, s.hedge)]
        it = iter(legs)
        spreads = [CreditSpread(next(it), next(it)) for _ in spreads]
        credit = sum(s.credit for s in spreads)
        worst = max((l.spread for l in legs if l.spread is not None), default=None)
        return [
            Check("Short strike in the delta range past the level", True,
                  ", ".join(f"{s.short.label} Δ{abs(s.short.delta):.2f}" for s in spreads)),
            Check(f"Credit at least {min_credit:.0f} points", credit >= min_credit, f"{credit:.1f}"),
            Check("Each leg's bid-ask spread at most ₹0.15", legs_liquid(legs, self.r),
                  "no bid/ask" if worst is None else f"widest ₹{worst:.2f}"),
        ], (spreads, credit)

    def _sell_signal(self, ctx, setup, title, side, key, cs, picked, index_stop, cost, half, notes=None) -> Signal:
        lines, data = [], {}
        if picked:
            spreads, credit = picked
            lot = self.sz.lot_size
            lines.append("Legs: " + " + ".join(s.label for s in spreads) + " (buy the hedges first)")
            lines.append(f"Credit ≈ {credit:.1f} pts · target: buy back at {credit / 2:.1f} · "
                         f"stop: value {credit * 1.5:.1f} (1.5x)")
            lines.append(f"Max loss ≈ ₹{(self.r.spread_width - credit) * lot + cost:,.0f}/lot · "
                         f"loss at 1.5x stop ≈ ₹{0.5 * credit * lot + cost:,.0f}/lot")
            lots = self.sz.lots(0.5 * credit * lot + cost, half)
            if lots:
                lines.append(f"Size: {lots}")
            data.update(credit=credit, legs=" + ".join(s.label for s in spreads))
        elif half:
            lines.append("Size: half")
        lines.append(f"Index stop: {index_stop}")
        lines.append("Exit the shorts first · flat by 15:00 · check broker margin before entry")
        return Signal(setup, title, side, key, cs, lines, notes or [], data)

    # --------------------------------------------------------------------- S1
    def _s1(self, ctx: Ctx, opt):
        if ctx.dte > 1 or ctx.or30 is None:
            return
        if not ctx.within("10:15", "12:00" if ctx.dte <= 0 else "13:00"):
            return
        lo, hi = ctx.or30
        after = ctx.today["c"].iloc[6:]
        inside = bool(((after >= lo) & (after <= hi)).all())
        if not inside or ctx.bias != "NEUTRAL":
            return   # the defining condition; skip quietly
        row = ctx.row
        adx3 = float(ctx.today["adx"].iloc[-4]) if len(ctx.today) >= 4 else float("nan")
        yr = ctx.pdl <= ctx.day_open <= ctx.pdh
        cs = [
            Check("Price inside the opening range since 09:45 and 15-min bias NEUTRAL", True,
                  f"range {_f(lo)}-{_f(hi)}"),
            Check("ADX(14) below 20 and not rising", float(row["adx"]) < self.r.adx_trend and not float(row["adx"]) > adx3,
                  f"{row['adx']:.0f} (3 candles ago {adx3:.0f})"),
            Check("Opening range at least 4 x 5-min ATR wide", hi - lo >= self.r.or_width_atr_min * float(row["atr"]),
                  f"{_f(hi - lo)} vs ATR {row['atr']:.1f}"),
            Check("No squeeze on the 5-min bands", not ctx.squeeze_now),
            Check("No gap open outside yesterday's range", yr, f"open {_f(ctx.day_open)}"),
        ] + self._sell_common(ctx)
        picked = None
        if _passed(cs):
            spreads = None
            if opt is not None:
                ch, dr = self._get_chain(opt), sell_delta_range("S1", ctx.dte)
                spreads = [pick_credit_spread(ch, "PE", ctx.spot(lo), dr, self.r),
                           pick_credit_spread(ch, "CE", ctx.spot(hi), dr, self.r)]
            ocs, picked = self._spread_checks(opt, spreads or [], self.r.min_credit_condor)
            cs = cs + ocs
        half = ctx.dte <= 0
        notes = ["Expiry day: closed by 13:30, half size"] if half else []
        yield self._sell_signal(
            ctx, "S1", "Range iron condor", "IRON CONDOR", "S1:0", cs, picked,
            f"close the threatened side on a 5-min close {0.5 * float(row['atr']):.0f} pts (0.5 ATR) outside "
            f"{_f(lo)}-{_f(hi)} (fut), or if that short leg doubles", self.r.condor_cost, half, notes)

    # --------------------------------------------------------------------- S2
    def _s2(self, ctx: Ctx, opt):
        if not ctx.within("11:30", "13:30") or ctx.bias not in ("UP", "DOWN"):
            return
        d = 1 if ctx.bias == "UP" else -1
        row, c = ctx.row, float(ctx.row["c"])
        used = ctx.day_range / ctx.em if ctx.em and not math.isnan(ctx.em) else float("nan")
        cs = [
            Check(f"15-min bias {ctx.bias}", True),
            Check(f"Last 5-min futures close {'above' if d > 0 else 'below'} VWAP", d * (c - float(row["vwap"])) > 0,
                  f"{_f(c)} vs {_f(float(row['vwap']))}"),
            Check("ADX(14) is 20 or more", float(row["adx"]) >= self.r.adx_trend, f"{row['adx']:.0f}"),
            Check("Day range under 100% of expected move", None if math.isnan(used) else used < 1, f"{used:.0%} used"),
            Check("Not expiry day after 12:00", not (ctx.dte <= 0 and ctx.t > dtime(12, 0))),
        ] + self._sell_common(ctx)
        picked = None
        kind = "PE" if d > 0 else "CE"
        if _passed(cs):
            spreads = None
            if opt is not None:
                last12 = ctx.today.tail(12)
                swing = float(last12["l"].min() if d > 0 else last12["h"].max())
                lvl = min(float(row["vwap"]), swing) if d > 0 else max(float(row["vwap"]), swing)
                ch = self._get_chain(opt)
                sp = pick_credit_spread(ch, kind, ctx.spot(lvl), sell_delta_range("S2", ctx.dte), self.r)
                spreads = [sp]
                if sp is not None:
                    far = abs(ch.spot - sp.short.strike) >= 2 * float(row["atr"])
                    cs.append(Check("Short strike at least 2 x ATR from spot", far,
                                    f"{abs(ch.spot - sp.short.strike):.0f} pts vs {2 * row['atr']:.0f}"))
            ocs, picked = self._spread_checks(opt, spreads or [], self.r.min_credit)
            cs = cs + ocs
        side = "BULL PUT SPREAD" if d > 0 else "BEAR CALL SPREAD"
        yield self._sell_signal(ctx, "S2", "Trend-side credit spread", side, f"S2:{d}", cs, picked,
                                f"5-min futures close {'below' if d > 0 else 'above'} VWAP ({_f(float(row['vwap']))})",
                                self.r.spread_cost, ctx.dte <= 0)

    # --------------------------------------------------------------------- S3
    def _s3(self, ctx: Ctx, opt):
        if not ctx.within("11:00", "13:30") or ctx.dte <= 0 or math.isnan(ctx.em) or len(ctx.today) < 6:
            return
        if ctx.day_range < ctx.em:
            return   # the defining condition; skip quietly
        c = float(ctx.row["c"])
        up = c >= (ctx.day_high + ctx.day_low) / 2      # fading an up-move: bear call above the high
        ext = ctx.day_high if up else ctx.day_low
        last3 = ctx.today.tail(3)
        held = (float(last3["h"].max()) < ext) if up else (float(last3["l"].min()) > ext)
        m = ctx.m15
        inside15 = len(m) >= 2 and float(m["l"].iloc[-2]) <= float(m["c"].iloc[-1]) <= float(m["h"].iloc[-2])
        beyond_band = (c > ctx.day_open + ctx.em) if up else (c < ctx.day_open - ctx.em)
        cs = [
            Check("Day range at least 100% of the expected move", True, f"{_f(ctx.day_range)} vs EM {_f(ctx.em)}"),
            Check("Day extreme not exceeded for 3 closed candles", held, f"extreme {_f(ext)}"),
            Check("Last 15-min candle closed inside the prior 15-min range", inside15),
            Check("India VIX not making higher 5-min highs", not ctx.vix_higher_high, f"VIX {ctx.vix:.2f}"),
            Check("Not closing beyond the expected-move band with VIX rising", not (beyond_band and ctx.vix_rising)),
        ] + self._sell_common(ctx)
        picked = None
        kind = "CE" if up else "PE"
        if _passed(cs):
            spreads = None
            if opt is not None:
                spreads = [pick_credit_spread(self._get_chain(opt), kind, ctx.spot(ext),
                                              sell_delta_range("S3", ctx.dte), self.r)]
            ocs, picked = self._spread_checks(opt, spreads or [], self.r.min_credit)
            cs = cs + ocs
        side = "BEAR CALL SPREAD" if up else "BULL PUT SPREAD"
        yield self._sell_signal(ctx, "S3", "Exhaustion fade spread", side, f"S3:{1 if up else -1}", cs, picked,
                                f"5-min close beyond the day extreme {_f(ext)} (fut)", self.r.spread_cost, True,
                                ["Half size: max loss per lot is large at a small credit"])
