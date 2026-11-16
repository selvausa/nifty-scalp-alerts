"""TREND10: in-sample test SUGGESTED BY the regime study (out_analysis.txt), so it is not independent evidence.
Day qualifies at 10:15 if any of: India VIX at open > 18, gap <= -0.5%, OR30 width > 0.5 x EM.
Signal: the 10:10 candle's close is outside the 09:15-09:45 range -> buy ATM in that direction at the 10:15 open.
Stop: 5-min close back beyond the OR midpoint. No target: exit at the 14:45 candle open. One trade per day."""
import sys; sys.path.insert(0, ".")
from datetime import time
import pandas as pd
import research.playbook.study as st

def trend10(slip):
    out = []
    for _, r in st.D.iterrows():
        if not (r.vix > 18 or r.gap_pct <= -0.5 or r.or30_em > 0.5):
            continue
        d = r.day; s = st.S[st.S.index.date == d]
        hi, lo = s.iloc[:6]["h"].max(), s.iloc[:6]["l"].min(); mid = (hi + lo) / 2
        ts0 = pd.Timestamp(f"{d} 10:10")
        if ts0 not in s.index:
            continue
        c = s.loc[ts0, "c"]; dr = 1 if c > hi else -1 if c < lo else 0
        if not dr:
            continue
        def rule(ts, n, s=s, dr=dr, mid=mid):
            if dr * (s.loc[ts, "c"] - mid) < 0:
                return "stop (OR mid)"
            if ts.time() >= time(14, 40):
                return "14:45 exit"
            return None
        t = st.buy_trade(d, ts0, dr, rule, slip)
        if t:
            t.update(setup="TREND10", dte=r.dte, dow=r.dow); out.append(t)
    return out

if __name__ == "__main__":
    rows = []
    for slip in (0.1, 0.5):
        tr = trend10(slip)
        x = st.summ(tr, "TREND10"); x["slip"] = slip; print(x)
        t = pd.DataFrame(tr); t["half"] = (t.day.astype(str) < "2026-05-01").map({True: "H1", False: "H2"})
        print(t.groupby("half").rupees.agg(["size", "mean", "sum"]).round(0).to_string())
        print("index move in signal direction, mean", round((t.idx_move * t.dir).mean(), 1), "median", round((t.idx_move * t.dir).median(), 1))
        rows.append(x); t.assign(slip=slip).to_csv(f"research/playbook/out_trend10_{slip}.csv", index=False)
    pd.DataFrame(rows).to_csv("research/playbook/out_trend10_summary.csv", index=False)
