"""Backtest: option maths, charges, trade simulation and an end-to-end run on synthetic history."""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from scalpbot.backtest import (Backtest, GrowwHistory, HistOptions, Options, Position, Trade, bs_delta, bs_price,
                               delta_from_price, groww_symbol, implied_vol, monthly_expiries, report,
                               round_trip_cost, summarise, write_trades)
from scalpbot.config import Rules
from scalpbot.setups import Signal
from tests.fakes import flat_vix, random_days

IV = 0.12


class FakeHistory:
    """Futures random walk, spot 20 below it, options priced by Black-Scholes at a fixed volatility."""

    def __init__(self, days, seed=0, vol=7.0, drift=0.0, missing=()):
        self.fut = random_days(days, seed=seed, vol=vol, drift=drift)
        self.spot = self.fut[["o", "h", "l", "c"]] - 20.0
        self.vix = flat_vix(self.fut.index, 14.0)
        first = days[0]
        self.expiries = [d for d in (first + timedelta(days=i) for i in range(120)) if d.weekday() == 1]
        self.missing, self.requests = set(missing), 0

    def option_day(self, expiry, strike, kind, day):
        self.requests += 1
        if (strike, kind) in self.missing:
            return None
        s = self.spot[self.spot.index.normalize() == pd.Timestamp(day)]
        if s.empty:
            return None
        out = {}
        for col, src in (("o", "o"), ("c", "c"), ("h", "h" if kind == "CE" else "l"), ("l", "l" if kind == "CE" else "h")):
            vals = []
            for ts, px in s[src].items():
                when = ts if col == "o" else ts + pd.Timedelta(minutes=5)
                t = max((datetime.combine(expiry, time(15, 30)) - when).total_seconds(), 60) / (365 * 86400)
                vals.append(bs_price(px, strike, t, IV, kind))
            out[col] = vals
        return pd.DataFrame(out, index=s.index).assign(v=1.0)


DAYS = pd.bdate_range("2026-10-05", periods=16).date.tolist()


# ---------------------------------------------------------------- option maths
def test_black_scholes_roundtrip_and_delta():
    t = 3 / 365
    for kind in ("CE", "PE"):
        for strike in (24800, 25000, 25300):
            px = bs_price(25000, strike, t, 0.14, kind)
            assert implied_vol(px, 25000, strike, t, kind) == pytest.approx(0.14, abs=1e-4)
    assert bs_delta(25000, 25000, t, 0.14, "CE") == pytest.approx(0.5, abs=0.03)
    assert bs_delta(25000, 25000, t, 0.14, "CE") - bs_delta(25000, 25000, t, 0.14, "PE") == pytest.approx(1.0)
    assert bs_price(25000, 25000, t, 0.14, "CE") - bs_price(25000, 25000, t, 0.14, "PE") == pytest.approx(
        25000 - 25000 * np.exp(-0.065 * t))                                  # put-call parity
    now = datetime(2026, 11, 13, 10, 0)
    assert 0.9 < delta_from_price(405.0, 25400, 25000, date(2026, 11, 17), now, "CE") <= 1.0   # deep in the money
    assert delta_from_price(0.05, 25000, 26500, date(2026, 11, 17), now, "CE") < 0.02
    assert implied_vol(1.0, 25400, 25000, t, "CE") == 0.01                    # below intrinsic: clamps, no crash


def test_charges_match_the_cheat_sheet():
    assert round_trip_cost([120.0], [120.0], 65) == pytest.approx(65.69, abs=0.02)        # ATM buy box
    assert round_trip_cost([25.0, 60.0], [60.0, 25.0], 65) == pytest.approx(107.50, abs=0.05)   # credit spread box


def test_symbols_and_monthly_expiries():
    assert groww_symbol(date(2025, 9, 30)) == "NSE-NIFTY-30Sep25-FUT"
    assert groww_symbol(date(2025, 9, 2), 24650, "CE") == "NSE-NIFTY-02Sep25-24650-CE"
    ex = [date(2026, 10, 6), date(2026, 10, 13), date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 24)]
    assert monthly_expiries(ex) == [date(2026, 10, 27), date(2026, 11, 24)]


