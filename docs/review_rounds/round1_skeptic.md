# Backtest Integrity Skeptic: Round 1

No new backtest runs. Everything below comes from the CSVs, the cached candles and the code. Scripts: `skeptic/a1.py` to `a5.py` (run with the venv python from the repo root).

## Findings

**1. Bookkeeping is correct (fact, high confidence).** I recomputed all 61 baseline trades (not just 6) from the raw option and futures candles: entry, exit, exit reason and time match in 61 of 61, and all 53 credit-rejected rows reproduce. Examples:
- 2026-06-01 S2 "50% target": opens 22.00 after slippage, value 10.95 at the 14:00 close, +1 slippage = 11.95.
- 2026-05-07 12:50 rejected alert: 12:45 closes 79.95 − 57.35 = 22.60, 12:50 opens 80.10 − 57.40 = 22.70, minus 1.0 = 21.70, below 22.
- Charges on 2025-12-01 recomputed by hand: Rs 64.62, matches.
- No traded leg had a stale or missing candle at the signal, and no look-ahead found in `HistOptions.chain` (backtest.py:309) or `build_context`.

**2. B1's target is often degenerate, and this drives the OOS B1 result (fact, high confidence).** `setups.py:254` caps T1 at the distance to the VWAP 1-SD band, with no minimum (`setups.py:124`). 11 of 21 B1 trades had T1 under 7 index points (as low as 0.2 and 1.0) against S of 13-20.
- T1 then "hits" on the entry candle (backtest.py:658-659), which switches off the time stop and invalidation exit, and moves the stop to entry+2.
- That stop is often above the market and still fills at entry+2 (backtest.py:664). In 4 of 5 OOS "stop after T1" exits the exit candle opened below the stop (2025-11-13: stop 133.10, open 128.20).
- Bias: flatters. Size: `fid_stop_gap_fill` takes OOS B1 from +1,185 to +429 and wins from 7 to 4 of 10; IS unchanged.
- The one large winner (2025-12-01, +1,674) is also a T1 = 6.7 trade. Without it OOS B1 is −490.
- This is partly a live-rule defect, not only a simulator one: the alert would print "T1 +0.2".

**3. Futures are spliced across monthly contracts without adjustment (fact; effect size is inference, medium confidence).** backtest.py:154-162. Reproduce: 2026-07-28 last futures close 23,983.2, 2026-07-29 open 24,235.6 (+252), while spot gapped +191, so about 61 points is splice; 2026-07-01 about 98.
- Prior-day high/low, ATR, ADX and the 15-minute EMA bias all read the jump.
- First post-roll days are 6 of 123 IS days but carry 9 of 67 alerts, 8 of them bull put spreads (upward bias after an upward splice). Traded result: 4 trades, −719.
- Also 2026-06-03 has zero futures volume on all 75 candles, so VWAP is meaningless that day (no alerts fired).

**4. Same-candle rule: zero effect (fact, high confidence).** It can only matter when the disaster stop and T1 fall in one candle before T1. That happened 0 times in 24 buy trades; `fid_target_first` is identical in both windows. One-minute data would not change this. It would matter for finding 2 (8 trades) and for spread stops judged on closes, but not enough to offset −264 per S2 trade.

**5. Smaller simulator biases.**
- Exits triggered by a close fill at that same close (backtest.py:617, 630). Filling at the next open instead costs Rs 276 IS and Rs 361 OOS. Flatters slightly.
- `exit_at_t1` and book-half price T1 as entry + T1 × delta (backtest.py:672, 676). On 8 T1 trades the approximation averages +4.4 points against +2.8 at the candle close. Flatters those variants by roughly 1.5 points per T1 trade (inference).

**6. Slippage (fact for the arithmetic, inference for plausibility).** Sweep rows mix two effects, so I repriced the same baseline trades:

| | 0 | 0.1 | 0.25 | 0.5 |
|---|---|---|---|---|
| IS, 1 lot | −7,243 | −7,984 | −9,096 | −10,949 |
| OOS, 1 lot | −442 | −975 | −1,774 | −3,106 |
| IS, 8 lots (per lot) | −4,889 | −5,630 | −6,741 | −8,594 |
| OOS, 8 lots (per lot) | +1,251 | +718 | −81 | −1,414 |

- At 1 lot no slippage level breaks even in either window. At 8 lots IS never does; OOS breaks even near 0.23 per fill.
- S2 alone is negative at zero slippage and 8 lots in both windows (−1,260, −660).
- Selection effect: `fid_slip_0` admits 14 extra trades per window, which lose about −2,286 (IS) and −277 (OOS).
- 0.1-0.25 per fill is plausible for near-the-money weeklies at 1-10 lots; the data has no bid/ask, so this is unverified.

