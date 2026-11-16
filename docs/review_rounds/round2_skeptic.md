# Backtest Integrity Skeptic: Round 2

No new backtests. Checks use the trade CSVs, `chair/settling.txt`, `scalpbot/review.py:72-81` and my round-1 scripts.

## 1. The Chair's settling experiments

**No arithmetic error found.** `b1_t1_min20` is exactly the baseline trades with T1 of 20 or more: IS 6 trades sum to −2,136, OOS 2 trades (2025-11-12 −250, 2025-12-29 +98) sum to −152. The 8 excluded OOS trades sum to +1,337, which is the whole OOS profit.

**What follows and what does not:**
- Follows (fact, high): B1's OOS profit came entirely from trades with a degenerate target.
- Does not follow: "B1 loses with a real target". Pooled min20 is 8 trades, mean −286, 95% interval about −620 to +48 (t, 7 df). Under the brief's rule that is insufficient sample. Say "no evidence of profit", not "evidence of loss".
- `b1_t1_uncapped` changes two things at once: the target, and the reach of the "no level inside T1" check. Alerts drop 17 to 13 and 10 to 7, so it is a different trade set, not the same trades with a bigger target.
- `review.py:78` skips only when `0 < cap < 20`. When price is already beyond the band (cap ≤ 0) the target silently becomes 2 × S. That is baseline behaviour too, but it is an untested path.
- I could not find the sheet's "minimum target 20 points" in `docs/`; the Chair should cite it.

## 2. Correction to my round 1

I wrote that S2 loses "at any slippage and at 8 lots". The sign is negative in both windows, but at 8 lots and zero slippage it is about −52 per trade with an interval of roughly −146 to +42, so not distinguishable from zero. At 8 lots and 0.25 slippage it is about −117 (−210 to −22). At 1 lot and 0.5 it is −264 (−354 to −170). S2's gross result is −20 per trade: no edge, plus certain costs.

## 3. Challenges to other reports

- **Funnel 8 and 11** ("waive volume, waive levels and gap-off raise B1 expectancy in both windows"): unsupported. The OOS B1 figures (+169, +162 per trade) rest on the above-market entry+2 fills. Gap-off is 6 extra trades, and the 3-point rule is the sheet's own entry instruction, not a fidelity setting.
- **Exits 10** ("time stop helps in both windows"): overstated. It rests on 4 and 2 time-stopped trades, and a tiny T1 switches the time stop off. No change follows, so it is harmless.
- **Exits unknown** (B1 deltas 0.46-0.56 against 0.60-0.80): not a defect. The range depends on days to expiry (`options.py:54-60`); the dte 0 trade has 0.76, dte 4 has 0.47.
- **Options 7 / L2** ("S1 trades and loses"): 4 trades, insufficient. S3 at credit 12 (21 and 19 trades) is adequately supported.
- **Checked and holds:** Funnel 2 and Options 1 (53 of 53 rejected alerts reproduced; slippage alone rejects 96% and 89%); Exits 5 and 7; Options 3.

## 4. Candidate options

| Option | Verdict | Overfitting risk | Condition |
|---|---|---|---|
| F1 gap-fill stops | Sign off | None (pessimistic fix) | Moot once L1 is in |
| F2 no futures splice | Sign off | None | I measured the splice and alert clustering only; the P&L effect is unknown. Rerun baseline once and confirm what history live uses |
| F3 exit at next open | Sign off | None | Worth −276 / −361 |
| F4 log bid/ask | Sign off logging; dissent on 0.25 as base | Medium | 0.25 is unmeasured and favours OOS. Report 0.25 and 0.5; a decision must hold at 0.5 |
| L1 B1 target floor 20 | Sign off as conformance to the sheet only | Low if 20 predates the data | Not a measured improvement (6 and 2 trades). B1 falls to about 8 trades a year |
| L2 pause S1, S3 | Sign off | None (they never trade) | Drop "S1 loses" |
| D1 pause S2 | Sign off | Low | See section 5 |
| D2 B1 paper-only | Sign off, amended | None | 30 trades is about four years at 8 a year. Say plainly that B1 is off |
| D3 no scaling to 8-10 lots | Sign off | None | IS at 8 lots and zero slippage is −4,889 per lot |
| E1 no loosening | Sign off | None (no change) | 17 experiments worse in both windows |
| E2 remove expiry check | Dissent, mild | None | Zero benefit; it becomes binding if the credit minimum ever drops. Keep it |
| X1 no exit change | Sign off | — | `exit_no_index_stop`: OOS expectancy −257 to −262, worst trade doubles |
| X2 re-test after-T1 rule | Amend: defer indefinitely | High if run early | With a real target 1 IS and 0 OOS trades reached T1 |
| V1 unseen window | Sign off, amended | — | "30 trades per setup" is unreachable for B1 in six months: pool several unseen windows. Fix F1-F3 first, freeze the code, pre-register metric and threshold. Mid-2025 may have a different lot size and expiry weekday |

**One option of my own.** After F1-F3 and L1, rerun the baseline once on both windows, publish it as the new reference, and change no parameter. Effect unknown until run; it could move S2 through the splice fix.

## 5. Is pausing S2 itself overfitting?

No. It is the default of not trading something with no demonstrated edge, not a fitted parameter.
- Negative in two independent windows with almost the same expectancy (−270, −257); pooled t = −5.5 on 37 trades, which survives a correction for six setups.
- Negative in all 31 S2 variants in both windows.

**What would reverse it:** measured live slippage of 0.1 per fill or less, together with a pre-registered S2 rule showing net expectancy with a 95% lower bound above zero on at least 30 trades from unseen data at that measured cost.

## 6. Agreed and contested

**Agreed:**
- Baseline arithmetic is right.
- S2 has no edge after costs.
- The credit gate rejections are a slippage effect, and the rejected trades lose.
- B1's target is degenerate and OOS B1 profit is an artifact.
- No loosening helps; lots only dilute charges; the same-candle rule is immaterial.
- B2, B3, S1: insufficient sample.

**Contested, with the one experiment that settles each:**
- B1 with a real target, loss or zero: uncapped and min20 on pooled unseen windows, pre-registered.
- Slippage, 0.25 or 0.5: live bid/ask logs (F4).
- Size of the roll-splice effect: one baseline rerun with per-contract history.
- Index stop on S2: none worth running while S2 is paused.
- Signals hidden while a position is open (Funnel): one run that logs them.
