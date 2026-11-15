"""Review harness: overrides, funnel maths, offline cache and an end-to-end sweep on synthetic data."""
from datetime import date, datetime

import pandas as pd
import pytest

from scalpbot.backtest import Backtest, GrowwHistory, Options
from scalpbot.config import Rules
from scalpbot.review import (Experiment, cost_breakdown, default_experiments, funnel, load_spec, main, result_rows,
                             run_experiment, save_spec)
from tests.test_backtest import DAYS, FakeApi, FakeG, FakeHistory


@pytest.fixture(scope="module")
def hist():
    return FakeHistory(DAYS, seed=4, vol=7.0)


@pytest.fixture(scope="module")
def base(hist):
    return run_experiment(hist, Experiment("baseline"), DAYS[1], DAYS[-1])


def key(bt):
    return [(t.signal_time, t.setup, t.reason, round(t.rupees, 2)) for t in bt.trades]


def test_baseline_experiment_equals_plain_backtest(hist, base):
    plain = Backtest(hist, Rules(), Options())
    plain.run(DAYS[1], DAYS[-1])
    assert key(base) == key(plain) and base.signals == plain.signals and base.skipped == plain.skipped
    assert base.signals == len(base.trades) + sum(base.skipped.values())      # every alert is accounted for
    assert len(base.untraded) == sum(base.skipped.values())


def test_live_module_is_restored_after_a_tuned_run(hist):
    from scalpbot import setups as m
    passed, delta = m._passed, m.sell_delta_range
    run_experiment(hist, Experiment("x", waive=["*:Stop size S"], sell_delta={"S2": [0.2, 0.35]}), DAYS[1], DAYS[3])
    assert m._passed is passed and m.sell_delta_range is delta


def test_waiving_a_check_removes_it_and_only_it(hist, base):
    name = "Volume at least the prior candle's"
    assert any(name in r["failed"] for r in base.candle_log if r["setup"] == "B1")
    bt = run_experiment(hist, Experiment("w", waive=[f"B1:{name}"]), DAYS[1], DAYS[-1])
    assert not any(name in r["failed"] for r in bt.candle_log if r["setup"] == "B1")
    other = run_experiment(hist, Experiment("w2", waive=[f"S2:{name}"]), DAYS[1], DAYS[-1])
    assert key(other) == key(base)                                            # scoped to the named setup


def test_rules_options_and_setup_overrides_apply(hist, base):
    wide = run_experiment(hist, Experiment("s", rules={"s_max": 60.0, "s_min": 1.0}), DAYS[1], DAYS[-1])
    assert not any("Stop size S" in r["failed"] for r in wide.candle_log)
    only = run_experiment(hist, Experiment("o", setups=["B1"]), DAYS[1], DAYS[-1])
    assert {r["setup"] for r in only.candle_log} <= {"B1"} and {t.setup for t in only.trades} <= {"B1"}
    t1 = run_experiment(hist, Experiment("t", options={"exit_at_t1": True}), DAYS[1], DAYS[-1])
    assert not any(t.reason in ("9 EMA trail", "stop after T1 (entry+2)") for t in t1.trades)
    free = run_experiment(hist, Experiment("z", options={"slippage": 0.0}), DAYS[1], DAYS[-1])
    assert all(t.slippage_pts == 0 for t in free.trades)


def test_trade_diagnostics_reconcile(base):
    assert base.trades
    for t in base.trades:
        assert t.fills in (2, 4, 8) and t.slippage_pts == pytest.approx(0.5 * t.fills)
        assert t.rupees == pytest.approx(t.points * 65 - t.charges)
        assert t.mae <= 0 <= t.mfe and t.bars >= 1 and t.dte >= 0
    cb = cost_breakdown(base.trades, 65)
    row = cb[cb["setup"] == "ALL"].iloc[0]
    assert row["gross_rupees_before_costs"] - row["slippage_rupees"] - row["charges_rupees"] == pytest.approx(
        row["net_rupees"], abs=3)
    assert row["net_rupees"] == pytest.approx(sum(t.rupees for t in base.trades), abs=1)


def test_funnel_counts_are_consistent(base):
    by = {}
    for r in base.candle_log:
        if r["outcome"] == "alert":
            by[r["setup"]] = by.get(r["setup"], 0) + 1
    fs, fc = funnel(base.candle_log, base.trades, by)
    assert sum(by.values()) == base.signals
    for _, s in fs.iterrows():
        if not s["pattern_candles"]:
            continue
        assert s["episodes"] <= s["pattern_candles"] and s["alerts"] <= s["passed_all_checks"] <= s["pattern_candles"]
        assert s["trades"] <= s["alerts"]
        c = fc[fc["setup"] == s["setup"]]
        assert c["sole_blocker_candles"].sum() == s["near_miss_candles"]     # each near miss has exactly one blocker
        assert (c["sole_blocker_candles"] <= c["raw_blocks"]).all()
        assert (c["sole_blocker_episodes"] <= c["sole_blocker_candles"]).all()
        assert c["raw_blocks"].max() <= s["pattern_candles"]


