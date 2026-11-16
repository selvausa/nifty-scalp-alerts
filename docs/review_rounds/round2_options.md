# Options Structure Analyst - Round 2

No new backtests. Sources: baseline CSVs, my round-1 dumps (`optstage_*.csv`, `days_*.csv`), the other round-1 reports.

## 1. Challenges to other reports

**Skeptic 3 (futures splice) - overstated as a driver of results.** The IS numbers reproduce: 9 alerts on the 6 post-roll days, 4 trades, -719 (2026-07-01 -450; 07-29 -301 and +34; 10-28 -2). But OOS has 1 alert and 0 trades on its 6 post-roll days (2025-11-26 .. 2026-04-29). Pooled: 10 alerts on 12 days (0.83 a day) against 0.49 a day overall. F2 is a correct fix, but it moves IS by at most about 719 and OOS by nothing on the first day.

**Skeptic 6 / Chair F4 ("0.1-0.25 per fill is plausible") - the live rule already implies the answer.** Live blocks a spread unless every leg's bid-ask is at most 0.15 (config.py:39, options.py:124-129, setups.py:335). The backtest never applies this check (no quotes, backtest.py:319). A spread that passes live costs at most about 0.075 per leg to cross, plus latency. So the baseline 0.5 per fill describes trades the live rule would refuse. The consistent base case is 0.1, where S2 is still -6,771 IS and -2,731 OOS (`fid_slip_0.1`, 36 and 30 trades).

**Exits, unknown 3 (B1 deltas 0.46-0.56 "against the 0.60-0.80 rule") - not a defect.** 0.60-0.80 is the expiry-day range only; dte 1 is 0.50-0.65, otherwise 0.45-0.55 (options.py:56-62). Trades match exactly: dte 0 0.68-0.78, dte 1 0.53-0.64, dte 2-4 0.47-0.53, both windows.

**Checked and holds:** Funnel 2 (25/26 and 24/27 rejections are slippage only). Exits 4 (50% target unreachable intraday). Skeptic 9 on lot size: November-December 2025 trades total +14.4 points, so a 75 lot adds about +144 rupees.

## 2. Corrections to my round 1

- **Finding 5, S3: I withdraw "code bug".** The code implements the sheet as written: delta 0.20 or less (options.py:66) and a 22 credit (setups.py:470). The inconsistency is the sheet's own. At delta <= 0.20 and dte 1-4, 153 candles paid at most 16.8, including OOS dte-1 candles at median VIX 22 (maximum 15.1). The sheet's "22 credit" example cannot occur at its own delta limit in either window.
- **Finding 7, S1:** "max 18.4 per side" was a proxy from S2 strikes at dte 1, not S1 strikes. Direct evidence is 5 candles, all dte 0, paying 6.9-12.2 in total. The Chair's L2 wording should say that. That 44 was never reached still stands (`diag_s1_chart_checks_off`: 0 alerts).

## 3. Candidate options in my scope

- **L2: support,** with the wording fix above. Opening S3 loses in both windows (21 trades -5,694; 19 trades -4,879). S1: 4 trades, all losers, insufficient sample.
- **D1: support.** No dte is profitable (dte 2: 10 trades -2,661; dte 3: 8, -2,707; dte 4: 17, -4,862). The feasible credit band is 22-25 at delta 0.27-0.28, and S2 stays negative at slippage 0.1 and 0.
- **E2: oppose, keep the check.** It is redundant only while the minimum stays above 10.3, the expiry-day maximum. It costs nothing and becomes the only guard if the minimum is ever lowered.
- **F4: support, amended.** Log bid, ask and last price for each leg at the alert and one candle later, and keep logging S2, S1 and S3 as paper alerts while paused.
- **Credit gate: keep both gates, change neither threshold.** Removing the fill gate adds 15 and 16 trades that lose about 273 and 153 each.

**Own option O1 (simulator only).** In `HistOptions.fill_quote` (backtest.py:319) return bid = last - slip, ask = last + slip. The alert credit then uses the same basis as live, and the leg-spread check is exercised. Hypothesis: the 53 phantom alerts disappear at the alert stage and traded results barely change. Not measured. Backfire: cooldown timing shifts, so trade sets change slightly. Must hold: the S2 trade count stays within a few of 22 and 15.

## 4. Still contested

- **Real slippage on spread legs.** Settled by F4 logs over 30 or more alerts.
- **Whether the sheet meant a separate S3 minimum.** Owner's decision; the data says any minimum of 12-22 loses or never trades.
- **Size of the splice effect.** One run with F2 applied, both windows.
