# Round 2 — Signal & Funnel Analyst

No new backtests. Script: `funnel/b.py` (sweep rows, candles and trades CSVs).

## 1. Alerts hidden while a position is open

Direct measures (per-setup `alerts` in the sweep CSVs):

| Comparison | IS | OOS |
|---|---|---|
| B1 alerts, baseline -> drop_only_B1 (no S2 positions) | 17 -> 17 | 10 -> 12 |
| S2 alerts, baseline -> drop_only_S2 (no buy positions) | 48 -> 48 | 42 -> 42 |
| S2 alerts, fid_no_entry_credit_gate (+15 / +16 S2 positions) | 48 -> 37 | 42 -> 31 |
| S2 alerts, fid_slip_1.0 (-13 / -7 S2 positions) | 48 -> 55 | 42 -> 43 |

- **Cross-setup hiding is 0 alerts IS and 2 B1 alerts OOS.** Fact, high. Those 2 extra B1 trades net -101 (drop_only_B1: 12 trades, +1,084 vs 10, +1,185).
- **S2 hides its own repeats: about 0.1-0.7 alerts per open S2 position.** Inference, low precision. With 22 / 15 baseline positions that is roughly 3-16 hidden S2 alerts IS and 2-10 OOS; about half would fail the fill gate.
- **No conclusion changes.** Hidden alerts are almost all S2, which loses -203 to -273 per trade in every variant.

## 2. Challenges to other reports

- **Skeptic 3 (post-roll days carry 9 of 67 IS alerts): holds in IS, does not replicate OOS.** IS: 9 alerts on 6 post-roll days against 3.3 expected (permutation p = 0.014). OOS: 3 alerts against 2.7 expected (p = 0.47), 1 trade, -384. The splice is real; an alert bias from it is shown in one window only. F2 is still correct as a fidelity fix; its effect on results is unproven.
- **Exits 10 ("the time stop helps in both windows", medium): overstated.** The B1 differences are -983 IS and -688 OOS, below the Skeptic's Rs 2,000 noise level, and were measured with the degenerate target that switches the time stop off after "T1". With a real target the time stop becomes 4 of 9 and 4 of 7 exits (settling.txt, b1_t1_uncapped), where it is untested. Confidence should be low.
- **Checked and hold:** Options 1 (I get the same 25/26 and 24/27 slippage-only rejections), Options 2, Options 4 (waive_S2_not_expiry row is identical to baseline in both windows), Skeptic 8's both-worse list (matches my per-setup rows).

## 3. Corrections to my round 1

- **Finding 8 and 11, withdrawn in part.** I said three B1 loosenings raise per-trade expectancy in both windows. The OOS half (+162 to +169) rests on trades with a 0.2-6.7 point target and the entry+2 fill artifact; with a real target OOS B1 is -451 or -152. The claim is unsupported. "None" stands, more firmly.
- **Finding 5.** The "levels inside T1" counts (88 / 85) were measured against the capped target, so they understate what a 2 x S target would block.
- **New fact:** 75 of 123 IS days and 87 of 121 OOS days had no alert at all.

## 4. Options in my scope

- **E1: support.** Every loosening is negative in IS (round 1, findings 4, 7, 8). After L1 the B1 OOS gains disappear too.
- **E2: amend to "leave it".** It changes nothing while the minimum is 22 (expiry-day credit tops out at 10.3), but it becomes the only guard if the minimum is ever lowered. Removing it has no benefit.
- **D1: support.** S2 is negative in all 14 S2 rows I tabulated, both windows. Trade-count cost: 22 / 15 trades and 48 / 42 alerts; it frees 0 / 2 B1 alerts.
- **L2: support.** Lowering the minimum to 12: S3 6 trades, 0 wins (IS); 7 trades, -305 each (OOS). diag_s3: -271 / -257 over 21 / 19 trades. S1: 2 trades per window, 0 wins.
- **Consequence for D2, amend.** With D1, L2 and L1 the bot trades about 11 times in 246 days (B1 6 + 2, B2 1, B3 1 + 1). Thirty B1 trades would take roughly three years. D2 needs a time limit or a lower bar stated in advance.

**My one addition (simulator only):** evaluate and log setups while a position is open, outcome "passed, position open" (backtest.py:476-480). No effect on results. Backfire: none beyond run time. It makes the funnel complete.

## 5. Still contested

- Size of the S2 self-hiding: one run with the logging change above.
- Whether the roll splice biases alerts: rerun both windows after F2 and compare post-roll alerts.
- Whether 1.0 point spread slippage is right: F4 live quotes. Matters only if S2 is kept.