def test_hist_chain_has_no_lookahead_and_sane_deltas():
    h = FakeHistory(DAYS, seed=2)
    ts = h.fut.index[75 * 3 + 20]
    spot = float(h.spot.at[ts, "c"])
    exp = next(e for e in h.expiries if e >= ts.date())
    ch = HistOptions(h, ts, spot, exp).chain()
    atm = int(round(spot / 50) * 50)
    ce, pe = ch.get(atm, "CE"), ch.get(atm, "PE")
    assert 0.35 < ce.delta < 0.65 and -0.65 < pe.delta < -0.35
    deltas = [ch.get(k, "CE").delta for k in range(atm - 150, atm + 701, 50)]
    assert deltas == sorted(deltas, reverse=True)                              # falls with strike
    day = h.option_day(exp, atm, "CE", ts.date())
    assert ce.ltp == pytest.approx(day.at[ts, "c"])                            # price as of the signal candle
    assert ce.bid is None                                                      # no fabricated bid/ask


# ------------------------------------------------------------------ simulation
def buy_position(prices, d=1, S=12.0, t1=24.0, inval=24990.0, delta=0.5):
    """A filled long-option position starting at 10:00 with the given option candles."""
    idx = pd.date_range("2026-11-13 10:00", periods=len(prices), freq="5min")
    frame = pd.DataFrame(prices, columns=["o", "h", "l", "c"], index=idx)
    sig = Signal("B1", "t", "BUY CE" if d > 0 else "BUY PE", "B1:1", [])
    sig.sim = {"kind": "buy", "d": d, "inval": inval, "S": S, "t1_pts": t1, "leg": None, "expiry_day": False,
               "_delta": delta}
    p = Position(sig, Trade(date(2026, 11, 13), "B1", sig.side, datetime(2026, 11, 13, 10, 0)), [frame], [1])
    p.entry_fut = 25000.0
    return p, idx


class C:
    """The few context fields the simulator reads."""

    def __init__(self, ts, o, h, l, c, ema9=24000.0, vwap=25000.0):
        self.ts, self.now = ts, (ts + pd.Timedelta(minutes=5)).to_pydatetime()
        self.row = pd.Series({"o": o, "h": h, "l": l, "c": c, "ema9": ema9, "vwap": vwap})


def drive(bt, pos, idx, fut):
    for ts, bar in zip(idx, fut):
        if bt._manage(pos, C(ts, *bar), None):
            return
    raise AssertionError("position never closed")


def bt_(**kw):
    return Backtest(None, Rules(), Options(**kw))


def test_buy_disaster_stop_wins_when_stop_and_target_share_a_candle():
    pos, idx = buy_position([(100, 101, 99, 100), (100, 115, 88, 110)])
    bt = bt_()
    drive(bt, pos, idx, [(25000, 25004, 24996, 25001), (25001, 25030, 24995, 25020)])
    t = bt.trades[0]
    assert t.reason == "disaster stop"
    assert t.entry == pytest.approx(100.5) and t.exit == pytest.approx(100.5 - 9.0 - 0.5)   # 1.5 x S x delta, then slippage
    assert t.points == pytest.approx(-9.5) and t.rupees == pytest.approx(-9.5 * 65 - round_trip_cost([100.5], [91.0], 65))


def test_buy_t1_then_trail_or_book():
    prices = [(100, 103, 99, 102), (102, 114, 101, 113), (113, 116, 110, 111), (111, 112, 108, 109)]
    fut = [(25000, 25006, 24998, 25005), (25005, 25026, 25003, 25024), (25024, 25030, 25018, 25020),
           (25020, 25021, 25010, 25012)]
    pos, idx = buy_position(prices)
    bt = bt_(exit_at_t1=True)
    drive(bt, pos, idx, fut)
    assert bt.trades[0].reason == "T1" and bt.trades[0].points == pytest.approx(24 * 0.5 - 0.5)
    # trailing: 9 EMA sits at 25015, so the 25012 close exits
    pos, idx = buy_position(prices)
    bt = bt_()
    for ts, bar in zip(idx, fut):
        if bt._manage(pos, C(ts, *bar, ema9=25015.0), None):
            break
    t = bt.trades[0]
    assert t.reason == "9 EMA trail" and t.exit == pytest.approx(109 - 0.5) and t.exit_time == idx[3].to_pydatetime()
    # after T1 the stop sits at entry + 2
    pos, idx = buy_position(prices[:2] + [(113, 113, 101, 104)])
    bt = bt_()
    drive(bt, pos, idx, fut[:3])
    assert bt.trades[0].reason == "stop after T1 (entry+2)" and bt.trades[0].exit == pytest.approx(102.0)


