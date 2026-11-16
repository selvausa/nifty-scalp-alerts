import sys; sys.path.insert(0, ".")
import numpy as np, pandas as pd
from datetime import time
pd.set_option("display.width", 200)
P="research/playbook/"
D=pd.read_csv(P+"out_days.csv",parse_dates=["day"])
T=pd.read_csv(P+"out_trend10_0.1.csv",parse_dates=["day"]); T5=pd.read_csv(P+"out_trend10_0.5.csv",parse_dates=["day"])
r=T.rupees.sort_values(ascending=False).values
print("== TREND10 @0.1 n",len(r),"mean",r.mean().round(0),"median",np.median(r).round(0))
for k in (1,2,3,4,5,6): print(f" drop top{k}: mean {r[k:].mean():.0f} net {r[k:].sum():.0f}")
loo=[np.delete(r,i).mean() for i in range(len(r))]; print(" LOO mean range",round(min(loo)),round(max(loo)))
rng=np.random.default_rng(1); bs=np.array([rng.choice(r,len(r)).mean() for _ in range(20000)]); print(" P(boot mean<=0)",(bs<=0).mean().round(3))
r5=T5.rupees.sort_values(ascending=False).values; print(" @0.5 drop top3 mean",r5[3:].mean().round(0),"top5",r5[5:].mean().round(0))
print(" sum top3 / net", r[:3].sum().round(0), r.sum().round(0))
M=T.merge(D,on="day",suffixes=("","_d"))
M["crit"]=np.select([M.vix>18],["vix>18"],"")
M["c_vix"]=M.vix>18; M["c_gap"]=M.gap_pct<=-0.5; M["c_or"]=M.or30_em>0.5
for c in ("c_vix","c_gap","c_or"): print(f" {c}: n {M[c].sum()} mean {M.loc[M[c],'rupees'].mean():.0f} | only-this n {(M[c]&(M[['c_vix','c_gap','c_or']].sum(1)==1)).sum()} mean {M.loc[M[c]&(M[['c_vix','c_gap','c_or']].sum(1)==1),'rupees'].mean():.0f}")
print(" not-vix>18 trades: n",(~M.c_vix).sum(),"mean",M.loc[~M.c_vix,"rupees"].mean().round(0))
print(M.groupby("dow").rupees.agg(["size","mean","sum"]).round(0).to_string())
M["mon"]=M.day.dt.to_period("M"); print(M.groupby("mon").rupees.agg(["size","sum"]).round(0).T.to_string())
print(" dte0:",M.loc[M.dte==0,"rupees"].round(0).tolist())
print(" low vix<12:",M.loc[M.vix<12,["day","rupees"]].values.tolist()); print(" vix<14 n",(M.vix<14).sum(),"mean",M.loc[M.vix<14,"rupees"].mean())
st_=M[M.reason.str.startswith("stop")].rupees; print(" stops n",len(st_),"mean",st_.mean().round(0),"min",st_.min().round(0))
print(" losers<=-1000:",(r<=-1000).sum(),"of",len(r))
cum=np.cumsum(T.rupees.values); print(" maxDD",(np.maximum.accumulate(cum)-cum).max().round(0))
# IFLY draft filter
X=pd.read_csv(P+"out_trades.csv",parse_dates=["day"]); X=X[X.setup=="IFLY"]
miss=X[X.missing==True].day.unique(); print("\n== IFLY missing days"); print(D[D.day.isin(miss)][["day","vix","gap_pct","or60","em","range","trend_day"]].to_string())
print(" all-expiry days median range",D[D.dte==0].range.median())
for slip in (0.1,0.5):
    x=X[(X.slip==slip)&(X.missing!=True)].merge(D,on="day",suffixes=("","_d"))
    tq=(x.vix>18)|(x.gap_pct<=-0.5)|(x.or30_em>0.5)
    f=(~tq)&(x.gap_pct.abs()<=0.5)&(x.or60<=0.7*x.em)&~(x.vix_chg>5)
    y=x[f]; h=y.day<"2026-05-01"
    print(f" slip {slip} draft-filter IFLY n {len(y)} mean {y.rupees.mean():.0f} H1 n{h.sum()} {y[h].rupees.mean():.0f} H2 n{(~h).sum()} {y[~h].rupees.mean():.0f} worst {y.rupees.min():.0f}; trend-qualified expiry n {tq.sum()} mean {x[tq].rupees.mean():.0f}; lowvix<12 n {(x.vix<12).sum()} mean {x[x.vix<12].rupees.mean():.0f}")
    if slip==0.1: print("  rejected-by-filter mean", x[~f].rupees.mean().round(0), "n", (~f).sum(), "| worst all", x.rupees.min().round(0), "reasons", x.reason.value_counts().to_dict())
print(" VIX NaN days",D.vix.isna().sum()," gap NaN",D.gap_pct.isna().sum(), " vixchg NaN",D.vix_chg.isna().sum())
