"""Regime study and backtests for the scalping playbook (NIFTY only; SENSEX data is not cached).

Rules below were written before the first run and are not tuned afterwards. Every variant
that was run is reported. Fills: signal on a 5-minute close, entry AND close-triggered exits
at the NEXT candle's open; option legs priced from cached Groww option candles.
Costs: Rs 20 per order, STT 0.15% of sell premium, NSE txn 0.03553%, SEBI Rs 10/cr,
stamp 0.003% of buys, GST 18% (scalpbot/backtest.py charges()); slippage per fill reported at 0.1 and 0.5.

ORB30  (trend day, buy one ATM option)
  OR = NIFTY spot high/low 09:15-09:45. Skip if OR width > 0.5 x expected move (EM = spot x VIX/100/sqrt(252)).
  Signal: first 5-min close outside the OR between 09:45 and 11:30 (long CE above, PE below). One per day.
  Stop: 5-min close back beyond the OR midpoint. Target: breakout edge +/- 1.0 x OR width (index, touched by high/low,
  filled at the target's premium-equivalent: next open). Time stop: not +0.5 x OR width within 6 candles.
  Hard exit 14:45.
VWAPF  (range day, fade back to VWAP, buy one ATM option)
  10:15-14:00, futures ADX(14) < 20. A candle closes back inside VWAP +/- 2 SD after the previous candle
  closed outside it: buy towards VWAP. Target: VWAP at entry (touched). Stop: close beyond the excursion
  extreme. Time stop 6 candles. Max 2 per day, one at a time.
IFLY   (expiry day only, defined-risk short iron fly)
  NIFTY expiry day, entry at the 10:15 open: sell ATM CE + PE, buy CE/PE 150 points away.
  Exit at next open when spread value <= 0.5 x credit (target) or >= 1.5 x credit (stop), else 14:30 open.
  Filter variant IFLY-R: only when the 09:15-10:15 range <= 0.5 x EM and VIX is not up > 5% on the day.
"""
from __future__ import annotations
import json, math, sys
from datetime import date, time, timedelta
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from research.playbook.data import load, sess, option_day
from scalpbot.backtest import charges
from scalpbot.indicators import add_indicators

LOT = 65
fut, spot, vix, expiries, _ = load()
S = sess(spot)
F = add_indicators(sess(fut))
V = vix
days = sorted(d for d in set(S.index.date) if date(2025, 11, 1) <= d <= date(2026, 10, 31))
exp = lambda d: next(e for e in expiries if e >= d)

# ------------------------------------------------------------------ day features (role 3)
rows = []
prev_close = None
for d in days:
    s = S[S.index.date == d]
    if len(s) < 60:
        prev_close = float(s["c"].iloc[-1]) if len(s) else prev_close
        continue
    o = float(s["o"].iloc[0]); orr = s.iloc[:6]; or60 = s.iloc[:12]
    v = V[(V.index.date == d) & (V.index.time >= time(9, 15))]
    vp = V[V.index.date < d]
    vix0 = float(v["c"].iloc[0]) if len(v) else np.nan
    vchg = (float(v["c"].iloc[5]) / float(vp["c"].iloc[-1]) - 1) * 100 if len(v) > 5 and len(vp) else np.nan
    em = o * vix0 / 100 / math.sqrt(252)
    f = F[F.index.date == d]
    adx1015 = float(f.loc[f.index.time <= time(10, 10), "adx"].iloc[-1]) if len(f) else np.nan
    p945 = float(s.loc[s.index.time <= time(9, 40), "c"].iloc[-1])
    p1500 = float(s.loc[s.index.time <= time(14, 55), "c"].iloc[-1])
    rows.append(dict(day=d, dow=pd.Timestamp(d).day_name()[:3], dte=int(np.busday_count(d, exp(d))), open=o,
                     gap_pct=(o / prev_close - 1) * 100 if prev_close else np.nan, vix=vix0, vix_chg=vchg, em=em,
                     or30=float(orr["h"].max() - orr["l"].min()), or60=float(or60["h"].max() - or60["l"].min()),
                     adx1015=adx1015, range=float(s["h"].max() - s["l"].min()), move_945_1500=p1500 - p945))
    prev_close = float(s["c"].iloc[-1])
D = pd.DataFrame(rows)
D["or30_em"] = D.or30 / D.em
D["trend_day"] = (D.move_945_1500.abs() >= 0.5 * D.em)
D.to_csv("research/playbook/out_days.csv", index=False)

# ------------------------------------------------------------------ simulation helpers
def opt(d, k, kind):
    return option_day(exp(d), k, kind, d)

def bar(df, ts):
    return df.loc[ts] if df is not None and ts in df.index else None

