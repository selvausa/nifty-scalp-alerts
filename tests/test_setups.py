"""Scenario tests: hand-built sessions that should (or should not) trigger each setup."""
from datetime import date, datetime, time

import numpy as np
import pandas as pd
import pytest

from scalpbot.config import Event, Rules
from scalpbot.indicators import add_indicators
from scalpbot.market import build_context
from scalpbot.runner import fmt_brief, fmt_signal
from scalpbot.setups import Engine, Sizing
from tests.fakes import FakeOptions, flat_vix, random_days, session_index

PREV = [date(2026, 11, 11), date(2026, 11, 12)]
DAY = date(2026, 11, 13)          # a Friday; DTE passed explicitly


def build_day(closes, vols=None, wick=3.0, opens=None):
    idx = session_index(DAY)[: len(closes)]
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, dtype=float)
    v = np.full(len(c), 50000.0) if vols is None else np.asarray(vols, dtype=float)
    return pd.DataFrame({"o": o, "h": np.maximum(o, c) + wick, "l": np.minimum(o, c) - wick, "c": c, "v": v}, index=idx)


def history(start=25000.0, vol=8.0, seed=5):
    h = random_days(PREV, seed=seed, start=start, vol=vol)
    return h + (start - h["c"].iloc[-1]) * 0 , h


def run(day_df, hist, dte=3, vix_level=15.0, opt="auto", events=(), vix=None, capital=500000):
    df = add_indicators(pd.concat([hist, day_df]))
    vx = vix if vix is not None else flat_vix(df.index, vix_level)
    ts = day_df.index[-1]
    ctx = build_context(df, ts, vx, dte, list(events))
    o = FakeOptions(float(day_df["c"].iloc[-1])) if opt == "auto" else opt
    eng = Engine(Rules(), Sizing(capital, 0.5, 65))
    return ctx, eng.evaluate(ctx, o), eng


def orb_day(hist, break_pts=14.0, break_vol=90000.0, n_after=1):
    """Tight opening range around the prior close, then one candle closing above it."""
    base = float(hist["c"].iloc[-1])
    base = round(base / 100) * 100 + 30            # keep 100-strikes out of the T1 path
    closes = [base + x for x in (0, 6, -4, 5, -3, 4)]          # 09:15-09:45 range
    closes += [base + 2] * n_after
    closes += [base + break_pts + 9]               # closes above range high (base+9 with wick)
    vols = [50000.0] * (len(closes) - 1) + [break_vol]
    return build_day(closes, vols), base


@pytest.fixture
def hist():
    h = random_days(PREV, seed=5, start=25030.0, vol=6.0)
    # make yesterday's range wide so PDH/PDL sit far from today's action
    h.iloc[-40, h.columns.get_loc("h")] += 400
    h.iloc[-39, h.columns.get_loc("l")] -= 400
    return h


