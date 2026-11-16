# Exits & Risk, Round 2

No new backtests. Evidence: baseline trades CSVs, sweeps CSVs, chair/settling.txt.

## 1. Challenges to others

- **Skeptic 8 ("exit_no_index_stop beats baseline in both windows") is overstated.** S2 expectancy per trade gets worse in OOS (-257 to -262); the +698 comes from 3 fewer trades (15 to 12). Worst trade goes -680 to -1,634 (IS) and -599 to -1,207 (OOS). It is "better in both" on net only.
- **Funnel 8 and 11 ("waive volume, waive levels raise B1 expectancy in both windows") are unsupported.** Their OOS gains (+2,877, +2,273) were measured with the band-capped target and above-market stop fills. Baseline OOS B1 falls from +1,185 to -451 once the target is real (settling.txt), and those rows were not re-run. The "no level inside T1" check also uses the capped T1 (setups.py:128), so it passed trades that a real target would block.
- **Skeptic 2 holds.** 3 of 5 OOS entry+2 exits turn into losses under fid_stop_gap_fill (wins 7 to 4), consistent with their candle check.
- **Funnel 7 (wider stop cap loses) holds.** B1 worst trade reaches -1,563 at s_max_25 in OOS.
- **Skeptic 5 (close-triggered exits fill at the same close):** code confirmed (backtest.py:617, 630); the rupee figure is not tested by me.

## 2. Corrections to my round 1

- **Finding 8 is withdrawn as a ranking.** Every after-T1 comparison was run on targets of 0.2-6.7 points. With a real target only 1 of 9 IS and 0 of 7 OOS trades reach T1, so the after-T1 rule has almost nothing to act on.
- **Finding 7:** I said +429 was nearer the truth for OOS B1. The Chair's -451 (uncapped) and -152 (minimum 20) replace it.
- **Finding 6:** I called B1 a parameter problem. It is a strategy problem in the stop/target geometry.

## 3. Geometry: can an exit rule rescue B1?

In premium points, the full 2 x S target is a median 17.6 (IS) and 18.2 (OOS). The best excursion of baseline trades is a median 6.1 and 5.7. Only 1 of 11 IS and 1 of 10 OOS trades ever reached the full target; 3 and 2 reached half of it. The typical trade moves about one third of the way before reversing, and the invalidation level (S = 12-20) is inside one 5-minute ATR (22-30). A 2:1 payoff needs about 42% winners after costs; the data shows 5-10%.

Upper bound in IS: selling every trade at its exact high gives 72.1 points = Rs 4,687, less about Rs 1,030 exit costs = +3,660. That requires perfect foresight. A fixed premium target of 5 points (about half of S), computed by hand from mfe_pts: IS 8 of 11 hit, net about Rs -240; OOS 7 of 10 hit, about +1,135. This is fitted in hindsight on spent data and needs about 73% winners to break even. **No exit rule tested or computable here makes B1 positive in IS.**

## 4. Options in scope

- **F1: support.** IS unchanged, OOS +1,185 to +429; moot once L1 is in.
- **F3: support.** Direction is certain; size is the Skeptic's.
- **L1: support as a defect fix, not as an improvement.** It leaves 6 IS and 2 OOS trades, both negative (-2,137, -152).
- **X1: support.** See the first challenge.
- **X2: amend.** After L1 almost no trade reaches T1, so the after-T1 comparison has no subjects. Replace it with one pre-registered test of target distance (below).
- **D2: support.** Pooled B1 is 21 trades; with a real target 16 trades, both windows negative.
- **D3: support.** Points are identical at any lot count; 8 lots turns IS into about -68,800.

**My option O1 (to pre-register, not adopt):** B1 target = 0.5 x S x delta premium points, sell all, on a fresh window. Hypothesis: the pullback pays a small bounce, not a trend leg. Measured: hand calculation above (IS about -240, OOS about +1,135). Backfire: losses stay 5-13 points against wins of about 4.5, so a win rate under about 73% loses; costs are 40% of each win. Must hold: at least 30 trades, win rate above 75%.

## 5. Still contested

- Whether B1 has any edge at a short target: O1 on an unfetched window.
- Real spread slippage: logged bid/ask (F4).
- Whether removing the S2 index stop helps per trade: moot if D1 is adopted.
