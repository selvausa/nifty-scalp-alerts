"""Indicator maths on a 5-minute OHLCV frame (columns o, h, l, c, v; DatetimeIndex)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["c"].shift()
    return pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(), (df["l"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df["h"].diff(), -df["l"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = wilder(true_range(df), n)
    pdi, mdi = 100 * wilder(pdm, n) / tr, 100 * wilder(mdm, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n)


def session_vwap(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Session-anchored VWAP and its volume-weighted standard deviation."""
    tp = (df["h"] + df["l"] + df["c"]) / 3
    day = df.index.normalize()
    v = df["v"].astype(float)
    cv = v.groupby(day).cumsum().replace(0, np.nan)
    vwap = (tp * v).groupby(day).cumsum() / cv
    var = (tp * tp * v).groupby(day).cumsum() / cv - vwap * vwap
    return vwap.fillna(tp), np.sqrt(var.clip(lower=0)).fillna(0.0)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["c"]
    for n in (9, 20, 50):
        df[f"ema{n}"] = ema(c, n)
    df["rsi"] = rsi(c)
    df["atr"] = atr(df)
    df["adx"] = adx(df)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_mid"], df["bb_up"], df["bb_lo"] = mid, mid + 2 * sd, mid - 2 * sd
    df["bb_w"] = (4 * sd) / mid
    df["vwap"], df["vwap_sd"] = session_vwap(df)
    return df


def to_15m(df: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Closed 15-minute candles (anchored at 09:15) from 5-minute ones, as of `asof`."""
    start = df.index.normalize() + pd.Timedelta(hours=9, minutes=15)
    bucket = start + ((df.index - start) // pd.Timedelta(minutes=15)) * pd.Timedelta(minutes=15)
    g = df.groupby(bucket)
    out = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()})
    return out[out.index + pd.Timedelta(minutes=15) <= asof]
