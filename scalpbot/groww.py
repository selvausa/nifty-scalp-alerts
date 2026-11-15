"""Groww Trading API adapter.

Response shapes are parsed defensively because they were written from the SDK source
and public docs without a live account; run `python -m scalpbot doctor` to verify.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import IST, Settings
from .options import Chain, Leg

log = logging.getLogger("scalpbot.groww")
FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Inst:
    groww_symbol: str
    trading_symbol: str
    segment: str
    lot_size: int = 0
    expiry: str = ""


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def parse_candles(payload: dict) -> pd.DataFrame:
    """Candles as [timestamp, open, high, low, close, volume, ...]; timestamp is epoch
    seconds/milliseconds or an IST date-time string. Returns naive-IST indexed OHLCV."""
    rows = _first(payload, "candles", default=[]) or []
    idx, data = [], []
    for c in rows:
        if not c or len(c) < 5:
            continue
        t = c[0]
        if isinstance(t, (int, float)):
            sec = t / 1000 if t > 1e11 else t
            ts = datetime.fromtimestamp(sec, IST).replace(tzinfo=None)
        else:
            ts = pd.Timestamp(str(t))
            ts = (ts.tz_convert(IST).tz_localize(None) if ts.tzinfo else ts).to_pydatetime()
        idx.append(pd.Timestamp(ts))
        data.append([_num(c[1]), _num(c[2]), _num(c[3]), _num(c[4]), _num(c[5]) if len(c) > 5 else 0.0])
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx), columns=["o", "h", "l", "c", "v"])
    return df[~df.index.duplicated(keep="last")].sort_index()


def parse_chain(payload: dict, expiry: str) -> Chain:
    spot = _num(_first(payload, "underlying_ltp", "underlyingLtp", "spot_price"))
    legs: dict[tuple[int, str], Leg] = {}
    strikes = _first(payload, "strikes", "option_chain", default={}) or {}
    items = strikes.items() if isinstance(strikes, dict) else ((s.get("strike_price"), s) for s in strikes)
    for k, row in items:
        try:
            strike = int(round(float(k)))
        except (TypeError, ValueError):
            continue
        for kind in ("CE", "PE"):
            d = _first(row, kind, kind.lower())
            if not isinstance(d, dict):
                continue
            g = _first(d, "greeks", default={}) or {}
            legs[(strike, kind)] = Leg(
                strike=strike, kind=kind,
                symbol=str(_first(d, "trading_symbol", "tradingSymbol", default="")),
                ltp=_num(_first(d, "ltp", "last_price")),
                delta=_num(_first(g, "delta", default=_first(d, "delta"))),
            )
    return Chain(spot=spot, expiry=expiry, legs=legs)


def parse_quote(payload: dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(bid, ask, last) from a quote payload."""
    depth = _first(payload, "depth", default={}) or {}

    def top(side: str) -> Optional[float]:
        lv = _first(depth, side, default=[]) or []
        p = _num(lv[0].get("price")) if lv and isinstance(lv[0], dict) else 0.0
        return p or None

    bid = _num(_first(payload, "bid_price", "bidPrice")) or top("buy")
    ask = _num(_first(payload, "offer_price", "ask_price", "offerPrice")) or top("sell")
    last = _num(_first(payload, "last_price", "ltp")) or None
    return bid or None, ask or None, last