def buy_trade(d, sig_ts, direction, exit_rule, slip):
    """Buy ATM CE/PE at the open after sig_ts; exit_rule(ts, futbar/spotbar) -> 'exit' reason or None, checked on
    each closed candle; filled at the next candle's open. Returns dict or None if option data missing."""
    s = S[S.index.date == d]
    k = int(round(float(s.loc[sig_ts, "c"]) / 50) * 50)
    o = opt(d, k, "CE" if direction > 0 else "PE")
    idx = list(s.index)
    i = idx.index(sig_ts)
    if i + 1 >= len(idx) or o is None:
        return None
    t_in = idx[i + 1]
    b = bar(o, t_in)
    if b is None:
        return None
    entry = float(b["o"]) + slip
    reason = None
    for j in range(i + 1, len(idx)):
        ts = idx[j]
        reason = exit_rule(ts, j - i)
        if reason:
            break
    t_out = idx[j + 1] if j + 1 < len(idx) else idx[j]
    bo = bar(o, t_out)
    if bo is None:
        bo = o[o.index <= t_out].iloc[-1] if len(o[o.index <= t_out]) else None
    if bo is None:
        return None
    px = max(float(bo["o"] if t_out != idx[j] else bo["c"]) - slip, 0.05)
    ch = charges([(entry, 1)], [(px, 1)], LOT)
    pts = px - entry
    return dict(day=d, t_signal=sig_ts.strftime("%H:%M"), dir=direction, strike=k, entry=entry, exit=px, pts=pts,
                rupees=pts * LOT - ch, charges=ch, reason=reason or "eod", idx_move=float(s.loc[t_out, "o"] if t_out != idx[j] else s.loc[t_out, "c"]) - float(s.loc[t_in, "o"]))


def orb(slip):
    out = []
    for _, r in D.iterrows():
        d = r.day
        if r.or30_em > 0.5:
            continue
        s = S[S.index.date == d]
        hi, lo = s.iloc[:6]["h"].max(), s.iloc[:6]["l"].min(); mid, w = (hi + lo) / 2, hi - lo
        win = s[(s.index.time >= time(9, 45)) & (s.index.time <= time(11, 25))]
        sig = next(((ts, 1 if c > hi else -1) for ts, c in win["c"].items() if c > hi or c < lo), None)
        if not sig:
            continue
        ts0, dr = sig
        edge = hi if dr > 0 else lo
        tgt = edge + dr * w

        def rule(ts, n, s=s, dr=dr, mid=mid, tgt=tgt, edge=edge, w=w):
            c, h, l = s.loc[ts, ["c", "h", "l"]]
            if (dr > 0 and h >= tgt) or (dr < 0 and l <= tgt):
                return "target"
            if dr * (c - mid) < 0:
                return "stop (OR mid)"
            if n == 6 and dr * (c - edge) < 0.5 * w:
                return "time stop"
            if ts.time() >= time(14, 40):
                return "14:45 exit"
            return None
        t = buy_trade(d, ts0, dr, rule, slip)
        if t:
            t.update(setup="ORB30", dte=r.dte, dow=r.dow)
            out.append(t)
    return out


def vwapf(slip):
    out = []
    for _, r in D.iterrows():
        d = r.day
        f = F[F.index.date == d]; s = S[S.index.date == d]
        if len(f) < 60:
            continue
        n_tr, busy_until = 0, None
        idx = list(f.index)
        for i in range(1, len(idx)):
            ts = idx[i]
            if not (time(10, 15) <= ts.time() <= time(13, 55)) or n_tr >= 2 or ts not in s.index:
                continue
            if busy_until is not None and ts <= busy_until:
                continue
            p, c = f.iloc[i - 1], f.iloc[i]
            if not (c["adx"] < 20):
                continue
            up_p, lo_p = p["vwap"] + 2 * p["vwap_sd"], p["vwap"] - 2 * p["vwap_sd"]
            up_c, lo_c = c["vwap"] + 2 * c["vwap_sd"], c["vwap"] - 2 * c["vwap_sd"]
            dr = 0
            if p["c"] > up_p and c["c"] <= up_c:
                dr, ext = -1, max(p["h"], c["h"])
            elif p["c"] < lo_p and c["c"] >= lo_c:
                dr, ext = 1, min(p["l"], c["l"])
            if not dr:
                continue
            tgt = float(c["vwap"])

            def rule(t2, n, f=f, dr=dr, ext=ext, tgt=tgt):
                if t2 not in f.index:
                    return "eod"
                b = f.loc[t2]
                if (dr > 0 and b["h"] >= tgt) or (dr < 0 and b["l"] <= tgt):
                    return "target (VWAP)"
                if dr * (b["c"] - ext) < 0:
                    return "stop (extreme)"
                if n >= 6:
                    return "time stop"
                if t2.time() >= time(14, 40):
                    return "14:45 exit"
                return None
            t = buy_trade(d, ts, dr, rule, slip)
            if t:
                t.update(setup="VWAPF", dte=r.dte, dow=r.dow)
                out.append(t); n_tr += 1
                busy_until = pd.Timestamp(f"{d} {t['t_signal']}") + timedelta(minutes=5 * 12)
                # (a trade lasts at most 6 candles plus exit; skip overlapping signals conservatively)
    return out