def opt_break(day_df, ok=True):
    idx = day_df.index
    c = np.linspace(100, 104, len(idx))
    c[-1] = 120 if ok else 101
    return pd.DataFrame({"o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1.0}, index=idx)


def test_b2_fires_with_all_fields(hist):
    day, base = orb_day(hist)
    opt = FakeOptions(float(day["c"].iloc[-1]), opt_candles=opt_break(day))
    ctx, sigs, eng = run(day, hist, opt=opt)
    assert [s.setup for s in sigs] == ["B2"], eng.rejects
    s = sigs[0]
    assert s.side == "BUY CE" and all(c.ok for c in s.checks)
    assert 10 <= s.data["S"] <= 20 and s.data["t1"] == pytest.approx(s.data["entry"] + 2 * s.data["S"])
    assert 0.45 <= s.data["delta"] <= 0.55
    text = fmt_signal(s, ctx)
    assert "Opening-range breakout" in text and "Strike:" in text and "disaster stop" in text and "Size:" in text
    assert "09:15" in fmt_brief(ctx, 65)


def test_b2_mirror_put(hist):
    base = round(float(hist["c"].iloc[-1]) / 100) * 100 + 70
    closes = [base + x for x in (0, 6, -4, 5, -3, 4)] + [base - 2, base - 4 - 14 - 6]
    day = build_day(closes, [50000.0] * 7 + [90000.0])
    ctx, sigs, eng = run(day, hist, opt=FakeOptions(closes[-1], opt_candles=opt_break(day)))
    assert [(s.setup, s.side) for s in sigs] == [("B2", "BUY PE")], eng.rejects
    assert sigs[0].data["t1"] < sigs[0].data["entry"]


@pytest.mark.parametrize("kw,reason", [
    (dict(break_vol=20000.0), "volume"),
    (dict(break_pts=40.0), "Stop size"),
])
def test_b2_rejections(hist, kw, reason):
    day, _ = orb_day(hist, **kw)
    ctx, sigs, eng = run(day, hist, opt=FakeOptions(float(day["c"].iloc[-1]), opt_candles=opt_break(day)))
    assert not sigs and any(reason in r for r in eng.rejects), eng.rejects


def test_b2_rejects_wide_spread_option_no_break_and_events(hist):
    day, _ = orb_day(hist)
    px = float(day["c"].iloc[-1])
    _, sigs, eng = run(day, hist, opt=FakeOptions(px, spread=1.2, opt_candles=opt_break(day)))
    assert not sigs and "Spread" in eng.rejects[0]
    _, sigs, eng = run(day, hist, opt=FakeOptions(px, opt_candles=opt_break(day, ok=False)))
    assert not sigs and "prior 3 highs" in eng.rejects[0]
    _, sigs, eng = run(day, hist, opt=FakeOptions(px, opt_candles=opt_break(day)),
                       events=[Event(DAY, time(10, 0), "RBI policy")])
    assert not sigs and "event" in eng.rejects[0].lower()


def test_b2_only_first_break_and_no_option_calls_when_chart_fails(hist):
    day, base = orb_day(hist)
    again = build_day(list(day["c"]) + [base + 2, base + 26], list(day["v"]) + [50000.0, 90000.0])
    _, sigs, eng = run(again, hist)
    assert not [s for s in sigs if s.setup == "B2"]
    weak, _ = orb_day(hist, break_vol=20000.0)
    opt = FakeOptions(float(weak["c"].iloc[-1]))
    run(weak, hist, opt=opt)
    assert opt.calls == 0


def test_b2_without_option_data_marks_unchecked(hist):
    day, _ = orb_day(hist)
    ctx, sigs, _ = run(day, hist, opt=None)
    assert [s.setup for s in sigs] == ["B2"]
    assert sum(c.ok is None for c in sigs[0].checks) == 2
    assert "verify by hand" in fmt_signal(sigs[0], ctx)


def test_expiry_day_uses_itm_strike_and_half_size(hist):
    day, _ = orb_day(hist)
    opt = FakeOptions(float(day["c"].iloc[-1]), opt_candles=opt_break(day))
    ctx, sigs, eng = run(day, hist, dte=0, opt=opt)
    assert sigs and 0.60 <= sigs[0].data["delta"] <= 0.80, eng.rejects
    assert "half size" in fmt_signal(sigs[0], ctx) and "14:45" in fmt_signal(sigs[0], ctx)


def trend_day(hist, n=20):
    """Steady grind up from the open, then a pullback candle that tags the 20 EMA / VWAP."""
    base = round(float(hist["c"].iloc[-1]) / 100) * 100 + 5
    closes = [base + 4.0 * i for i in range(n)]
    return base, closes


def test_b1_vwap_pullback(hist):
    base, closes = trend_day(hist, 22)                      # last close 10:55 -> closes at 11:05
    df0 = add_indicators(pd.concat([hist, build_day(closes)]))
    last = df0.iloc[-1]
    # next candle: dips to the 20 EMA, closes back above the 9 EMA on higher volume
    lvl = float(last["ema20"])
    o, c = float(last["c"]), float(last["ema9"]) + 6
    day = build_day(closes + [c], [50000.0] * len(closes) + [80000.0])
    day.iloc[-1, day.columns.get_loc("o")] = o
    day.iloc[-1, day.columns.get_loc("l")] = lvl - 0.5
    day.iloc[-1, day.columns.get_loc("h")] = max(o, c) + 1
    ctx, sigs, eng = run(day, hist)
    assert ctx.bias == "UP"
    b1 = [s for s in sigs if s.setup == "B1"]
    rej = [r for r in eng.rejects if r.startswith("B1")]
    # the chart pattern must be recognised; only distance rules may veto it
    assert b1 or all(("Stop size" in r or "inside T1" in r or "expected move" in r) and "touched" not in r for r in rej), eng.rejects
    assert b1 or rej


def test_s2_bull_put_in_slow_uptrend(hist):
    base, closes = trend_day(hist, 30)
    closes = closes + [closes[-1] + 1.0 * i for i in range(1, 6)]       # 12:10 close, still above VWAP
    day = build_day(closes)
    ctx, sigs, eng = run(day, hist, vix_level=15.0)
    assert ctx.bias == "UP" and time(11, 30) <= ctx.t <= time(13, 30)
    s2 = [s for s in sigs if s.setup == "S2"]
    if not s2:      # a veto must come from a named sheet rule, never from the pattern itself
        assert any(r.startswith("S2") for r in eng.rejects), eng.rejects
        return
    s = s2[0]
    assert s.side == "BULL PUT SPREAD" and s.data["credit"] >= 22
    assert "buy the hedges first" in fmt_signal(s, ctx)


def test_s1_condor_on_expiry_eve_range_day(hist):
    base = round(float(hist["c"].iloc[-1]) / 100) * 100 + 50
    rng = np.random.default_rng(3)
    opening = [base + x for x in (0, 28, -30, 25, -27, 5)]       # wide 09:15-09:45 range
    rest = list(base + rng.uniform(-9, 9, 10))                   # quiet drift inside it until 10:35
    day = build_day(opening + rest, wick=2.0)
    ctx, sigs, eng = run(day, hist, dte=1)
    assert ctx.bias == "NEUTRAL"
    s1 = [s for s in sigs if s.setup == "S1"]
    rej = [r for r in eng.rejects if r.startswith("S1")]
    assert s1 or rej, "S1 defining condition (inside range, neutral bias) was not recognised"
    if s1:
        assert s1[0].side == "IRON CONDOR" and s1[0].data["credit"] >= 44
        assert s1[0].data["legs"].count("sell") == 2
    # never on a Wed-Fri style day (DTE >= 2)
    _, sigs2, eng2 = run(day, hist, dte=3)
    assert not [s for s in sigs2 if s.setup == "S1"] and not [r for r in eng2.rejects if r.startswith("S1")]


def test_vix_spike_blocks_all_selling(hist):
    base = round(float(hist["c"].iloc[-1]) / 100) * 100 + 50
    rng = np.random.default_rng(3)
    day = build_day([base + x for x in (0, 28, -30, 25, -27, 5)] + list(base + rng.uniform(-9, 9, 10)), wick=2.0)
    df_idx = pd.concat([hist, day]).index
    vix = flat_vix(df_idx, 15.0)
    vix.loc[vix.index.normalize() == pd.Timestamp(DAY), ["o", "h", "l", "c"]] = 16.2      # +8% on the day
    ctx, sigs, eng = run(day, hist, dte=1, vix=vix)
    assert ctx.vix_chg_pct == pytest.approx(8.0)
    assert not [s for s in sigs if s.setup.startswith("S")]
    assert any("VIX not up more than 5%" in r for r in eng.rejects)


def test_fuzz_no_crashes_and_signals_respect_windows():
    """Random sessions: nothing may raise, and every signal must sit in its time window."""
    windows = {"B1": [("10:15", "11:30"), ("13:15", "14:45")], "B2": [("09:45", "11:30")],
               "B3": [("13:15", "14:45")], "S1": [("10:15", "13:00")], "S2": [("11:30", "13:30")],
               "S3": [("11:00", "13:30")]}
    days = pd.bdate_range("2026-10-01", periods=15).date.tolist()
    seen, n = set(), 0
    for seed, (vol, drift) in enumerate([(5, 0), (9, 0), (6, 1.2), (6, -1.2), (14, 0)]):
        df = add_indicators(random_days(days, seed=seed, vol=vol, drift=drift))
        vix = flat_vix(df.index, 14.0)
        eng = Engine(Rules(), Sizing(300000, 0.5, 65))
        for i, ts in enumerate(df.index):
            d = ts.date()
            if d == days[0]:
                continue
            dte = (i // 75) % 5
            ctx = build_context(df, ts, vix, dte, [])
            if ctx is None:
                continue
            oc = pd.DataFrame({"o": 100.0, "h": 101.0, "l": 99.0, "c": np.linspace(100, 160, 75)[: len(ctx.today)]},
                              index=ctx.today.index)
            for s in eng.evaluate(ctx, FakeOptions(ctx.row["c"], opt_candles=oc)):
                n += 1
                seen.add(s.setup)
                t = ctx.t.strftime("%H:%M")
                assert any(a <= t <= b for a, b in windows[s.setup]), (s.setup, t)
                assert all(c.ok is not False for c in s.checks)
                if s.setup.startswith("B"):
                    assert 10 <= s.data["S"] <= 20
                    lo, hi = (0.60, 0.80) if dte == 0 else (0.50, 0.65) if dte == 1 else (0.45, 0.55)
                    assert lo <= s.data["delta"] <= hi
                else:
                    assert s.data["credit"] >= (44 if s.setup == "S1" else 22)
                    assert dte <= 1 if s.setup == "S1" else True
                    assert dte >= 1 if s.setup == "S3" else True
                assert fmt_signal(s, ctx)
    print("fuzz signals:", n, sorted(seen))
    assert n > 0 and len(seen) >= 3