def test_funnel_on_a_known_log():
    def row(t, failed, setup="B2", side="BUY CE", day=date(2026, 6, 1)):
        return {"day": day, "time": t, "dte": 3, "atr": 25.0, "adx": 20.0, "setup": setup, "side": side,
                "failed": failed, "outcome": "blocked" if failed else "alert"}
    log = [row("10:00", "A; B"), row("10:05", "A"), row("10:10", "A"),          # one episode of three candles
           row("11:00", "B"), row("11:05", ""),                                  # a second episode, then a pass
           row("10:00", "A", day=date(2026, 6, 2))]                              # next day: third episode
    fs, fc = funnel(log, [], {"B2": 1})
    s = fs[fs["setup"] == "B2"].iloc[0]
    assert (s["pattern_candles"], s["episodes"], s["near_miss_candles"], s["passed_all_checks"]) == (6, 3, 4, 1)
    a = fc[fc["check"] == "A"].iloc[0]
    assert (a["raw_blocks"], a["sole_blocker_candles"], a["sole_blocker_episodes"]) == (4, 3, 2)
    b = fc[fc["check"] == "B"].iloc[0]
    assert (b["raw_blocks"], b["sole_blocker_candles"]) == (2, 1)
    assert s["atr_over_20_pct"] == 100


def test_result_rows_and_spec_roundtrip(base, tmp_path):
    rows = result_rows(Experiment("baseline"), base)
    allr = next(r for r in rows if r["setup"] == "ALL")
    assert allr["trades"] == len(base.trades) and allr["alerts"] == base.signals
    assert allr["expectancy_per_trade"] == round(sum(t.rupees for t in base.trades) / len(base.trades))
    exps = default_experiments()
    assert len({e.name for e in exps}) == len(exps) and exps[0].name == "baseline"
    assert all(e.change for e in exps) and {e.group for e in exps} >= {"fidelity", "entry-filter", "exit-risk", "drop-setup"}
    valid_rules, valid_opts = set(Rules.__dataclass_fields__), set(Options.__dataclass_fields__)
    for e in exps:
        assert set(e.rules) <= valid_rules and set(e.options) <= valid_opts, e.name
    save_spec(exps, tmp_path / "s.json")
    assert [e.__dict__ for e in load_spec(tmp_path / "s.json")] == [e.__dict__ for e in exps]


def test_optimistic_same_candle_rule_never_does_worse_on_a_shared_candle():
    from tests.test_backtest import bt_, buy_position, drive
    prices = [(100, 101, 99, 100), (100, 115, 88, 110), (110, 112, 109, 111), (111, 111, 100, 101)]
    fut = [(25000, 25004, 24996, 25001), (25001, 25030, 24995, 25020), (25020, 25024, 25016, 25022),
           (25022, 25023, 25000, 25002)]
    res = {}
    for mode in ("stop_first", "target_first"):
        pos, idx = buy_position(prices)
        bt = bt_(same_candle=mode, exit_at_t1=True)
        drive(bt, pos, idx, fut)
        res[mode] = bt.trades[0]
    assert res["stop_first"].reason == "disaster stop" and res["target_first"].reason == "T1"
    assert res["target_first"].points > 0 > res["stop_first"].points


def test_offline_history_matches_online_and_makes_no_requests(tmp_path, monkeypatch):
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda *_: None)
    g = FakeG()
    a, b = date(2026, 10, 5), date(2026, 10, 23)
    on = GrowwHistory(g, a, b, tmp_path, vix_symbol="NSE-INDIAVIX")
    opt = on.option_day(date(2026, 10, 13), 25000, "CE", date(2026, 10, 12))
    n = len(g.api.candle_calls)
    off = GrowwHistory(None, a, b, tmp_path, offline=True)                   # no Groww object at all
    pd.testing.assert_frame_equal(on.fut, off.fut, check_freq=False)
    pd.testing.assert_frame_equal(on.vix, off.vix, check_freq=False)
    assert on.expiries == off.expiries and off.calls == 0 and len(g.api.candle_calls) == n
    pd.testing.assert_frame_equal(opt, off.option_day(date(2026, 10, 13), 25000, "CE", date(2026, 10, 12)),
                                  check_freq=False)
    assert off.option_day(date(2026, 10, 13), 24000, "PE", date(2026, 10, 12)) is None and off.failed == 1