def test_buy_invalidation_time_stop_flat_and_entry_skip():
    pos, idx = buy_position([(100, 101, 97, 98)] * 2)
    bt = bt_()
    drive(bt, pos, idx, [(25000, 25002, 24985, 24988)] * 2)
    assert bt.trades[0].reason == "invalidation close"
    pos, idx = buy_position([(100, 102, 98, 101)] * 4)
    bt = bt_()
    drive(bt, pos, idx, [(25000, 25005, 24996, 25003)] * 4)             # +3 points after 3 candles < 0.5 x S
    assert bt.trades[0].reason == "time stop" and bt.trades[0].exit_time == idx[2].to_pydatetime()
    pos, idx = buy_position([(100, 104, 99, 103)] * 80)
    bt = bt_()
    drive(bt, pos, idx, [(25000, 25010, 24999, 25008)] * 80)            # past +0.5R, never reaches T1
    assert bt.trades[0].reason == "flat-by time" and bt.trades[0].exit_time.time() == time(14, 55)
    pos, idx = buy_position([(100, 101, 99, 100)])
    bt = bt_()
    assert bt._manage(pos, C(idx[0], 25004.5, 25006, 25003, 25005), None) is True
    assert not bt.trades and bt.skipped == {"index moved more than 3 points before entry": 1}


def spread_position(short, hedge, stop=("vwap", 1)):
    idx = pd.date_range("2026-11-13 11:35", periods=len(short), freq="5min")
    f = lambda xs: pd.DataFrame({"o": xs, "h": xs, "l": xs, "c": xs}, index=idx)
    sig = Signal("S2", "t", "BULL PUT SPREAD", "S2:1", [])
    sig.sim = {"kind": "sell", "spreads": [object()], "credit": 0, "stop": stop, "expiry_day": False}
    return Position(sig, Trade(date(2026, 11, 13), "S2", sig.side, datetime(2026, 11, 13, 11, 35)),
                    [f(short), f(hedge)], [-1, 1]), idx


def test_credit_spread_target_stop_and_index_stop():
    pos, idx = spread_position([60, 50, 36], [25, 22, 20])              # value 35 -> 28 -> 16
    bt = bt_()
    drive(bt, pos, idx, [(25050, 25052, 25048, 25050)] * 3)
    t = bt.trades[0]
    assert t.reason == "50% target" and t.entry == pytest.approx(34.0)  # 35 less slippage on two fills
    assert t.exit == pytest.approx(17.0) and t.points == pytest.approx(17.0)
    assert t.rupees == pytest.approx(17 * 65 - round_trip_cost([25.5, 36.5], [59.5, 19.5], 65))
    pos, idx = spread_position([60, 80], [25, 27])                      # value 53 >= 1.5 x 34
    bt = bt_()
    drive(bt, pos, idx, [(25050, 25052, 25048, 25050)] * 2)
    assert bt.trades[0].reason == "1.5x credit stop" and bt.trades[0].points < 0
    pos, idx = spread_position([60, 62], [25, 25])
    bt = bt_()
    drive(bt, pos, idx, [(25050, 25052, 25048, 25050), (25050, 25051, 24990, 24995)])   # close below VWAP 25000
    assert bt.trades[0].reason == "index stop"
    pos, idx = spread_position([30], [15])                              # only 14 of credit after slippage
    bt = bt_()
    assert bt._manage(pos, C(idx[0], 25050, 25052, 25048, 25050), None) is True
    assert not bt.trades and "credit below the minimum at entry" in bt.skipped


# ------------------------------------------------------------------ end to end
@pytest.fixture(scope="module")
def run():
    h = FakeHistory(DAYS, seed=4, vol=7.0)
    bt = Backtest(h, Rules(), Options())
    bt.run(DAYS[1], DAYS[-1])
    return h, bt


