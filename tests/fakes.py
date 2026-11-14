"""Synthetic market data and a fake Groww for tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from scalpbot.options import Chain, Leg


def session_index(day: date) -> pd.DatetimeIndex:
    return pd.date_range(datetime.combine(day, datetime.min.time()) + timedelta(hours=9, minutes=15),
                         periods=75, freq="5min")


def random_days(days: list[date], seed: int = 0, start: float = 25000.0, vol: float = 12.0,
                drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames, px = [], start
    for d in days:
        idx = session_index(d)
        px += rng.normal(0, 30)
        steps = rng.normal(drift, vol, len(idx))
        c = px + np.cumsum(steps)
        o = np.concatenate([[px], c[:-1]])
        h = np.maximum(o, c) + rng.uniform(0, vol / 2, len(idx))
        l = np.minimum(o, c) - rng.uniform(0, vol / 2, len(idx))
        v = rng.integers(20000, 90000, len(idx)).astype(float)
        frames.append(pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "v": v}, index=idx))
        px = c[-1]
    return pd.concat(frames)


def flat_vix(index: pd.DatetimeIndex, level: float = 15.0) -> pd.DataFrame:
    return pd.DataFrame({"o": level, "h": level + 0.02, "l": level - 0.02, "c": level, "v": 0.0}, index=index)


def make_chain(spot: float, sigma_pts: float = 150.0) -> Chain:
    """A rough chain: delta from a normal CDF, premium = intrinsic + time value."""
    from math import erf, sqrt

    legs = {}
    atm = int(round(spot / 50) * 50)
    for k in range(atm - 1500, atm + 1501, 50):
        z = (spot - k) / sigma_pts
        cdf = 0.5 * (1 + erf(z / sqrt(2)))
        tv = 0.4 * sigma_pts * np.exp(-z * z / 2)
        legs[(k, "CE")] = Leg(k, "CE", f"NIFTY{k}CE", round(max(spot - k, 0) + tv, 2), round(cdf, 3))
        legs[(k, "PE")] = Leg(k, "PE", f"NIFTY{k}PE", round(max(k - spot, 0) + tv, 2), round(cdf - 1, 3))
    return Chain(spot, "2026-11-17", legs)


class FakeOptions:
    def __init__(self, spot: float, spread: float = 0.10, opt_candles: pd.DataFrame | None = None):
        self._chain = make_chain(spot)
        self.spread = spread
        self.opt_candles = opt_candles
        self.calls = 0

    def chain(self) -> Chain:
        self.calls += 1
        return self._chain

    def fill_quote(self, leg: Leg) -> Leg:
        leg.bid, leg.ask = leg.ltp - self.spread / 2, leg.ltp + self.spread / 2
        return leg

    def candles(self, leg: Leg) -> pd.DataFrame:
        if self.opt_candles is None:
            raise RuntimeError("no candles")
        return self.opt_candles
