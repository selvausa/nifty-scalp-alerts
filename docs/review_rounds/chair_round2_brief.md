# Round 2 brief from the Chair

Round-1 reports (read the three that are not yours):
- funnel/round1.md, options/round1.md, exits/round1.md, skeptic/round1.md (all under this review folder)
- chair/settling.txt : settling experiments the Chair ran after round 1 on B1's target (both windows)

## What the Chair's settling experiments show (chair/settling.txt)
B1's target is 2 x S capped at the VWAP +1 SD band, with no floor (setups.py:251-254). The cheat sheet itself says the minimum target is 20 index points.
- b1_t1_uncapped (target always 2 x S): B1 IS 9 trades, 1 reached T1, net -3,066. OOS 7 trades, 0 reached T1, net -451 (baseline +1,185).
- b1_t1_min20 (skip B1 when the capped target is under 20 points): B1 IS 6 trades, net -2,137. OOS 2 trades, net -152.
- Adding the stop gap-fill fix changes neither (no above-market stops remain once the target is real).
So B1's out-of-sample profit does not survive a real target.

## Candidate options (Chair's draft, for you to attack)
Fidelity fixes (simulator):
 F1. Stops that the candle opened through fill at the open, and a stop moved above the market exits at market (fid_stop_gap_fill: OOS B1 +1,185 -> +429; IS unchanged).
 F2. Monthly futures roll: build each day's history from the current contract instead of splicing (skeptic: ~61-98 point jumps; first post-roll days carry 9 of 67 IS alerts, 4 trades, -719).
 F3. Exits triggered by a 5-minute close fill at the next open, not that close (skeptic: -276 IS, -361 OOS).
 F4. Log live bid/ask on every alert leg so slippage can be measured instead of assumed (base case 0.25 per fill until then).
Live-rule defects:
 L1. B1: skip when the band-capped target is under 20 index points (the sheet's own minimum). Measured: B1 IS -3,709 -> -2,137 (6 trades), OOS +1,185 -> -152 (2 trades).
 L2. S3 and S1: the credit minimum cannot be met at their delta ranges (S3 max credit 16.8 vs 22; S1 max 18.4 per side vs 22). Lowering the minimum makes them trade and lose (diag rows). Pause both rather than recalibrate.
Drop / pause:
 D1. Pause S2 alerts: negative in both windows (-5,937, -3,849), negative at zero slippage and at 8 lots, pooled 95% interval -354 to -170 per trade.
 D2. Keep B1 as paper-only alerts (no money) until it shows positive expectancy over at least 30 trades on the fixed simulator.
 D3. Do not scale to 8-10 lots: lots dilute charges only; the gross result is negative in-sample.
Entry filters:
 E1. Make no entry-filter loosening: every loosening adds losing trades in-sample (stop cap, credit minimum, S2 delta, ADX, cooldown).
 E2. Remove "Not expiry day after 12:00" from S2 as redundant (credit can never reach 22 on expiry day). Cosmetic.
Exit rules:
 X1. No exit change is adopted now. exit_no_index_stop improves both windows (+1,268, +698) but doubles the worst trade and rests on 3 fewer trades OOS.
 X2. After F1-F3 and L1, re-test the after-T1 rule (sell half at T1 vs entry+2 lock vs all at T1) as ONE pre-registered comparison on new data.
Validation:
 V1. Treat both existing windows as spent for tuning. Any future change must be stated in advance, tested on a window not yet fetched (for example 2025-05..2025-10), with at least 30 trades per setup and at most one parameter changed at a time.

## What I need from you (at most 600 words; save to <your-role>/round2.md and return it)
1. Challenge at least two findings from OTHER specialists' round-1 reports that you think are wrong, overstated or unsupported. Quote the finding number, give your counter-evidence (file rows, numbers or code lines). If you checked and it holds, say so in one line each for the ones you tested.
2. If anything in your own round 1 is weakened by the others' reports or the Chair's settling experiments, correct it.
3. For each candidate option in your scope: support, oppose or amend, with the evidence. Add at most two options of your own, each with: the change (parameter old -> new or logic, file:line), hypothesis, measured effect in both windows, how it could backfire, what must hold out of sample.
4. List what is still contested and the single experiment that would settle each.
Rules from BRIEF.md still apply (read-only repo, no network, write only in your folder). Run at most 2 new backtests, and only if a contested point needs it.
