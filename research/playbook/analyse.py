import sys; sys.path.insert(0, ".")
import numpy as np, pandas as pd
from datetime import time
from research.playbook.data import load, sess
pd.set_option("display.width", 220, "display.max_columns", 30)
D = pd.read_csv("research/playbook/out_days.csv", parse_dates=["day"])
T = pd.read_csv("research/playbook/out_trades.csv", parse_dates=["day"])
print("days", len(D), "trend days", int(D.trend_day.sum()), f"({D.trend_day.mean():.0%})")
print("median EM", round(D.em.median()), "median OR30", round(D.or30.median()), "median day range", round(D.range.median()),
      "median VIX", round(D.vix.median(), 1))
def tab(col, bins, labels):
    x = D.assign(b=pd.cut(D[col], bins, labels=labels))
    g = x.groupby("b", observed=True).agg(days=("day", "size"), trend_pct=("trend_day", "mean"),
                                           med_range=("range", "median"), med_em=("em", "median"))
    g["trend_pct"] = (100 * g.trend_pct).round(0); print(f"\n-- trend-day share by {col}"); print(g)
tab("or30_em", [0, .25, .35, .5, 5], ["<0.25", "0.25-0.35", "0.35-0.5", ">0.5"])
tab("gap_pct", [-9, -0.5, -0.2, 0.2, 0.5, 9], ["<-0.5%", "-0.5..-0.2", "-0.2..0.2", "0.2..0.5", ">0.5%"])
tab("vix", [0, 12, 15, 18, 40], ["<12", "12-15", "15-18", ">18"])
tab("adx1015", [0, 20, 25, 30, 100], ["<20", "20-25", "25-30", ">30"])
print("\n-- day of week (NIFTY expiry Tue; dte = weekdays to expiry)")
print(D.groupby("dow").agg(days=("day", "size"), med_range=("range", "median"), trend_pct=("trend_day", "mean")).round(2))
print(D.groupby("dte").agg(days=("day", "size"), med_range=("range", "median"), trend_pct=("trend_day", "mean")).round(2))
# time-of-day: median 5-min spot range by half hour
fut, spot, vix, ex, _ = load()
S = sess(spot); S = S[(S.index >= "2025-11-01") & (S.index < "2026-11-01")]
r = (S.h - S.l).to_frame("rng"); r["hh"] = [f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}" for t in r.index.time]
print("\n-- median 5-min spot range (index points) by half hour"); print(r.groupby("hh").rng.median().round(1).to_string())
# by window and by setup
T["half"] = np.where(T.day < "2026-05-01", "H1 Nov-Apr", "H2 May-Oct")
t = T[(T.missing != True) & T.rupees.notna()]
print("\n-- per half-year, rupees per trade")
print(t.groupby(["slip", "setup", "half"]).rupees.agg(["size", "mean", "sum"]).round(0))
# index-point information in the signals
for s_ in ("ORB30", "VWAPF"):
    x = t[(t.setup == s_) & (t.slip == 0.1)]
    v = x.idx_move * x.dir
    print(f"\n{s_}: index move entry->exit in signal direction: mean {v.mean():.1f} pts, median {v.median():.1f}, n {len(v)}")
# iron fly: credit, max loss, regime split
x = t[(t.setup == "IFLY") & (t.slip == 0.1)].merge(D[["day", "or60", "em", "vix", "vix_chg", "gap_pct"]], on="day")
print("\nIFLY credit pts: median", x.entry.median(), "min", x.entry.min(), "max", x.entry.max(),
      "| max loss pts median", round((150 - x.entry).median(), 1))
x["or60_em"] = x.or60 / x.em
x["b"] = pd.cut(x.or60_em, [0, .35, .5, .7, 5])
print(x.groupby("b", observed=True).rupees.agg(["size", "mean", "sum"]).round(0))
x["g"] = pd.cut(x.gap_pct.abs(), [0, .2, .5, 9])
print(x.groupby("g", observed=True).rupees.agg(["size", "mean", "sum"]).round(0))
