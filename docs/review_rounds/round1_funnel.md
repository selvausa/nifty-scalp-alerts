# Round 1 — Signal & Funnel Analyst

Sources: `docs/backtest_{funnel_setups,funnel_checks,candles,sweeps,untraded,trades}_TAG.csv`, both windows. No extra experiments run. Script: `funnel/a.py`.

## Funnel (candles -> episodes -> passed every check -> alerts -> trades)

| Setup | IS (125 days) | OOS (121 days) |
|---|---|---|
| B1 | 2218 -> 249 -> 18 -> 17 -> 11 | 2499 -> 258 -> 11 -> 10 -> 10 |
| B2 | 105 -> 105 -> 1 -> 1 -> 1 | 112 -> 112 -> 1 -> 1 -> 0 |
| B3 | 69 -> 42 -> 1 -> 1 -> 1 | 116 -> 65 -> 1 -> 1 -> 1 |
| S1 | 179 -> 20 -> 0 -> 0 -> 0 | 237 -> 19 -> 0 -> 0 -> 0 |
| S2 | 1583 -> 171 -> 76 -> 48 -> 22 | 1673 -> 168 -> 84 -> 42 -> 15 |
| S3 | 509 -> 38 -> 0 -> 0 -> 0 | 495 -> 39 -> 0 -> 0 -> 0 |
| ALL | 96 passed -> 67 alerts -> 35 trades | 97 passed -> 54 alerts -> 26 trades |

## Findings

1. **Two leaks after the checks remove 64% (IS) and 73% (OOS) of passing candles.** Fact, high.
   - Passed -> alert: 29 IS / 43 OOS candles "passed, in cooldown" (28/42 are S2). These are repeats of the same setup and side within 30 minutes, not new episodes.
   - Alert -> trade: S2 loses 26 of 48 (IS) and 27 of 42 (OOS) to "credit below the minimum at entry". B1 loses 6 of 17 in IS to the 3-point entry gap; OOS loses 1 B2.

2. **The S2 entry-credit loss is caused by the slippage assumption, not by the market moving.** Fact, high. Untraded S2 alerts had signal credit 22.0-23.6 (median 22.6); the next-open credit was still >= 22 in 96% (IS) and 89% (OOS) of them. They fail only after the 1.0 point slippage deduction.

3. **S2's binding constraint is the 22-point credit minimum (option stage, so chart checks had all passed).** Fact, high. Sole blocker on 528 candles / 90 episodes / 62 days IS; 534 / 88 / 55 OOS. Largest chart-stage sole blockers: ADX >= 20 (37 / 44 episodes), day range (23 / 20).

4. **Loosening any S2 filter adds losing trades in both windows.** Fact, high (15-75 trades per row). S2 rows, baseline IS 22 trades, 13.6% win vs 54.1% break-even, -270/trade, net -5,937; OOS 15, 20.0% vs 67.1%, -257, -3,849.

   | Experiment | IS trades / win / BE / exp / net | OOS trades / win / BE / exp / net |
   |---|---|---|
   | entry_min_credit_18 | 56 / 14.3 / 63.3 / -318 / -17,786 | 49 / 32.7 / 60.8 / -173 / -8,463 |
   | entry_min_credit_12 | 75 / 16.0 / 65.8 / -289 / -21,686 | 67 / 26.9 / 62.6 / -202 / -13,522 |
   | fid_no_entry_credit_gate | 37 / 16.2 / 57.3 / -271 / -10,036 | 31 / 22.6 / 57.8 / -203 / -6,289 |
   | waive S2 ADX | 31 / 19.4 / 69.7 / -313 / -9,714 | 21 / 23.8 / 58.9 / -220 / -4,623 |
   | waive S2 day range | 27 / 18.5 / 50.9 / -244 / -6,580 | 18 / 16.7 / 64.8 / -245 / -4,408 |
   | waive S2 VIX | 23 / 17.4 / 56.0 / -247 / -5,686 | 21 / 23.8 / 59.2 / -245 / -5,140 |
   | entry_cooldown_15 | 23 / 17.4 / 62.4 / -277 / -6,378 | 19 / 15.8 / 63.8 / -253 / -4,802 |

   Win rate never comes within 25 points of break-even.

