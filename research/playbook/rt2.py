import sys; sys.path.insert(0, ".")
import numpy as np, pandas as pd
from datetime import time
import research.playbook.study as st
def run(slip, qual, flip=1):
    out=[]; dropped=0; stale=0; dist=[]
    for _, r in st.D.iterrows():
        q = (r.vix > 18 or r.gap_pct <= -0.5 or r.or30_em > 0.5)
        if q != qual: continue
        d=r.day; s=st.S[st.S.index.date==d]
        hi,lo=s.iloc[:6]["h"].max(), s.iloc[:6]["l"].min(); mid=(hi+lo)/2
        ts0=pd.Timestamp(f"{d} 10:10")
        if ts0 not in s.index: dropped+=1; continue
        c=s.loc[ts0,"c"]; dr=1 if c>hi else -1 if c<lo else 0
        if not dr: continue
        dist.append(abs(c-mid)); dr*=flip
        def rule(ts,n,s=s,dr=dr,mid=mid):
            if dr*flip*(s.loc[ts,"c"]-mid)<0: return "stop"
            if ts.time()>=time(14,40): return "eod"
        t=st.buy_trade(d,ts0,dr,rule,slip)
        if t is None: dropped+=1; continue
        k=t["strike"]; o=st.opt(d,k,"CE" if dr>0 else "PE")
        if pd.Timestamp(f"{d} 14:45") not in o.index or pd.Timestamp(f"{d} 10:15") not in o.index: stale+=1
        out.append(t)
    x=pd.DataFrame(out); return x, dropped, stale, np.array(dist)
for qual,flip,lab in ((True,1,"TREND10"),(False,1,"same rule on NON-qualified days"),(True,-1,"opposite direction on qualified days")):
    x,dr_,stl,dist=run(0.1,qual,flip)
    print(f"{lab}: n {len(x)} mean {x.rupees.mean():.0f} median {x.rupees.median():.0f} dropped(no data) {dr_} stale-bar trades {stl} | stop dist pts median {np.median(dist):.0f} p90 {np.percentile(dist,90):.0f} -> Rs@delta0.5 median {np.median(dist)*0.5*65:.0f}")
# IFLY: how many candles skipped in stop check because a leg bar missing; and exit fill bars stale
sk=0; tot=0
for _, r in st.D[st.D.dte==0].iterrows():
    d=r.day; s=st.S[st.S.index.date==d]; t_in=pd.Timestamp(f"{d} 10:15")
    if t_in not in s.index: continue
    k=int(round(float(s.loc[pd.Timestamp(f'{d} 10:10'),'c'])/50)*50)
    fr=[st.opt(d,kk,kd) for kk,kd in ((k,"CE"),(k,"PE"),(k+150,"CE"),(k-150,"PE"))]
    if any(f is None or t_in not in f.index for f in fr): continue
    for ts in [t for t in s.index if t_in<=t<pd.Timestamp(f"{d} 14:25")]:
        tot+=1; sk+= any(ts not in f.index for f in fr)
print("IFLY candles where stop check skipped (missing leg bar):",sk,"of",tot)
# expiry list sanity: expiries that are not Tuesday
print("non-Tue expiries in window:",[str(e) for e in st.expiries if pd.Timestamp("2025-11-01")<=pd.Timestamp(e)<=pd.Timestamp("2026-10-31") and pd.Timestamp(e).dayofweek!=1])
print("days in D that are expiries but dte!=0 or vice versa:", sum((st.D.day.isin(st.expiries))!=(st.D.dte==0)))
d=st.D; print("Feb 2026 rows:"); print(d[(d.day.astype(str)>="2026-01-29")&(d.day.astype(str)<="2026-02-04")][["day","dow","open","gap_pct","vix","range"]].to_string())