def test_run_respects_the_sheets_limits(run):
    h, bt = run
    assert bt.trades, "synthetic history should produce trades"
    by_day = {}
    for t in bt.trades:
        by_day.setdefault(t.day, []).append(t)
        assert t.entry_time > t.signal_time - timedelta(minutes=1)       # filled on the candle after the alert
        assert t.exit_time >= t.entry_time and t.exit_time.time() <= time(14, 55)
        assert t.reason and np.isfinite(t.rupees)
        assert t.rupees == pytest.approx(t.points * 65, abs=400)         # points and rupees agree, charges aside
    for day, ts in by_day.items():
        assert len(ts) <= 4
        for a, b in zip(ts, ts[1:]):
            assert b.signal_time >= a.exit_time                          # one position at a time
        streak = 0
        for t in ts:
            assert streak < 3                                            # no new trade after 3 straight losses
            streak = streak + 1 if t.rupees < 0 else 0
    assert bt.signals >= len(bt.trades)


def test_run_is_repeatable_and_reports(run, tmp_path):
    h, bt = run
    again = Backtest(FakeHistory(DAYS, seed=4, vol=7.0), Rules(), Options())
    again.run(DAYS[1], DAYS[-1])
    assert [(t.signal_time, t.setup, round(t.rupees, 2)) for t in again.trades] == \
           [(t.signal_time, t.setup, round(t.rupees, 2)) for t in bt.trades]
    df = summarise(bt.trades)
    all_row = df[df["setup"] == "ALL"].iloc[0]
    assert all_row["trades"] == len(bt.trades)
    assert all_row["net ₹ (1 lot)"] == pytest.approx(sum(t.rupees for t in bt.trades))
    text = report(bt, DAYS[1], DAYS[-1])
    assert "break-even win %" in text and "Read this before trusting the numbers" in text
    write_trades(bt.trades, tmp_path / "t.csv")
    assert len((tmp_path / "t.csv").read_text().splitlines()) == len(bt.trades) + 1


def test_chart_only_and_missing_option_data():
    h = FakeHistory(DAYS, seed=4, vol=7.0)
    bt = Backtest(h, Rules(), Options(use_options=False))
    bt.run(DAYS[1], DAYS[-1])
    assert h.requests == 0 and bt.trades and all(t.setup.startswith("B") for t in bt.trades)
    assert "CHART-ONLY" in report(bt, DAYS[1], DAYS[-1])
    none = FakeHistory(DAYS, seed=4, vol=7.0)
    none.option_day = lambda *a: None                                   # e.g. expired contracts unavailable
    bt2 = Backtest(none, Rules(), Options())
    bt2.run(DAYS[1], DAYS[-1])                                          # must not crash
    assert "No trades." in report(bt2, DAYS[1], DAYS[-1]) or bt2.skipped


# ------------------------------------------------------------ Groww history loader
class FakeApi:
    def __init__(self):
        self.candle_calls, self.fut = [], random_days(pd.bdate_range("2026-09-20", "2026-10-30").date.tolist(), seed=1)

    def get_expiries(self, exch, und, year, month, timeout=None):
        days = pd.date_range(date(year, month, 1), periods=31)
        return {"expiries": [d.date().isoformat() for d in days if d.month == month and d.weekday() == 1]}

    def get_contracts(self, exch, und, expiry, timeout=None):
        return {"contracts": [f"NSE-NIFTY-XX-25000-CE"]}

    def get_historical_candles(self, exch, seg, sym, start, end, interval, timeout=None):
        self.candle_calls.append((sym, start[:10], end[:10]))
        if sym.endswith("-25100-PE"):
            raise RuntimeError("contract not found")
        df = self.fut[(self.fut.index >= start) & (self.fut.index <= end)]
        return {"candles": [[ts.strftime("%Y-%m-%dT%H:%M:%S"), r.o, r.h, r.l, r.c, r.v] for ts, r in df.iterrows()]}


class FakeG:
    vix = None

    def __init__(self):
        self.api = FakeApi()


