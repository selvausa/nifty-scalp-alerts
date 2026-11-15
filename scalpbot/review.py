"""Review harness: funnel analysis and one-at-a-time sensitivity sweeps over a backtest window.

Experiment-only code. It never changes the live rules: every experiment is an override
applied in memory for one run (a Rules value, a simulator option, or a check that is
waived), read from a JSON spec so each result can be reproduced.

    python -m scalpbot.review 2026-05-01 2026-10-31            # baseline diagnostics + all sweeps
    python -m scalpbot.review 2026-05-01 2026-10-31 --only baseline
    python -m scalpbot.review 2026-05-01 2026-10-31 --offline  # data/cache only, no Groww login
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import setups as setups_mod
from .backtest import Backtest, GrowwHistory, Options, Trade, summarise, write_trades
from .config import Rules, Settings, ist_now, load_events
from .indicators import add_indicators
from .market import session_only
from .setups import Engine, Signal

log = logging.getLogger("scalpbot.review")
SETUPS = ("B1", "B2", "B3", "S1", "S2", "S3")
# Checks that run only after every chart check has passed (they cost option-data calls).
# A candle that fails one of these therefore passed the whole chart side.
OPTION_STAGE = ("Strike delta", "Strike with delta", "Spread at most", "Option 5-min close", "Credit at least",
                "Short strike in the delta range", "Each leg's bid-ask", "Short strike at least 2 x ATR",
                "Strikes, credit")


@dataclass
class Experiment:
    name: str
    group: str = "baseline"          # fidelity / entry-filter / exit-risk / drop-setup / diagnostic
    change: str = ""                 # plain description: "s_max 20 -> 30"
    rules: dict = field(default_factory=dict)      # Rules fields to override
    options: dict = field(default_factory=dict)    # backtest Options fields to override
    waive: list = field(default_factory=list)      # "SETUP:check name prefix" or "*:prefix" treated as passed
    setups: Optional[list] = None                  # run only these setups
    sell_delta: dict = field(default_factory=dict)  # {"S2": [0.20, 0.35]} short-strike delta range override


class TunedEngine(Engine):
    """The live Engine with per-run overrides. Waived checks count as passed; the live code is untouched."""

    def __init__(self, rules, sizing, exp: Experiment):
        super().__init__(rules, sizing)
        self.exp = exp
        self._cur = ""

    def _waived(self, name: str) -> bool:
        for w in self.exp.waive:
            who, _, prefix = w.partition(":")
            if who in ("*", self._cur) and name.startswith(prefix):
                return True
        return False

    def _ok(self, checks) -> bool:
        return all(c.ok is not False or self._waived(c.name) for c in checks)

    def evaluate(self, ctx, opt) -> list[Signal]:
        self.rejects, self._chain, self._chain_err = [], None, None
        out: list[Signal] = []
        orig_passed, orig_delta = setups_mod._passed, setups_mod.sell_delta_range
        setups_mod._passed = self._ok
        if self.exp.sell_delta:
            setups_mod.sell_delta_range = lambda s, dte: tuple(self.exp.sell_delta.get(s) or orig_delta(s, dte))
        try:
            for name, fn in (("B1", self._b1), ("B2", self._b2), ("B3", self._b3),
                             ("S1", self._s1), ("S2", self._s2), ("S3", self._s3)):
                if self.exp.setups and name not in self.exp.setups:
                    continue
                self._cur = name
                for sig in fn(ctx, opt):
                    bad = [c.name for c in sig.checks if c.ok is False and not self._waived(c.name)]
                    if bad:
                        self.rejects.append(f"{sig.setup} {sig.side}: " + "; ".join(bad))
                    else:
                        out.append(sig)
        finally:
            setups_mod._passed, setups_mod.sell_delta_range = orig_passed, orig_delta
        return out


# ------------------------------------------------------------------------ funnel
def _stage(check: str) -> str:
    return "option" if check.startswith(OPTION_STAGE) else "chart"


def funnel(candle_log: list[dict], trades: list[Trade], signals_by_setup: dict[str, int]):
    """Per setup: pattern candles, distinct episodes, candles passing every check, alerts, trades.
    Per check: raw blocks (overlapping), sole-blocker candles (the only failing check) and episodes."""
    df = pd.DataFrame(candle_log)
    summary, checks = [], []
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    df["t"] = pd.to_datetime(df["day"].astype(str) + " " + df["time"])
    df["fails"] = df["failed"].apply(lambda s: [x for x in s.split("; ") if x])
    df["n_fail"] = df["fails"].apply(len)

    def episodes(g: pd.DataFrame) -> int:
        """Runs of consecutive 5-minute candles, per day and side, count once."""
        n = 0
        for _, h in g.sort_values("t").groupby(["day", "side"]):
            gaps = h["t"].diff().dt.total_seconds().fillna(1e9)
            n += int((gaps > 300).sum())
        return n

    for setup in SETUPS:
        g = df[df["setup"] == setup]
        tr = [t for t in trades if t.setup == setup]
        if g.empty:
            summary.append({"setup": setup, "pattern_candles": 0, "episodes": 0, "near_miss_candles": 0,
                            "passed_all_checks": 0, "alerts": 0, "trades": len(tr)})
            continue
        passed = g[g["n_fail"] == 0]
        summary.append({
            "setup": setup, "pattern_candles": len(g), "episodes": episodes(g), "pattern_days": g["day"].nunique(),
            "near_miss_candles": int((g["n_fail"] == 1).sum()), "near_miss_episodes": episodes(g[g["n_fail"] == 1]),
            "passed_all_checks": len(passed), "passed_episodes": episodes(passed) if len(passed) else 0,
            "alerts": signals_by_setup.get(setup, 0), "trades": len(tr),
            "atr_median": round(float(g["atr"].median()), 1),
            "atr_over_20_pct": round(100 * float((g["atr"] > 20).mean()), 0),
            "avg_failed_checks": round(float(g.loc[g["n_fail"] > 0, "n_fail"].mean()), 2) if (g["n_fail"] > 0).any() else 0,
        })
        names = sorted({c for fs in g["fails"] for c in fs})
        for c in names:
            hit = g[g["fails"].apply(lambda fs: c in fs)]
            sole = hit[hit["n_fail"] == 1]
            checks.append({"setup": setup, "check": c, "stage": _stage(c), "raw_blocks": len(hit),
                           "raw_pct_of_pattern": round(100 * len(hit) / len(g), 0),
                           "sole_blocker_candles": len(sole), "sole_blocker_episodes": episodes(sole) if len(sole) else 0,
                           "sole_blocker_days": sole["day"].nunique()})
    cdf = pd.DataFrame(checks)
    if not cdf.empty:
        cdf = cdf.sort_values(["setup", "sole_blocker_candles", "raw_blocks"], ascending=[True, False, False])
    return pd.DataFrame(summary), cdf


def cost_breakdown(trades: list[Trade], lot: int) -> pd.DataFrame:
    rows = []
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.setup, []).append(t)
    for name, ts in sorted(groups.items()) + ([("ALL", trades)] if trades else []):
        slip = sum(t.slippage_pts for t in ts) * lot
        charges = sum(t.charges for t in ts)
        net = sum(t.rupees for t in ts)
        wins = [t.rupees for t in ts if t.rupees > 0]
        rows.append({"setup": name, "trades": len(ts), "gross_rupees_before_costs": round(net + slip + charges),
                     "slippage_rupees": round(slip), "charges_rupees": round(charges), "net_rupees": round(net),
                     "cost_per_trade": round((slip + charges) / len(ts)),
                     "avg_win_rupees": round(float(np.mean(wins))) if wins else 0,
                     "cost_as_pct_of_avg_win": round(100 * (slip + charges) / len(ts) / np.mean(wins)) if wins else None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------- sweeps
def default_experiments() -> list[Experiment]:
    E = Experiment
    x: list[Experiment] = [E("baseline", "baseline", "the cheat sheet's rules as coded")]
    # (a) fidelity: how much of the result is the simulation?
    x += [
        E("fid_target_first", "fidelity", "same-candle stop and target: target first (optimistic bound)",
          options={"same_candle": "target_first"}),
        E("fid_stop_gap_fill", "fidelity", "a stop the candle opened through fills at the open, not the stop price",
          options={"stop_fill": "open_if_worse"}),
        E("fid_slip_0", "fidelity", "slippage 0.5 -> 0 per fill", options={"slippage": 0.0}),
        E("fid_slip_0.25", "fidelity", "slippage 0.5 -> 0.25 per fill", options={"slippage": 0.25}),
        E("fid_slip_1.0", "fidelity", "slippage 0.5 -> 1.0 per fill", options={"slippage": 1.0}),
        E("fid_no_entry_credit_gate", "fidelity", "credit minimum checked at the alert only, not again at the fill",
          options={"entry_credit_min": 0.0}),
        E("fid_entry_gap_off", "fidelity", "do not skip buys when the index moved over 3 points before the fill",
          options={"entry_max_gap": 1e9}),
    ]
    # (c) exits and risk
    x += [
        E("exit_at_t1", "exit-risk", "buys: book everything at T1 instead of stop to entry+2 and trail",
          options={"exit_at_t1": True}),
        E("exit_no_lock", "exit-risk", "buys: after T1 keep the original stop, trail under the 9 EMA",
          options={"lock_after_t1": None}),
        E("exit_lock_be", "exit-risk", "buys: after T1 stop to entry + 0 (break-even before costs)",
          options={"lock_after_t1": 0.0}),
        E("exit_lock_half_t1", "exit-risk", "buys: after T1 stop to entry + 6", options={"lock_after_t1": 6.0}),
        E("exit_no_time_stop", "exit-risk", "buys: time stop off", options={"time_stop_bars": 0}),
        E("exit_time_stop_6", "exit-risk", "buys: time stop after 6 candles instead of 3", options={"time_stop_bars": 6}),
        E("exit_stop_1.0", "exit-risk", "buys: disaster stop 1.5 -> 1.0 x S x delta", options={"stop_mult": 1.0}),
        E("exit_stop_2.0", "exit-risk", "buys: disaster stop 1.5 -> 2.0 x S x delta", options={"stop_mult": 2.0}),
        E("exit_no_index_stop", "exit-risk", "spreads: no index stop (credit stop, target and flat-by only)",
          options={"index_stop": False}),
        E("exit_credit_target_0.3", "exit-risk", "spreads: target 50% -> 30% of credit", options={"credit_target": 0.3}),
        E("exit_credit_target_0.7", "exit-risk", "spreads: target 50% -> 70% of credit", options={"credit_target": 0.7}),
        E("exit_credit_stop_2.0", "exit-risk", "spreads: stop 1.5x -> 2.0x credit", options={"credit_stop": 2.0}),
    ]
    # (b) entry filters, one at a time
    for v in (25, 30, 40):
        x.append(E(f"entry_s_max_{v}", "entry-filter", f"stop size cap s_max 20 -> {v}", rules={"s_max": float(v)}))
    x.append(E("entry_s_min_5", "entry-filter", "stop size floor s_min 10 -> 5", rules={"s_min": 5.0}))
    for v in (18, 15, 12):
        x.append(E(f"entry_min_credit_{v}", "entry-filter", f"minimum credit 22 -> {v} (alert and fill)",
                   rules={"min_credit": float(v), "min_credit_condor": float(2 * v)}))
    x += [
        E("entry_s2_delta_0.20_0.35", "entry-filter", "S2 short-strike delta 0.15-0.30 -> 0.20-0.35",
          sell_delta={"S2": [0.20, 0.35]}),
        E("entry_s2_delta_0.25_0.40", "entry-filter", "S2 short-strike delta 0.15-0.30 -> 0.25-0.40",
          sell_delta={"S2": [0.25, 0.40]}),
        E("entry_adx_15", "entry-filter", "ADX trend threshold 20 -> 15", rules={"adx_trend": 15.0}),
        E("entry_adx_25", "entry-filter", "ADX trend threshold 20 -> 25", rules={"adx_trend": 25.0}),
        E("entry_vix_up_8", "entry-filter", "no selling when VIX is up more than 5% -> 8%", rules={"vix_up_block_pct": 8.0}),
        E("entry_or_width_0.6", "entry-filter", "B2 opening range at most 0.4 -> 0.6 x expected move",
          rules={"or_width_em_max": 0.6}),
        E("entry_b3_vol_1.2", "entry-filter", "B3 break volume 1.5 -> 1.2 x the prior-10 average",
          rules={"b3_vol_mult": 1.2}),
        E("entry_s1_or_atr_2", "entry-filter", "S1 opening range at least 4 -> 2 x ATR", rules={"or_width_atr_min": 2.0}),
        E("entry_cooldown_15", "entry-filter", "alert cooldown 30 -> 15 minutes", rules={"cooldown_min": 15}),
    ]
    waivers = [
        ("B1", "Volume at least the prior candle's"), ("B1", "No PDH/PDL or 100-strike inside T1"),
        ("B1", "ADX(14) is 20 or more"), ("B1", "Day range under 100%"),
        ("B2", "Break volume at least the opening-range average"), ("B2", "No PDH/PDL or 100-strike inside T1"),
        ("B2", "Range width at most 0.4"), ("B2", "Option 5-min close above"),
        ("B3", "Break volume at least 1.5"), ("B3", "Close outside the band"), ("B3", "Option 5-min close above"),
        ("S1", "ADX(14) below 20"), ("S1", "Opening range at least 4"), ("S1", "No gap open"), ("S1", "No squeeze"),
        ("S2", "Day range under 100%"), ("S2", "India VIX not up"), ("S2", "Not expiry day after 12:00"),
        ("S2", "ADX(14) is 20 or more"), ("S2", "Short strike at least 2 x ATR"),
        ("S3", "India VIX not making higher"), ("S3", "India VIX not up"), ("S3", "Last 15-min candle"),
        ("S3", "Day extreme not exceeded"), ("S3", "Not closing beyond"),
    ]
    for setup, check in waivers:
        slug = "".join(ch if ch.isalnum() else "_" for ch in check.lower())[:28].strip("_")
        x.append(E(f"waive_{setup}_{slug}", "entry-filter", f"{setup}: drop the check '{check}'",
                   waive=[f"{setup}:{check}"]))
    # S1 and S3 never trade: what does it take?
    x += [
        E("diag_s1_chart_checks_off", "diagnostic", "S1: waive ADX, range width, gap and squeeze (chart side fully open)",
          waive=["S1:ADX(14) below 20", "S1:Opening range at least 4", "S1:No gap open", "S1:No squeeze"], setups=["S1"]),
        E("diag_s1_open_credit_30", "diagnostic", "S1: chart side open and condor credit 44 -> 30",
          waive=["S1:ADX(14) below 20", "S1:Opening range at least 4", "S1:No gap open", "S1:No squeeze"],
          rules={"min_credit_condor": 30.0}, setups=["S1"]),
        E("diag_s3_vix_checks_off", "diagnostic", "S3: waive both VIX checks", setups=["S3"],
          waive=["S3:India VIX not making higher", "S3:India VIX not up"]),
        E("diag_s3_chart_open_credit_12", "diagnostic", "S3: VIX checks off and credit 22 -> 12", setups=["S3"],
          waive=["S3:India VIX not making higher", "S3:India VIX not up"], rules={"min_credit": 12.0}),
    ]
    # (d) dropping setups
    x += [
        E("drop_only_buys", "drop-setup", "run B1, B2, B3 only", setups=["B1", "B2", "B3"]),
        E("drop_only_sells", "drop-setup", "run S1, S2, S3 only", setups=["S1", "S2", "S3"]),
        E("drop_only_B1", "drop-setup", "run B1 only", setups=["B1"]),
        E("drop_only_S2", "drop-setup", "run S2 only", setups=["S2"]),
        E("drop_no_S2", "drop-setup", "run everything except S2", setups=["B1", "B2", "B3", "S1", "S3"]),
    ]
    return x


def load_spec(path: Path) -> list[Experiment]:
    return [Experiment(**e) for e in json.loads(path.read_text())]


def save_spec(exps: list[Experiment], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([e.__dict__ for e in exps], indent=1))


def run_experiment(hist, exp: Experiment, start: date, end: date, events=None, frame=None) -> Backtest:
    rules = replace(Rules(), **exp.rules)
    bt = Backtest(hist, rules, Options(**exp.options), events or [],
                  engine_factory=lambda r, s: TunedEngine(r, s, exp), frame=frame)
    bt.run(start, end)
    return bt


def result_rows(exp: Experiment, bt: Backtest) -> list[dict]:
    """One row per setup that traded, plus ALL. Expectancy is rupees per trade after all costs."""
    alerts: dict[str, int] = {}
    for r in bt.candle_log:
        if r["outcome"] == "alert":
            alerts[r["setup"]] = alerts.get(r["setup"], 0) + 1
    base = {"experiment": exp.name, "group": exp.group, "change": exp.change}
    rows = []
    if not bt.trades:
        return [{**base, "setup": "ALL", "alerts": bt.signals, "trades": 0}]
    df = summarise(bt.trades)
    for _, r in df.iterrows():
        ts = bt.trades if r["setup"] == "ALL" else [t for t in bt.trades if t.setup == r["setup"]]
        reasons: dict[str, int] = {}
        for t in ts:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
        rows.append({**base, "setup": r["setup"],
                     "alerts": bt.signals if r["setup"] == "ALL" else alerts.get(r["setup"], 0),
                     "trades": int(r["trades"]), "win_pct": round(r["win %"], 1),
                     "avg_win": round(r["avg win ₹"]), "avg_loss": round(r["avg loss ₹"]),
                     "break_even_win_pct": None if pd.isna(r["break-even win %"]) else round(r["break-even win %"], 1),
                     "expectancy_per_trade": round(r["net ₹ (1 lot)"] / r["trades"]),
                     "net_rupees": round(r["net ₹ (1 lot)"]), "net_points": round(r["net points"], 1),
                     "max_drawdown": round(r["max drawdown ₹"]), "worst_trade": round(r["worst trade ₹"]),
                     "exits": "; ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])),
                     "not_traded": "; ".join(f"{k} {v}" for k, v in sorted(bt.skipped.items(), key=lambda kv: -kv[1]))
                     if r["setup"] == "ALL" else ""})
    return rows


# -- process pool plumbing: each worker loads the cached history once
_W: dict = {}


def _init(cache: str, start: str, end: str, vix: str, events_file: str):
    logging.basicConfig(level=logging.WARNING)
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    _W["hist"] = GrowwHistory(None, s, e, Path(cache), vix_symbol=vix, offline=True)
    _W["frame"] = add_indicators(session_only(_W["hist"].fut))
    _W["events"] = load_events(Path(events_file))
    _W["range"] = (s, e)


def _work(exp_dict: dict) -> list[dict]:
    exp = Experiment(**exp_dict)
    bt = run_experiment(_W["hist"], exp, *_W["range"], _W["events"], _W["frame"])
    rows = result_rows(exp, bt)
    for r in rows:
        r["missing_cache_files"] = _W["hist"].failed
    return rows


COLUMNS = ["experiment", "group", "change", "setup", "alerts", "trades", "win_pct", "break_even_win_pct",
           "avg_win", "avg_loss", "expectancy_per_trade", "net_rupees", "net_points", "max_drawdown", "worst_trade",
           "exits", "not_traded", "missing_cache_files"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scalpbot.review", description="Funnel analysis and sensitivity sweeps")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("--offline", action="store_true", help="use data/cache only for the baseline (sweeps always do)")
    p.add_argument("--spec", help="JSON experiment list (default: the built-in set, saved to experiments/)")
    p.add_argument("--only", help="comma-separated experiment names or groups to run")
    p.add_argument("--jobs", type=int, default=4, help="parallel sweep runs (default 4)")
    p.add_argument("--out", default="docs", help="output folder (default docs)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    tag = f"{start:%Y-%m}_{end:%Y-%m}"
    out, cache = Path(a.out), s.data_dir / "cache"
    out.mkdir(parents=True, exist_ok=True)
    spec = Path(a.spec) if a.spec else Path("experiments") / f"sweeps_{tag}.json"
    if a.spec or spec.exists():
        exps = load_spec(spec)
    else:
        exps = default_experiments()
        save_spec(exps, spec)
    if a.only:
        want = set(a.only.split(","))
        exps = [e for e in exps if e.name in want or e.group in want]
    print(f"{len(exps)} experiment(s); spec: {spec}")

    # ---- baseline diagnostics (run here, online unless --offline, so the cache gets completed)
    base = next((e for e in exps if e.name == "baseline"), None)
    if base is not None:
        g = None
        if not a.offline:
            from .groww import Groww
            g = Groww(s)
            g.connect(ist_now().date())
        hist = GrowwHistory(g, start, end, cache, vix_symbol=s.vix_groww_symbol, offline=a.offline)
        bt = run_experiment(hist, base, start, end, load_events(s.events_file))
        write_trades(bt.trades, out / f"backtest_trades_{tag}.csv")
        pd.DataFrame(bt.untraded).to_csv(out / f"backtest_untraded_{tag}.csv", index=False)
        by_setup: dict[str, int] = {}
        for r in bt.candle_log:
            if r["outcome"] == "alert":
                by_setup[r["setup"]] = by_setup.get(r["setup"], 0) + 1
        fs, fc = funnel(bt.candle_log, bt.trades, by_setup)
        fs.to_csv(out / f"backtest_funnel_setups_{tag}.csv", index=False)
        fc.to_csv(out / f"backtest_funnel_checks_{tag}.csv", index=False)
        pd.DataFrame(bt.candle_log).to_csv(out / f"backtest_candles_{tag}.csv", index=False)
        cb = cost_breakdown(bt.trades, Options().lot)
        cb.to_csv(out / f"backtest_costs_{tag}.csv", index=False)
        reasons: dict[str, int] = {}
        for t in bt.trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
        print(f"\nBASELINE: {bt.signals} alerts = {len(bt.trades)} trades + {sum(bt.skipped.values())} not traded "
              f"{dict(bt.skipped)}")
        print(f"exits ({sum(reasons.values())}): {reasons}")
        print(f"Groww requests {hist.calls}, missing cache files {hist.failed}\n")
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 70):
            print(fs.to_string(index=False), "\n")
            print(fc.to_string(index=False), "\n")
            print(cb.to_string(index=False), "\n")

    # ---- sweeps (offline, in parallel; results appended as they finish so a stopped run keeps its rows)
    sweep = [e for e in exps]
    path = out / f"backtest_sweeps_{tag}.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        with ProcessPoolExecutor(max_workers=max(1, a.jobs), initializer=_init,
                                 initargs=(str(cache), a.start, a.end, s.vix_groww_symbol, str(s.events_file))) as pool:
            for i, rows in enumerate(pool.map(_work, [e.__dict__ for e in sweep]), 1):
                for r in rows:
                    w.writerow(r)
                f.flush()
                allr = next((r for r in rows if r["setup"] == "ALL"), rows[0])
                print(f"[{i}/{len(sweep)}] {allr['experiment']}: {allr.get('trades', 0)} trades, "
                      f"net ₹{allr.get('net_rupees', 0):,}, expectancy ₹{allr.get('expectancy_per_trade', 0):,}/trade")
                if allr["experiment"] == "baseline" and base is not None and (
                        allr.get("trades", 0) != len(bt.trades) or allr.get("alerts") != bt.signals):
                    print("  WARNING: the offline baseline differs from the online one "
                          f"({allr.get('alerts')} alerts / {allr.get('trades', 0)} trades vs {bt.signals} / "
                          f"{len(bt.trades)}): the cache is incomplete, so sweep rows are not comparable.")
    print(f"\nWrote {path} and the baseline files in {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