5. **B1: 89-91% of "pattern candles" are candles where the pullback did not occur.** Fact, high. The touch check fails on 1971 of 2218 (IS) and 2283 of 2499 (OOS). Only 247 / 216 candles have a real touch (75 / 76 days); 18 / 11 pass everything. Among touch candles the failures are: stop size 140 / 136, volume 107 / 111, levels inside T1 88 / 85, ADX 87 / 90, day range 65 / 45. Only 58 / 57 touch candles fail exactly one check, so no single filter is binding.

6. **The stop cap fails mechanically whenever ATR > 20.** Fact, high. `S = max(distance to invalidation, ATR)` (setups.py:122). ATR on buy pattern candles: median 22.9-23.3 (B1), 28.2-28.5 (B2), 21.8-22.0 (B3). ATR > 20 on 65.3% (IS) and 65.9% (OOS) of buy pattern candles, and explains 1563 of 1610 (IS) and 1798 of 1921 (OOS) stop-size failures. ATR < 10 is 0% / 1.7%, so the floor is irrelevant.

7. **Raising the stop cap adds trades that lose.** Fact, medium (15-17 trades).
   - B1, s_max 25/30/40: IS 16-17 trades, win 37.5-41.2% vs break-even 77-79%, -239 to -255/trade (baseline -337), net -4,062 to -4,085 (baseline -3,709). OOS 15-16 trades, win 56-62% vs break-even 76-78%, -156 to -186/trade (baseline +118), net -2,492 to -2,970 (baseline +1,185).
   - B3 (sole blocker 8 / 30 episodes): s_max_40 gives IS 3 trades, 0 wins; OOS 11 trades, 27.3% vs 35.5%, -190. s_max_30 OOS +1,396 is 3 trades: insufficient sample.

8. **Other B1 loosenings do not help in both windows.** Fact for the numbers, medium; incremental figures are inference, since trade sets shift.
   - Waive volume: IS 15 trades, -260/trade, net -3,907 (4 extra trades cost about 198). OOS 17 trades, +169, net +2,877.
   - Waive levels: IS 14, -321, -4,491. OOS 14, +162, +2,273.
   - Waive ADX: IS 13, -297, -3,859. OOS 16, -181, -2,900.
   - fid_entry_gap_off: IS 17 trades, 41.2% vs 48.9%, -83/trade, net -1,404 (6 extra trades, about +2,305: insufficient sample). OOS B1 unchanged.

9. **S1 and S3 never pass, and forcing them through loses.** Fact, medium. S3 credit is the sole blocker on 94 / 59 candles. diag_s3_chart_open_credit_12: IS 21 trades, 9.5% vs 63.5%, -271; OOS 19, 21.1% vs 66.5%, -257. diag_s1_open_credit_30: 2 trades per window, 0 wins. Waiving any single S1 or S3 chart check adds no trades.

10. **B2 is one candle per day and fails 3.5 checks on average** (stop size 85-90%, volume 81%, levels 67-70%). Fact, high. Near-miss episodes: 4 IS, 0 OOS. No single loosening adds more than one trade.

11. **No filter loosening gives positive expectancy after costs in both windows. None.** Fact, high. Every loosened row is negative in IS. Three raise B1 per-trade expectancy in both (waive volume, waive levels, gap off), but IS stays at -83 to -321.

## Could not determine

- **Signals hidden while a position is open.** The simulator skips evaluation on those candles (backtest.py:476-480), so they are in no funnel count. Evidence it matters: removing the credit gate drops S2 alerts 48 -> 37. Resolving it needs a run that logs those candles.
- **Whether the IS-versus-OOS B1 gap (36% vs 70% win) is regime or noise.** 10-11 trades each; needs more windows.
- **Whether 1.0 point entry slippage on spreads is realistic.** It decides about 26 S2 alerts per window; needs live fill data.