def test_groww_history_stitches_caches_and_survives_missing_contracts(tmp_path, monkeypatch):
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda *_: None)
    g = FakeG()
    h = GrowwHistory(g, date(2026, 10, 5), date(2026, 10, 23), tmp_path, vix_symbol="NSE-INDIAVIX")
    syms = {c[0] for c in g.api.candle_calls}
    assert {"NSE-NIFTY", "NSE-INDIAVIX", "NSE-NIFTY-29Sep26-FUT", "NSE-NIFTY-27Oct26-FUT"} <= syms
    assert h.fut.index.is_monotonic_increasing and not h.fut.index.duplicated().any()
    assert h.fut.index[0].date() <= date(2026, 9, 28) and h.fut.index[-1].date() == date(2026, 10, 23)
    n = len(g.api.candle_calls)
    h2 = GrowwHistory(g, date(2026, 10, 5), date(2026, 10, 23), tmp_path, vix_symbol="NSE-INDIAVIX")
    assert len(g.api.candle_calls) == n                                  # second run is served from disk
    pd.testing.assert_frame_equal(h.fut, h2.fut, check_freq=False)
    # the contract list has a different date spelling: matched by strike and type instead
    assert h2.option_day(date(2026, 10, 13), 25000, "CE", date(2026, 10, 12)) is not None
    assert g.api.candle_calls[-1][0] == "NSE-NIFTY-XX-25000-CE"
    assert h2.option_day(date(2026, 10, 13), 25100, "PE", date(2026, 10, 12)) is None and h2.failed == 1


# rate limits -----------------------------------------------------------------
class Limited(Exception):
    def __init__(self):
        super().__init__("Rate limit has breached for your request. Please try again later.")
        self.msg, self.code = str(self), "GA005"


class FlakyApi(FakeApi):
    """Refuses the first `n` requests of every kind with Groww's rate-limit error."""

    def __init__(self, n):
        super().__init__()
        self.left, self.refused = n, 0

    def _gate(self):
        if self.left > 0:
            self.left -= 1
            self.refused += 1
            raise Limited()

    def get_expiries(self, *a, **k):
        self._gate()
        return super().get_expiries(*a, **k)

    def get_historical_candles(self, *a, **k):
        self._gate()
        return super().get_historical_candles(*a, **k)


def test_rate_limit_is_waited_out(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr("scalpbot.backtest._time.sleep", slept.append)
    g = FakeG()
    g.api = FlakyApi(3)                                # the very first requests are refused, as happened live
    h = GrowwHistory(g, date(2026, 10, 5), date(2026, 10, 23), tmp_path, vix_symbol="NSE-INDIAVIX")
    assert g.api.refused == 3 and h.waits == 3 and not h.fut.empty and h.failed == 0
    assert [s for s in slept if s >= 5] == [5, 15, 30]              # growing waits, then it carries on


def test_persistent_rate_limit_stops_cleanly_and_resumes(tmp_path, monkeypatch):
    from scalpbot.backtest import RateLimited
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda *_: None)
    g = FakeG()
    g.api = FlakyApi(0)
    orig = g.api.get_historical_candles
    n = {"c": 0}

    def candles(*a, **k):                              # works for a while, then Groww refuses everything
        n["c"] += 1
        if n["c"] > 4:
            raise Limited()
        return orig(*a, **k)

    g.api.get_historical_candles = candles
    with pytest.raises(RateLimited, match="resumes where it stopped"):
        GrowwHistory(g, date(2026, 10, 5), date(2026, 10, 23), tmp_path, vix_symbol="NSE-INDIAVIX")
    cached = len(list(tmp_path.glob("*.csv")))
    assert cached == 4                                 # nothing downloaded was lost, nothing empty was cached
    g.api.get_historical_candles = orig
    before = len(g.api.candle_calls)
    h = GrowwHistory(g, date(2026, 10, 5), date(2026, 10, 23), tmp_path, vix_symbol="NSE-INDIAVIX")
    assert not h.fut.empty and len(list(tmp_path.glob("*.csv"))) > cached
    first = GrowwHistory(FakeG(), date(2026, 10, 5), date(2026, 10, 23), tmp_path / "fresh", vix_symbol="NSE-INDIAVIX")
    assert len(g.api.candle_calls) - before < first.calls         # the rerun skipped what was already cached


def test_requests_are_spaced_and_other_errors_are_not_retried_as_rate_limits(tmp_path, monkeypatch):
    from scalpbot.backtest import is_rate_limit
    assert is_rate_limit(Limited()) and not is_rate_limit(RuntimeError("contract not found"))
    clock = {"t": 0.0}
    slept = []
    monkeypatch.setattr("scalpbot.backtest._time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    h = GrowwHistory(FakeG(), date(2026, 10, 5), date(2026, 10, 9), tmp_path, pause=0.4, vix_symbol="NSE-INDIAVIX")
    assert h.calls > 3 and len(slept) >= h.calls - 1 and all(abs(s - 0.4) < 1e-9 for s in slept)