def test_main_runs_end_to_end_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda *_: None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("VIX_GROWW_SYMBOL", "NSE-INDIAVIX")
    monkeypatch.chdir(tmp_path)
    GrowwHistory(FakeG(), date(2026, 10, 5), date(2026, 10, 23), tmp_path / "data" / "cache",
                 vix_symbol="NSE-INDIAVIX")                                   # fill the cache
    rc = main(["2026-10-05", "2026-10-23", "--offline", "--only", "baseline,fid_slip_0,drop_only_B1", "--jobs", "2",
               "--out", str(tmp_path / "docs")])
    assert rc == 0
    sweeps = pd.read_csv(tmp_path / "docs" / "backtest_sweeps_2026-10_2026-10.csv")
    assert set(sweeps["experiment"]) == {"baseline", "fid_slip_0", "drop_only_B1"}
    for f in ("trades", "untraded", "funnel_setups", "funnel_checks", "candles", "costs"):
        assert (tmp_path / "docs" / f"backtest_{f}_2026-10_2026-10.csv").exists()
    assert (tmp_path / "experiments" / "sweeps_2026-10_2026-10.json").exists()
    assert "WARNING: the offline baseline differs" not in capsys.readouterr().out


def test_stop_gap_fill_uses_the_open_when_the_candle_opened_through_the_stop():
    from tests.test_backtest import bt_, buy_position, drive
    prices = [(100, 101, 99, 100), (85, 86, 80, 82)]                 # second candle opens below the 91.5 stop
    fut = [(25000, 25004, 24996, 25001), (24975, 24978, 24960, 24965)]
    out = {}
    for mode in ("stop", "open_if_worse"):
        pos, idx = buy_position(prices)
        bt = bt_(stop_fill=mode)
        drive(bt, pos, idx, fut)
        out[mode] = bt.trades[0].exit
    assert out["stop"] == pytest.approx(91.5 - 0.5) and out["open_if_worse"] == pytest.approx(85 - 0.5)


def test_brokerage_is_spread_over_lots():
    from scalpbot.backtest import charges, round_trip_cost
    one = charges([(120.0, 1.0)], [(120.0, 1.0)], 65)
    assert one == pytest.approx(round_trip_cost([120.0], [120.0], 65)) == pytest.approx(65.69, abs=0.02)
    eight = charges([(120.0, 1.0)], [(120.0, 1.0)], 65 * 8) / 8
    fixed = 40 * 1.18                                              # two orders of brokerage plus GST on it
    assert eight == pytest.approx((one - fixed) + fixed / 8)       # only the flat part is diluted
    assert 20 < eight < 26


def test_lots_change_charges_only(hist, base):
    big = run_experiment(hist, Experiment("l", options={"lots": 8}), DAYS[1], DAYS[-1])
    assert [(t.signal_time, t.reason, round(t.points, 4)) for t in big.trades] == \
           [(t.signal_time, t.reason, round(t.points, 4)) for t in base.trades]
    assert all(b.charges < a.charges and b.rupees > a.rupees for a, b in zip(base.trades, big.trades))


def test_book_half_at_t1():
    from scalpbot.backtest import charges
    from tests.test_backtest import C, bt_, buy_position
    prices = [(100, 103, 99, 102), (102, 114, 101, 113), (113, 116, 110, 111), (111, 112, 108, 109)]
    fut = [(25000, 25006, 24998, 25005), (25005, 25026, 25003, 25024), (25024, 25030, 25018, 25020),
           (25020, 25021, 25010, 25012)]
    pos, idx = buy_position(prices)
    bt = bt_(lots=2, t1_book_fraction=0.5, lock_after_t1=None)
    for ts, bar in zip(idx, fut):
        if bt._manage(pos, C(ts, *bar, ema9=25015.0), None):
            break
    t = bt.trades[0]
    half_t1, rest = 100.5 + 24 * 0.5 - 0.5, 109 - 0.5              # T1 leg, then the 9 EMA trail exit
    assert t.reason == "9 EMA trail" and t.exit == pytest.approx((half_t1 + rest) / 2)
    assert t.points == pytest.approx((half_t1 + rest) / 2 - 100.5) and t.fills == 3
    assert t.slippage_pts == pytest.approx(0.5 * 2)                # one buy, two half sells
    assert t.charges == pytest.approx(charges([(100.5, 1.0)], [(half_t1, 0.5), (rest, 0.5)], 130) / 2)
    assert t.rupees == pytest.approx(t.points * 65 - t.charges)


def test_new_builtin_experiments_are_merged_into_an_old_spec(tmp_path, monkeypatch):
    monkeypatch.setattr("scalpbot.backtest._time.sleep", lambda *_: None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "none.txt"))
    monkeypatch.setenv("VIX_GROWW_SYMBOL", "NSE-INDIAVIX")
    monkeypatch.chdir(tmp_path)
    GrowwHistory(FakeG(), date(2026, 10, 5), date(2026, 10, 23), tmp_path / "data" / "cache", vix_symbol="NSE-INDIAVIX")
    old = [e for e in default_experiments() if not e.name.startswith(("lots_", "scn_"))]
    save_spec(old, tmp_path / "experiments" / "sweeps_2026-10_2026-10.json")
    assert main(["2026-10-05", "2026-10-23", "--offline", "--only", "lots_8", "--jobs", "1",
                 "--out", str(tmp_path / "docs")]) == 0
    names = [e.name for e in load_spec(tmp_path / "experiments" / "sweeps_2026-10_2026-10.json")]
    assert "lots_8" in names and names[: len(old)] == [e.name for e in old]
