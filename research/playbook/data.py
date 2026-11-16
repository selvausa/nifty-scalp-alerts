"""Load the cached NIFTY history (both windows) and build per-day features. Offline only."""
from __future__ import annotations
import math, os
from datetime import date, datetime, time
from pathlib import Path
import numpy as np, pandas as pd
from scalpbot.backtest import GrowwHistory, groww_symbol
from scalpbot.indicators import add_indicators, adx
from scalpbot.market import session_only

CACHE = Path("data/cache")
WINDOWS = [(date(2025, 11, 1), date(2026, 4, 30)), (date(2026, 5, 1), date(2026, 10, 31))]


def load():
    hs = [GrowwHistory(None, a, b, CACHE, offline=True) for a, b in WINDOWS]
    cat = lambda xs: (lambda d: d[~d.index.duplicated(keep="last")].sort_index())(pd.concat([x for x in xs if x is not None]))
    fut, spot, vix = cat([h.fut for h in hs]), cat([h.spot for h in hs]), cat([h.vix for h in hs])
    expiries = sorted(set(hs[0].expiries) | set(hs[1].expiries))
    return fut, spot, vix, expiries, hs


def sess(df):
    t = df.index.time
    return df[(t >= time(9, 15)) & (t < time(15, 30))]


def option_day(expiry: date, strike: int, kind: str, day: date, _files=set()):
    if not _files:
        _files.update(os.listdir(CACHE))
    f = f"{groww_symbol(expiry, strike, kind)}_{day}_{day}.csv"
    if f not in _files:
        return None
    d = pd.read_csv(CACHE / f, index_col=0, parse_dates=True)
    return d if not d.empty else None