class Groww:
    def __init__(self, s: Settings):
        self.s = s
        self.api = None
        self.fut: Optional[Inst] = None
        self.vix: Optional[Inst] = None
        self.expiry: str = ""
        self.mode = s.candle_api if s.candle_api in ("v2", "legacy") else "v2"
        self.auto = s.candle_api not in ("v2", "legacy")
        self._modes: dict[str, str] = {}      # endpoint that works, per instrument
        self._hist: dict[str, tuple[date, pd.DataFrame]] = {}   # prior sessions, per instrument
        self._inst: Optional[pd.DataFrame] = None
        self._day: Optional[date] = None

    # ------------------------------------------------------------ connection
    def connect(self, today: date) -> None:
        from growwapi import GrowwAPI

        s = self.s
        if s.groww_access_token:
            token = s.groww_access_token
        elif s.groww_api_key and s.groww_totp_secret:
            import pyotp

            token = GrowwAPI.get_access_token(api_key=s.groww_api_key, totp=pyotp.TOTP(s.groww_totp_secret).now())
        elif s.groww_api_key and s.groww_api_secret:
            token = GrowwAPI.get_access_token(api_key=s.groww_api_key, secret=s.groww_api_secret)
        else:
            raise RuntimeError("Set GROWW_API_KEY with GROWW_TOTP_SECRET or GROWW_API_SECRET, or GROWW_ACCESS_TOKEN")
        self.api = GrowwAPI(token)
        # the day is recorded only once everything resolved, so a failed lookup is retried
        self._inst, self._day = None, None
        self._resolve(today)
        self._day = today

    def ensure(self, today: date) -> None:
        if self.api is None or self._day != today:   # Groww tokens expire daily
            self.connect(today)

    def instruments(self) -> pd.DataFrame:
        if self._inst is None:
            df = self.api.get_all_instruments().copy()
            df.columns = [str(c).strip().lower() for c in df.columns]
            self._inst = df
        return self._inst

    def _resolve(self, today: date) -> None:
        s, tday = self.s, today.isoformat()
        df = None
        self.vix = None
        try:
            df = self.instruments()
            und = df[(df["underlying_symbol"].astype(str) == "NIFTY") & (df["exchange"].astype(str) == "NSE")]
            und = und.assign(_exp=und["expiry_date"].astype(str).str[:10])
            und = und[und["_exp"] >= tday]
        except Exception as e:
            log.warning("Instrument list unavailable (%s); relying on overrides", e)
            und = None
        # futures: nearest monthly contract
        if s.fut_groww_symbol:
            self.fut = Inst(s.fut_groww_symbol, s.fut_trading_symbol, "FNO", 65)
        elif und is not None:
            f = und[und["instrument_type"].astype(str).str.upper().isin(["FUT", "FUTIDX"])].sort_values("_exp")
            if f.empty:
                raise RuntimeError("No NIFTY future found in the instrument list; set FUT_GROWW_SYMBOL")
            r = f.iloc[0]
            self.fut = Inst(str(r["groww_symbol"]), str(r["trading_symbol"]), "FNO",
                            int(_num(r.get("lot_size"), 65)) or 65, r["_exp"])
        else:
            raise RuntimeError("Set FUT_GROWW_SYMBOL and FUT_TRADING_SYMBOL")
        # India VIX
        if s.vix_groww_symbol:
            self.vix = Inst(s.vix_groww_symbol, s.vix_trading_symbol, "CASH")
        elif df is not None:
            ts = df["trading_symbol"].astype(str).str.upper()
            nm = df["name"].astype(str).str.upper() if "name" in df else ts
            v = df[(ts.str.replace(" ", "").str.contains("INDIAVIX") | nm.str.replace(" ", "").str.contains("INDIAVIX"))
                   & (df["exchange"].astype(str) == "NSE") & (df["segment"].astype(str) == "CASH")]
            if not v.empty:
                r = v.iloc[0]
                self.vix = Inst(str(r["groww_symbol"]), str(r["trading_symbol"]), "CASH")
        if self.vix is None:
            log.warning("India VIX instrument not found; set VIX_GROWW_SYMBOL. VIX-based checks will be off.")
        # nearest weekly option expiry
        exp = ""
        if und is not None:
            o = und[und["instrument_type"].astype(str).str.upper() == "CE"]
            if not o.empty:
                exp = o["_exp"].min()
        if not exp:
            p = self.api.get_expiries("NSE", "NIFTY", today.year, today.month)
            exp = min((e for e in p.get("expiries", []) if e >= tday), default="")
        if not exp:
            raise RuntimeError("Could not find the nearest NIFTY option expiry")
        self.expiry = exp

    @property
    def lot_size(self) -> int:
        return (self.fut.lot_size if self.fut else 0) or 65

    def dte(self, today: date) -> int:
        """Weekdays until the weekly expiry (0 on expiry day). Ignores holidays."""
        return int(np.busday_count(today, date.fromisoformat(self.expiry)))

    # ---------------------------------------------------------------- candles
    def _fetch(self, inst: Inst, start: datetime, end: datetime, mode: str) -> pd.DataFrame:
        if mode == "v2":
            p = self.api.get_historical_candles("NSE", inst.segment, inst.groww_symbol,
                                                start.strftime(FMT), end.strftime(FMT), "5minute", timeout=15)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                p = self.api.get_historical_candle_data(inst.trading_symbol, "NSE", inst.segment,
                                                        start.strftime(FMT), end.strftime(FMT), 5, timeout=15)
        return parse_candles(p)

    @staticmethod
    def _key(inst: Inst) -> str:
        return inst.groww_symbol or inst.trading_symbol

    def mode_for(self, inst: Inst) -> str:
        return self._modes.get(self._key(inst), self.mode)

    @staticmethod
    def _usable(inst: Inst, mode: str) -> bool:
        """v2 needs the Groww symbol; the older endpoint needs the trading symbol."""
        return bool(inst.groww_symbol if mode == "v2" else inst.trading_symbol)

    def candles(self, inst: Inst, start: datetime, end: datetime, need: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """5-minute candles. In auto mode, falls back to the other endpoint when this one
        errors or does not yet have the candle we need. The choice is remembered per
        instrument, so a problem with one symbol never changes how another is fetched."""
        mode = self.mode_for(inst)
        other = "legacy" if mode == "v2" else "v2"
        can_fall_back = self.auto and self._usable(inst, other)
        if self.auto and not self._usable(inst, mode) and can_fall_back:
            mode, other, can_fall_back = other, mode, False
        try:
            df = self._fetch(inst, start, end, mode)
        except Exception as e:
            if not can_fall_back:
                raise
            log.warning("%s candles failed for %s (%s); trying %s", mode, self._key(inst), e, other)
            df = self._fetch(inst, start, end, other)
            self._modes[self._key(inst)] = other
            return df
        if can_fall_back and need is not None and (df.empty or need not in df.index):
            try:
                alt = self._fetch(inst, start, end, other)
                if need in alt.index:
                    log.info("Using the %s candle endpoint for %s (it has the latest candle)", other, self._key(inst))
                    self._modes[self._key(inst)] = other
                    return alt
            except Exception as e:
                log.debug("fallback candle endpoint failed: %s", e)
        return df

    def _with_history(self, inst: Inst, end: datetime, need: Optional[pd.Timestamp], days: int) -> pd.DataFrame:
        """Prior sessions never change, so they are fetched once a day; each cycle
        then asks only for today's candles."""
        day = end.date()
        midnight = datetime.combine(day, datetime.min.time())
        key = self._key(inst)
        cached = self._hist.get(key)
        if cached is None or cached[0] != day:
            hist = self.candles(inst, midnight - timedelta(days=days), midnight)
            hist = hist[hist.index < pd.Timestamp(midnight)]
            if hist.empty:
                return self.candles(inst, midnight - timedelta(days=days), end, need)   # nothing to cache yet
            self._hist[key] = (day, hist)
        else:
            hist = cached[1]
        today = self.candles(inst, midnight, end, need)
        today = today[today.index >= pd.Timestamp(midnight)]
        return pd.concat([hist, today]) if not today.empty else hist

    def fut_candles(self, end: datetime, need: Optional[pd.Timestamp] = None, days: int = 7) -> pd.DataFrame:
        return self._with_history(self.fut, end, need, days)

    def vix_candles(self, end: datetime, days: int = 7) -> Optional[pd.DataFrame]:
        if self.vix is None:
            return None
        return self._with_history(self.vix, end, None, days)

    def spot(self) -> Optional[float]:
        p = self.api.get_ltp("NSE_NIFTY", "CASH", timeout=10)
        v = _num(p.get("NSE_NIFTY")) if isinstance(p, dict) else 0.0
        return v or None

    # ---------------------------------------------------------------- options
    def chain(self) -> Chain:
        return parse_chain(self.api.get_option_chain("NSE", "NIFTY", self.expiry, timeout=15), self.expiry)

    def fill_quote(self, leg: Leg) -> Leg:
        try:
            bid, ask, last = parse_quote(self.api.get_quote(leg.symbol, "NSE", "FNO", timeout=10))
            leg.bid, leg.ask = bid, ask
            if last:
                leg.ltp = last
        except Exception as e:
            log.warning("quote failed for %s: %s", leg.symbol, e)
        return leg

    def option_candles(self, leg: Leg) -> pd.DataFrame:
        gs = ""
        try:
            gs = str(self.api.get_instrument_by_exchange_and_trading_symbol("NSE", leg.symbol)["groww_symbol"])
        except Exception:
            pass
        now = datetime.now(IST).replace(tzinfo=None)
        start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        inst = Inst(gs, leg.symbol, "FNO")
        order = [m for m in (self.mode, "legacy" if self.mode == "v2" else "v2") if self._usable(inst, m)]
        err: Optional[Exception] = None
        for mode in order:   # does not change the endpoint chosen for index candles
            try:
                return self._fetch(inst, start, now, mode)
            except Exception as e:
                err = e
        raise err if err else RuntimeError("no option candles")


class GrowwOptions:
    """The option-data view the setups engine uses."""

    def __init__(self, g: Groww):
        self.g = g

    def chain(self) -> Chain:
        return self.g.chain()

    def fill_quote(self, leg: Leg) -> Leg:
        return self.g.fill_quote(leg)

    def candles(self, leg: Leg) -> pd.DataFrame:
        return self.g.option_candles(leg)