**7. Statistical power (bootstrap, 20,000 resamples of per-trade rupees; normal approximation agrees within Rs 50).**

| | n | mean | 95% interval |
|---|---|---|---|
| B1 IS | 11 | −337 | −564 to −122 |
| B1 OOS | 10 | +118 | −124 to +496 |
| B1 pooled | 21 | −120 | −321 to +117 |
| S2 IS | 22 | −270 | −392 to −138 |
| S2 OOS | 15 | −257 | −379 to −117 |
| S2 pooled | 37 | −264 | −354 to −170 |

- S2 is negative beyond doubt. B1 pooled cannot be told from zero. B2 and B3: insufficient sample.
- The standard error of a window's net is about Rs 2,000, so sweep differences under about Rs 2,000 are noise.

**8. Overfitting (fact).** Of 80 experiments, 59 change anything; 17 beat baseline in both windows, 17 are worse in both, 16 flip.
- All 17 "both better" are cost assumptions (lots, slippage) or trading less (drop rows), except `exit_no_index_stop` (+1,268, +698) and `exit_credit_target_0.7` (+312, +120). Chance alone would give about 9 of the roughly 38 rule changes.
- Worse in both: min credit 18/15/12, both S2 delta widenings, no credit gate, stop cap 25/30/40, ADX 15, cooldown 15, no time stop, time stop 6, and waiving B1 ADX, B1 day range, S2 ADX, S2 day range.
- Flips: `exit_at_t1`, `exit_no_lock`, `exit_lock_be`, `exit_lock_half_t1`, `fid_entry_gap_off`, `entry_adx_25`, waive B1 volume, waive B1 PDH/PDL, waive S2 VIX, `entry_vix_up_8`, `drop_only_S2`, `diag_s3_chart_open_credit_12`, slippage 0.1/0.25/1.0.

**9. Regime (fact).** The IS − OOS gap of −7,843 splits as B1 −4,894, S2 −2,088 (more trades at the same expectancy), B2/B3 −861. So it is not B1 alone.
- OOS is two markets: Nov-Dec 2025 has median 5-minute ATR 18.2 and VIX 11.2; Jan-Apr 2026 has ATR 28.1 and VIX 14.8 (up to 27.9). IS sits between (23.6, 13.4).
- 7 of 10 OOS B1 trades and all of its profit (+1,450) come from Nov-Dec; Jan-Apr B1 is 3 trades, −266. No trades at all from 2025-12-30 to 2026-02-04.
- Lot size of 65 applied to 2025 trades: effect under a few hundred rupees (inference).

## The eight predictions

| # | IS | OOS | Verdict |
|---|---|---|---|
| P1 book at T1: about +2,000, still negative | +1,163, still negative | −977 | Refuted OOS; half-size IS |
| P2 S2 negative at zero slippage | −5,250 (same trades −3,077) | −1,951 | Confirmed |
| P3 no credit gate: more S2, same expectancy | +15 trades, −271 vs −270 | +16 trades, −203 | Confirmed |
| P4 lower credit minimum is worse | −10,144 to −15,891 | −6,106 to −12,551 | Confirmed |
| P5 stop cap is the biggest buy-alert lever | +17, largest | +20, largest | Confirmed |
| P6 same-candle rule changes at most 5 trades | 0 | 0 | Confirmed |
| P7 S1/S3 barely trade with chart checks off | 0 trades | 0 trades | Confirmed |
| P8 no single change is profitable | 0 of 80 | drop S2: +642, +1,084 | Confirmed IS; undecided OOS |

## Sign-off

**I sign off:**
- The simulator's arithmetic and the baseline numbers.
- S2 as coded loses after costs in both windows, at any slippage and at 8 lots.
- Lowering the credit minimum, widening the S2 delta range or removing the fill-time credit gate makes things worse.
- The same-candle rule is immaterial.
- Costs alone do not explain the IS loss.

**I refuse:**
- "B1 works out of sample." It rests on one trade plus a stop-fill artifact, in a low-volatility two-month stretch.
- Any exit or entry tuning chosen from these sweeps, including `exit_no_index_stop`.
- Any conclusion about B2, B3, S1 or S3.
- "8 lots at 0.25 slippage breaks even": true in OOS only.
- Any B1 expectancy figure until the T1 floor and the above-market stop fill are fixed and the futures splice is back-adjusted.
