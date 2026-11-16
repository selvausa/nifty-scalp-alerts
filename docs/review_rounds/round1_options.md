# Options Structure Analyst - Round 1

IS = 2026-05..10, OOS = 2025-11..2026-04. Per-candle dump from my own offline baseline run (0 missing files, reproduces 22/15 S2 trades): `optstage_is.csv`, `optstage_oos.csv`, `days_*.csv` in this folder.

## Findings

**1. The two credit gates differ; the fill gate is effectively 23.** Fact, high.
Alert: last closes, no slippage, >= 22 (setups.py:334). Fill: next opens minus 1.0 slippage, >= 22 (backtest.py:591-600). Credit-rejected S2 alerts:

| | n | alert | next open | after slippage | rejected by slippage alone (open >= 22) |
|---|---|---|---|---|---|
| IS | 26 | 22.66 | 22.64 | 21.64 | 25 |
| OOS | 27 | 22.52 | 22.49 | 21.49 | 24 |

Drift is -0.02 / -0.03 points, slippage -1.00: slippage is about 98% of the shortfall. Would fill at 21: 25/26 and 24/27; at 20, 18, 15: all. Live has no second gate, but its alert credit is bid minus ask (options.py:92-97), so the fill gate is the closer analogue of live.

**2. The rejected trades lose money in both windows.** Fact, high (per-trade split medium: position blocking shifts alerts).
`fid_no_entry_credit_gate`, S2: IS 37 trades -10,036 vs 22 / -5,937 (15 extra, about -273 each); OOS 31 / -6,289 vs 15 / -3,849 (16 extra, about -153 each). `entry_min_credit_18`: IS 56 / -17,786; OOS 49 / -8,463. Credit 15, 12 and delta 0.20-0.35, 0.25-0.40 are worse still. No variant has positive expectancy.

**3. Credit 22 sits at the top edge of what delta <= 0.30 pays on a 100-wide spread.** Fact, high.
S2 candles passing every chart check (IS 606, OOS 620), credit at the picked strike (median short delta 0.27-0.28):

| dte | IS median / max | IS >= 22 | OOS median / max | OOS >= 22 |
|---|---|---|---|---|
| 0 | 5.9 / 9.5 | 0% | 5.0 / 10.3 | 0% |
| 1 | 15.8 / 23.4 | 2% | 16.9 / 23.4 | 3% |
| 2 | 19.7 / 24.5 | 17% | 18.0 / 26.8 | 6% |
| 3 | 18.6 / 24.2 | 13% | 20.0 / 25.5 | 29% |
| 4 | 20.8 / 25.0 | 30% | 20.1 / 24.6 | 24% |

Every S2 alert had signal credit 22.0-26.75. The usable band is about 22-25 and slippage removes a third of it, which is why half the alerts fail the fill.

**4. S2 cannot trade on expiry day and almost never the day before; no dte is profitable.** Fact, high.
Expiry-day delta 0.10-0.20 pays at most 10.3 (0 of 140 candles reach 22), so "Not expiry day after 12:00" is redundant. Trades pooled over both windows: dte 1: 2, +444 (insufficient); dte 2: 10 trades, 2 wins, -2,661; dte 3: 8, 1 win, -2,707; dte 4: 17, 2 wins, -4,862.

**5. S3 never trades: its credit rule contradicts its delta range.** Fact, high; "bug" is inference, medium.
S3 delta is 0.03-0.20 (options.py:66) with the common 22 minimum (setups.py:470). Over all 153 chart-passing candles, credit median was 11-14, maximum 16.8. Its own note expects "a small credit" (setups.py:474). Classification: spec/code bug. Opening it loses: `diag_s3_chart_open_credit_12` IS 21 trades, 9.5% wins, -5,694; OOS 19, 21%, -4,879.

**6. S3's VIX checks are noisy and collide with its trigger, but do not decide the outcome.** Fact, high. Calibration.
"Higher 5-min highs" compares one VIX candle's high with the previous one (market.py:189-190): true on 37% of all VIX candles, 43-47% of S3 candles. The day-change (vs prior day's last candle, market.py:184-185) is sound, but on S3 candles (range >= expected move) VIX is up over 5% 42% / 37% of the time. `diag_s3_vix_checks_off`: 0 alerts, credit still blocks.

**7. S1 never trades: unreachable credit plus chart checks that exclude each other over time.** Fact, high. Calibration.
S1 runs only at dte <= 1 (setups.py:364) and needs 44. The 5 candles reaching the option stage (all dte 0) paid 6.9-12.2 for both sides; at dte 1, delta 0.20-0.25 pays median 14, max 18.4 per side. `diag_s1_chart_checks_off`: 0 alerts. Chart side: at 10:xx ADX < 20 on 14% / 3% of pattern candles and range-width fails 73% / 44%; by 11:xx-12:xx squeeze fails 51-64%. Among ADX < 20 candles squeeze fails 64% / 68%: a two-hour range is a squeeze. Chart-pass 4 of 179 (IS), 1 of 237 (OOS). With credit 30: 4 trades, all losers (insufficient).

**8. Expected move: live expiry-day figure is about 30% below the backtest's; effect is bounded.** Ratio fact, high; impact inference, medium.
Straddle / 0.8 over the VIX formula at the first candle: median 0.65 IS (25 expiry days), 0.73 OOS (22). S3 is excluded on expiry day, S2 cannot pass credit there, S1 does not use it; only buys are affected, and a smaller figure blocks more. Baseline expiry-day trades: B1 3 (IS, -995), 1 (OOS, +40). Also, the backtest reads VIX from the 09:00 pre-open candle, not "about 09:20" (market.py:192-193); median difference 0.5%.

**9. Weekday dte is off by one on 8 IS and 12 OOS days, without material effect.** Fact, high.
Only 2026-09-11, 2026-01-23 (labelled 2, truly 1) and Sunday 2026-02-01 (labelled 1, truly 2) cross a rule boundary; none had a trade. No expiry day is mislabelled; the 4 Monday expiries count correctly. Trades on mislabelled days: 4 IS, 3 OOS, all S2 at dte 2-4.

**10. Lot 65 and today's charges distort rupees only.** Inference, medium.
Points, win rate, trade selection, credit and delta logic are lot-independent. If the lot was 75 before January 2026 (my recollection, unverified), OOS November-December rupees are understated in size by 15% and flat brokerage per point overstated (94 rupees = 1.45 points at 65, 1.26 at 75). Signs do not change. Expiry was Tuesday throughout.

## Unknowns
- Real bid/ask width on the legs (is 1.0 per spread right?): live quote logs.
- Whether the sheet intended separate S3 / S1 credit minimums: owner or sheet text.
- Holidays after each window's end (5 days' dte unverifiable from cache).
- Lot size and STT by date: exchange circulars.

Note: `scalpbot/review.py` and `.git/index` changed at 16:35 UTC during this round. I did not edit them.
