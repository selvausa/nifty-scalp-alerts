"""Builds the per-candle market context the setups read."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

from .config import Event, hm
from .indicators import ema, to_15m

FIVE = pd.Timedelta(minutes=5)
SESSION_START, SESSION_END = time(9, 15), time(15, 45)   # F&O trades to 15:40
MIN_SESSION_CANDLES = 30     # shorter sessions (Diwali muhurat) are not a "previous day"


@dataclass
class Ctx:
    ts: pd.Timestamp              # start of the signal (last closed) candle
    now: datetime                 # its close time
    row: pd.Series                # the signal candle with indicators
    prev: pd.Series               # the candle before it
    today: pd.DataFrame           # today's candles up to and including the signal candle
    hist: pd.DataFrame            # all candles up to and including the signal candle
    m15: pd.DataFrame             # closed 15-minute candles with ema20
    pdh: float
    pdl: float
    pdc: float
    cpr: tuple[float, float, float]   # bottom, pivot, top
    r1: float
    s1: float
    or15: Optional[tuple[float, float]]   # 09:15-09:30 low, high
    or30: Optional[tuple[float, float]]   # 09:15-09:45 low, high
    or30_avg_vol: float
    bias: str                     # UP / DOWN / NEUTRAL / n/a (before 10:15)
    em: float                     # expected daily move, index points
    vix: float
    vix_chg_pct: float
    vix_rising: bool
    vix_higher_high: bool
    vix_fall_sharp: bool
    dte: int                      # trading-calendar proxy: days to the weekly expiry
    basis: float = 0.0            # futures minus spot
    events: list[Event] = field(default_factory=list)

    @property
    def t(self) -> time:
        return self.now.time()

    def within(self, a: str, b: str) -> bool:
        return hm(a) <= self.t <= hm(b)

    @property
    def day_open(self) -> float:
        return float(self.today["o"].iloc[0])

    @property
    def day_high(self) -> float:
        return float(self.today["h"].max())

    @property
    def day_low(self) -> float:
        return float(self.today["l"].min())

    @property
    def day_range(self) -> float:
        return self.day_high - self.day_low

    @property
    def range_used(self) -> float:
        """Share of the expected move the day's range has used; NaN when unknown."""
        return self.day_range / self.em if self.em and not math.isnan(self.em) else float("nan")

    @property
    def is_event_day(self) -> bool:
        return bool(self.events)

    @property
    def buys_blocked_by_event(self) -> bool:
        """Buys only after the release time plus one closed 5-min candle."""
        for e in self.events:
            if e.at is None:
                return True
            if self.now < datetime.combine(self.now.date(), e.at) + timedelta(minutes=5):
                return True
        return False

    @property
    def vwap_crosses_10(self) -> int:
        d = (self.today["c"] - self.today["vwap"]).tail(11)
        s = d.apply(lambda x: 1 if x > 0 else -1)
        return int((s.diff().abs() > 0).sum())

    @property
    def squeeze_now(self) -> bool:
        return session_low_width_recent(self.today, include_last=True)

    def spot(self, fut_price: float) -> float:
        return fut_price - self.basis


def session_low_width_recent(today: pd.DataFrame, lookback: int = 6, include_last: bool = False) -> bool:
    """Bollinger width made its session low within the last `lookback` candles."""
    w = today["bb_w"] if include_last else today["bb_w"].iloc[:-1]
    w = w.dropna()
    if len(w) < lookback + 3:
        return False
    return int(w.values.argmin()) >= len(w) - lookback


def session_only(df: pd.DataFrame) -> pd.DataFrame:
    t = df.index.time
    return df[(t >= SESSION_START) & (t < SESSION_END)]


def expected_move(spot: float, vix: float) -> float:
    return spot * vix / 100 / math.sqrt(252)


def build_context(
    df: pd.DataFrame,
    ts: pd.Timestamp,
    vix: Optional[pd.DataFrame],
    dte: int,
    events: list[Event],
    basis: float = 0.0,
    em_override: Optional[float] = None,
    vix_fall_pct: float = 1.0,
) -> Optional[Ctx]:
    """`df` is the futures 5-min frame with indicators; `ts` the signal candle start.

    Returns None when there is not enough data (no prior session, or indicators unset).
    """
    hist = df[df.index <= ts]
    if ts not in hist.index or len(hist) < 2:
        return None
    day = ts.normalize()
    today = hist[hist.index.normalize() == day]
    prior = hist[hist.index.normalize() < day]
    if prior.empty or today.empty:
        return None
    counts = prior.groupby(prior.index.normalize()).size()
    full = counts[counts >= MIN_SESSION_CANDLES]
    if full.empty:
        return None
    pd_ = prior[prior.index.normalize() == full.index[-1]]
    pdh, pdl, pdc = float(pd_["h"].max()), float(pd_["l"].min()), float(pd_["c"].iloc[-1])
    p = (pdh + pdl + pdc) / 3
    bc = (pdh + pdl) / 2
    tc = 2 * p - bc
    row = hist.iloc[-1]
    if pd.isna(row["atr"]) or pd.isna(row["adx"]):
        return None
    now = (ts + FIVE).to_pydatetime()

    def rng(n: int) -> Optional[tuple[float, float]]:
        o = today.iloc[:n]
        return (float(o["l"].min()), float(o["h"].max())) if len(o) == n else None

    or15, or30 = rng(3), rng(6)
    m15 = to_15m(hist, pd.Timestamp(now))
    m15 = m15.assign(ema20=ema(m15["c"], 20))
    bias = "n/a"
    if now.time() >= time(10, 15) and or15 and len(m15) >= 20:
        last = m15.iloc[-1]
        if last["c"] > last["ema20"] and last["c"] > or15[1]:
            bias = "UP"
        elif last["c"] < last["ema20"] and last["c"] < or15[0]:
            bias = "DOWN"
        else:
            bias = "NEUTRAL"

    v_now = v_chg = float("nan")
    v_rising = v_hh = v_fall = False
    em = em_override or float("nan")
    if vix is not None and not vix.empty:
        vh = vix[vix.index <= ts]
        vt = vh[vh.index.normalize() == day]
        vp = vh[vh.index.normalize() < day]
        if not vt.empty:
            v_now = float(vt["c"].iloc[-1])
            if not vp.empty:
                v_chg = (v_now / float(vp["c"].iloc[-1]) - 1) * 100
            if len(vt) >= 4:
                v_rising = v_now > float(vt["c"].iloc[-4])
                v_fall = (v_now / float(vt["c"].iloc[-4]) - 1) * 100 <= -abs(vix_fall_pct)
            if len(vt) >= 2:
                v_hh = float(vt["h"].iloc[-1]) > float(vt["h"].iloc[-2])
            if not em_override:
                # computed once from the first candle of the day (about 09:20)
                em = expected_move(float(today["c"].iloc[0]) - basis, float(vt["c"].iloc[0]))
    return Ctx(
        ts=ts, now=now, row=row, prev=hist.iloc[-2], today=today, hist=hist, m15=m15,
        pdh=pdh, pdl=pdl, pdc=pdc, cpr=(min(bc, tc), p, max(bc, tc)), r1=2 * p - pdl, s1=2 * p - pdh,
        or15=or15, or30=or30,
        or30_avg_vol=float(today["v"].iloc[:6].mean()) if or30 else float("nan"),
        bias=bias, em=em, vix=v_now, vix_chg_pct=v_chg, vix_rising=v_rising,
        vix_higher_high=v_hh, vix_fall_sharp=v_fall, dte=dte, basis=basis,
        events=[e for e in events if e.day == day.date()],
    )