def ifly(slip, W=150, regime=False, name=None):
    out = []
    for _, r in D[D.dte == 0].iterrows():
        d = r.day
        if regime and not (r.or60 <= 0.5 * r.em and (pd.isna(r.vix_chg) or r.vix_chg <= 5)):
            continue
        s = S[S.index.date == d]
        t_in = pd.Timestamp(f"{d} 10:15")
        if t_in not in s.index:
            continue
        k = int(round(float(s.loc[pd.Timestamp(f'{d} 10:10'), 'c']) / 50) * 50)
        legs = [(k, "CE", -1), (k, "PE", -1), (k + W, "CE", 1), (k - W, "PE", 1)]
        frames = [opt(d, kk, kind) for kk, kind, _ in legs]
        if any(x is None or t_in not in x.index for x in frames):
            out.append(dict(day=d, setup=name or "IFLY", missing=True)); continue
        fills = [(max(float(x.loc[t_in, "o"]) + sg * slip, 0.05), sg) for x, (_, _, sg) in zip(frames, legs)]  # buy higher, sell lower
        credit = -sum(sg * p for p, sg in fills)
        idx = [t for t in s.index if t >= t_in]
        reason, t_out = "14:30 exit", pd.Timestamp(f"{d} 14:30")
        for j, ts in enumerate(idx):
            if ts >= pd.Timestamp(f"{d} 14:25"):
                break
            vals = [bar(x, ts) for x in frames]
            if any(v is None for v in vals):
                continue
            value = -sum(sg * float(v["c"]) for v, (_, _, sg) in zip(vals, legs))
            if value <= 0.5 * credit:
                reason, t_out = "50% target", idx[j + 1]; break
            if value >= 1.5 * credit:
                reason, t_out = "1.5x stop", idx[j + 1]; break
        # buy back shorts at px + slip, sell longs at px - slip
        ex = []
        for x, (_, _, sg) in zip(frames, legs):
            b = x[x.index <= t_out]
            px = float(b["o"].iloc[-1] if b.index[-1] == t_out else b["c"].iloc[-1])
            ex.append(((px + slip) if sg < 0 else max(px - slip, 0.05), sg))
        close_value = sum((p if sg < 0 else -p) for p, sg in ex)
        pts = credit - close_value
        buys = [(p, 1) for p, sg in fills if sg > 0] + [(p, 1) for p, sg in ex if sg < 0]
        sells = [(p, 1) for p, sg in fills if sg < 0] + [(p, 1) for p, sg in ex if sg > 0]
        ch = charges(buys, sells, LOT)
        out.append(dict(day=d, setup=name or ("IFLY-R" if regime else "IFLY"), dte=0, dow=r.dow, strike=k, entry=credit,
                        exit=close_value, pts=pts, rupees=pts * LOT - ch, charges=ch, reason=reason,
                        max_loss_pts=W - credit, missing=False))
    return out


def summ(tr, name):
    t = pd.DataFrame([x for x in tr if not x.get("missing")])
    miss = sum(1 for x in tr if x.get("missing"))
    if t.empty:
        return dict(setup=name, trades=0, missing=miss)
    r = t.rupees.values
    rng = np.random.default_rng(7)
    bs = [rng.choice(r, len(r)).mean() for _ in range(5000)]
    w, l = r[r > 0], r[r <= 0]
    aw, al = (w.mean() if len(w) else 0), (-l.mean() if len(l) else 0)
    return dict(setup=name, trades=len(r), missing=miss, win_pct=round(100 * len(w) / len(r), 1),
                be_win_pct=round(100 * al / (aw + al), 1) if aw + al else None, avg_win=round(aw), avg_loss=round(al),
                exp_per_trade=round(r.mean()), ci95=f"{np.percentile(bs, 2.5):.0f} to {np.percentile(bs, 97.5):.0f}",
                net=round(r.sum()), gross_pts=round(t.pts.sum() + 0, 1), charges=round(t.charges.sum()),
                worst=round(r.min()), dd=round(float((np.maximum.accumulate(np.cumsum(r)) - np.cumsum(r)).max())),
                exits="; ".join(f"{k} {v}" for k, v in t.reason.value_counts().items()))


if __name__ == "__main__":
    res, trades = [], []
    for slip in (0.1, 0.5):
        for name, fn in (("ORB30", lambda: orb(slip)), ("VWAPF", lambda: vwapf(slip)), ("IFLY", lambda: ifly(slip)),
                         ("IFLY-R", lambda: ifly(slip, regime=True)),
                         ("IFLY-W100 (robustness)", lambda: ifly(slip, W=100, name="IFLY-W100")),
                         ("IFLY-W200 (robustness)", lambda: ifly(slip, W=200, name="IFLY-W200"))):
            tr = fn()
            for x in tr:
                x["slip"] = slip
            trades += tr
            row = summ(tr, name); row["slip"] = slip; res.append(row)
            print(row, flush=True)
    pd.DataFrame(res).to_csv("research/playbook/out_summary.csv", index=False)
    pd.DataFrame(trades).to_csv("research/playbook/out_trades.csv", index=False)
