# Backtest review, 2026-05-01 to 2026-10-31

Two windows were used. **IS** (in-sample) is 2026-05-01 to 2026-10-31, the window under review. **OOS** (out-of-sample) is 2025-11-01 to 2026-04-30, fetched afterwards as a check. All rupee figures are per lot of 65, after 0.5 points of slippage per fill and charges at ₹20 per order, unless stated.

Four specialists (signal funnel, options structure, exits and risk, backtest integrity) ran two rounds; their reports are in `docs/review_rounds/`. The Chair ran the settling experiments. Sweep rows are in `docs/backtest_sweeps_2026-05_2026-10.csv` and `docs/backtest_sweeps_2025-11_2026-04.csv`.

## 1. Bottom line

- **Why trades are few:** the setups rarely occur and several cannot occur as specified. S1 and S3 can never reach their credit minimum, S2 clears it on about one chart-passing candle in eight, and the buy setups fail the 10–20 point stop cap whenever 5-minute ATR is above 20, which is 65% of the time.
- **Why trades lose:** no setup shows an edge before costs. S2 is flat before costs and loses ₹264 a trade after them. B1's target is so far away that 2 of 21 trades ever reached it.
- **No tuning fixes this.** Of 80 experiments, none is profitable in-sample, and every filter loosening adds losing trades.
- **Top 3 actions:** (1) fix three simulator flaws and B1's missing target floor, then freeze a new reference; (2) pause S2, and leave S1 and S3 off; (3) put no money on B1 and do not scale to 8–10 lots; log live bid-ask and test one pre-registered B1 idea on unseen data.
- **After those actions the bot would have traded 8 times in IS (−₹3,440) and 4 times in OOS (+₹46).** The sheet as specified has no demonstrated edge.

## 2. Reconciled numbers

### Counts

| Check | IS | OOS |
| --- | --- | --- |
| Alerts | 67 = 35 traded + 26 credit below minimum at the fill + 6 index moved over 3 points | 54 = 26 traded + 27 credit + 1 index moved |
| Trades by setup | B1 11, B2 1, B3 1, S2 22 = 35 | B1 10, B3 1, S2 15 = 26 |
| Exits | index stop 14, flat-by 7, time stop 5, invalidation 3, stop after T1 3, disaster stop 2, 50% target 1 = 35 | flat-by 8, index stop 8, stop after T1 5, time stop 3, 9 EMA trail 2 = 26 |
| Net ₹ | −3,709 − 364 − 939 − 5,937 = −10,949 | 1,185 − 442 − 3,849 = −3,106 |

The baseline reproduces from the cache alone in the review session. The skeptic recomputed all 61 trades and all 53 credit rejections from the raw candles; every one matched (`docs/review_rounds/round1_skeptic.md`, finding 1).

### Funnel

Pattern candles are candles where a setup's defining condition held. An episode is a run of consecutive pattern candles on one day and side. A sole blocker is the only failing check on a candle; raw counts overlap and are in `docs/backtest_funnel_checks_*.csv`.

| Setup | Window | Pattern candles | Episodes | Failed exactly one check | Passed every check | Alerts | Trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | IS | 2,218 | 249 | 217 | 18 | 17 | 11 |
| B1 | OOS | 2,499 | 258 | 195 | 11 | 10 | 10 |
| B2 | IS | 105 | 105 | 4 | 1 | 1 | 1 |
| B2 | OOS | 112 | 112 | 0 | 1 | 1 | 0 |
| B3 | IS | 69 | 42 | 11 | 1 | 1 | 1 |
| B3 | OOS | 116 | 65 | 44 | 1 | 1 | 1 |
| S1 | IS | 179 | 20 | 43 | 0 | 0 | 0 |
| S1 | OOS | 237 | 19 | 42 | 0 | 0 | 0 |
| S2 | IS | 1,583 | 171 | 1,189 | 76 | 48 | 22 |
| S2 | OOS | 1,673 | 168 | 1,267 | 84 | 42 | 15 |
| S3 | IS | 509 | 38 | 229 | 0 | 0 | 0 |
| S3 | OOS | 495 | 39 | 195 | 0 | 0 | 0 |

Sole-blocker candles (episodes), IS then OOS:

| Setup | Binding constraint | Next largest sole blockers |
| --- | --- | --- |
| B1 | None. The pullback itself is absent on 1,971 of 2,218 and 2,283 of 2,499 pattern candles | Among sole blockers: touch 159 (116) / 138 (98); volume 20 (18) / 17 (16); stop size 15 (14) / 14 (13); ADX 9 (8) / 18 (17) |
| B2 | None. One candidate a day, failing 3.5 checks on average | Stop size, volume, level inside T1, range width: 1 each / 0 |
| B3 | Stop size 9 (8) / 40 (30) | Squeeze range 2 (1) / 0; volume 0 / 2 |
| S1 | None on the chart side; credit at the option stage | ADX 23 (2) / 11 (2); squeeze 4 (2) / 16 (3); range width 8 (3) / 5 (3); credit 4 (2) / 1 (1) |
| S2 | Credit at least 22: 528 (90) / 534 (88). Option stage, so every chart check had passed | Day range 203 (23) / 189 (20); expiry day 182 (19) / 142 (15); ADX 144 (37) / 226 (44); VIX 95 (13) / 153 (21) |
| S3 | Credit at least 22: 94 (42) / 59 (36) | VIX up 5% 39 / 37; VIX higher highs 37 / 36; 15-minute inside bar 32 / 41 |

Where alerts are lost after the checks:

- **Passed to alert:** 29 (IS) and 43 (OOS) passing candles were repeats inside the 30-minute cooldown; 28 and 42 of them were S2.
- **Alert to trade, S2:** 26 of 48 and 27 of 42 alerts failed the credit minimum at the fill. Their credit at the next open was still 22 or more in 25 of 26 and 24 of 27 cases; they failed only after the 1.0 point of slippage on two legs (`docs/backtest_untraded_*.csv`).
- **Alert to trade, buys:** 6 B1 alerts (IS) and 1 B2 alert (OOS) were skipped because the index moved more than 3 points before the fill.
- **Not counted anywhere:** candles while a position is open are not evaluated (`scalpbot/backtest.py:476-480`). The funnel analyst estimates this hides 3–16 S2 repeats in IS and 2–10 in OOS, and 0 and 2 B1 alerts.

75 of 123 IS days and 87 of 121 OOS days had no alert at all.

### Costs

| Setup | Window | Trades | Gross before costs | Slippage | Charges | Net | Cost per trade | Average win |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | IS | 11 | −₹2,325 | ₹715 | ₹670 | −₹3,709 | ₹126 | ₹50 |
| B1 | OOS | 10 | +₹2,457 | ₹650 | ₹622 | +₹1,185 | ₹127 | ₹278 |
| S2 | IS | 22 | −₹608 | ₹2,860 | ₹2,469 | −₹5,937 | ₹242 | ₹306 |
| S2 | OOS | 15 | −₹127 | ₹1,950 | ₹1,772 | −₹3,849 | ₹248 | ₹179 |
| All | IS | 35 | −₹3,981 | ₹3,705 | ₹3,263 | −₹10,949 | ₹199 | ₹160 |
| All | OOS | 26 | +₹2,008 | ₹2,665 | ₹2,450 | −₹3,106 | ₹197 | ₹248 |

A spread closed at its entry price loses ₹242: 16% of a 22.7-point credit. A buy closed flat loses ₹126. Costs are 64% of the IS loss and more than the whole OOS loss.

## 3. Setup-by-setup diagnosis

| Setup | IS result | OOS result | Classification |
| --- | --- | --- | --- |
| B1 | 11 trades, 36% wins vs 92% break-even, −₹337 a trade | 10 trades, 70% vs 48%, +₹118 a trade | Strategy problem (stop and target geometry), plus a live-rule defect and a simulation artifact that created the OOS profit |
| B2 | 1 trade | 0 trades | Insufficient sample |
| B3 | 1 trade | 1 trade | Insufficient sample |
| S1 | 0 trades | 0 trades | Calibration problem in the sheet: credit of 44 unreachable |
| S2 | 22 trades, 14% vs 54%, −₹270 a trade | 15 trades, 20% vs 67%, −₹257 a trade | Strategy and cost problem: no edge before costs, certain costs after |
| S3 | 0 trades | 0 trades | Calibration problem in the sheet: credit of 22 unreachable at delta 0.20 or less |

### B1

- **The target has no floor.** T1 is 2 × S capped at the VWAP +1 SD band (`scalpbot/setups.py:124`, `:251-254`). 11 of 21 trades had a target under 7 index points, as low as 0.2. The cheat sheet's own common rules give T1 as 20–40 points and say the minimum target is 20 (sheet section 3).
- **A tiny target "hits" on the entry candle.** That switches off the time stop and invalidation exit and moves the stop to entry + 2 (`scalpbot/backtest.py:678`). The stop is then often above the market and still fills at entry + 2 (`:660-667`). In 4 of 5 OOS "stop after T1" exits the candle opened below the stop.
- **This created the OOS profit.** The 8 OOS trades with a target under 20 sum to +₹1,337; the 2 with a real target sum to −₹152. Filling gapped stops at the open alone takes OOS B1 from +₹1,185 to +₹429.
- **With a real target, B1 does not reach it.** Target always 2 × S: IS 9 trades, 1 reached T1, −₹3,066; OOS 7 trades, 0 reached T1, −₹451. Skipping targets under 20: IS 6 trades, −₹2,137; OOS 2 trades, −₹152.
- **Geometry.** The full target is a median 17.6 (IS) and 18.2 (OOS) premium points; the median best excursion is 6.1 and 5.7. The invalidation level sits 12–20 index points away, inside one 5-minute ATR of 22–30. A 2:1 payoff needs about 42% winners after costs; 2 of 21 trades reached the full target.
- **What the data supports:** no evidence of profit. Pooled with a real target floor it is 8 trades, mean −₹286, 95% interval about −₹620 to +₹48: too few to call a loss.

### S2

- **No edge before costs:** gross −₹608 on 22 trades and −₹127 on 15.
- **Negative after costs beyond doubt:** pooled 37 trades, mean −₹264, 95% interval −₹354 to −₹170. Negative in all 31 S2 variants in both windows, at slippage 0.1, and at zero.
- **Index-stop exits were wrong from the start.** 14 IS exits had an average best excursion of 1.1 points and an average result of −5.3 points; costs are 53% of that loss.
- **The 50% target is not reachable intraday.** Best excursion as a share of credit: median 0.06 (IS) and 0.03 (OOS). It reached 0.5 once in 37 trades.
- **The credit rule sits at the edge of what the delta rule pays.** On chart-passing candles the picked spread paid a median of 16–21 points at 1–4 days to expiry; 22 was reached on 2–30% of them, and never on expiry day (maximum 10.3). Every alert had a credit of 22.0–26.75.
- **No days-to-expiry bucket is profitable:** 2 days, 10 trades, −₹2,661; 3 days, 8 trades, −₹2,707; 4 days, 17 trades, −₹4,862.

### S1 and S3

- **S3:** short delta 0.20 or less (`scalpbot/options.py:64-65`) with a 22 minimum (`scalpbot/setups.py:470`). Over 153 chart-passing candles the credit was a median of 11–14 and never above 16.8. The code follows the sheet; the sheet's own example credit of 22 cannot occur at its delta limit. Lowering the minimum to 12 produced 21 and 19 trades that lost ₹5,694 and ₹4,879.
- **S3's VIX check is noisy.** "Not making higher 5-minute highs" compares one candle with the previous one (`scalpbot/market.py:190`) and is true on 37% of all VIX candles. Removing both VIX checks still produced 0 alerts, because credit blocks.
- **S1:** runs only at 0–1 days to expiry (`scalpbot/setups.py:364`) and needs 44. The 5 candles that reached the option stage paid 6.9–12.2 in total. Its chart checks also exclude each other over time: early on ADX is above 20, and by late morning a quiet range registers as a squeeze. With every chart check waived there were 0 alerts; at a credit of 30, 2 trades per window, both losers (insufficient sample).

## 4. Debate record

### Agreed by all four specialists

1. The simulator's arithmetic and the baseline numbers are right.
2. S2 has no edge after costs in either window.
3. The fill-time credit rejections are a slippage effect, and the rejected trades lose when let through (15 and 16 extra trades at about −₹273 and −₹153 each).
4. B1's target is degenerate and its OOS profit is an artifact.
5. No filter loosening gives positive expectancy in both windows. Lower credit minimum, wider S2 delta, wider stop cap, lower ADX and shorter cooldown are worse in both.
6. More lots dilute charges only; points are identical at 1, 2, 8 and 10 lots.
7. The same-candle stop-first rule is immaterial: it changed 0 trades in either window.
8. B2, B3 and S1: insufficient sample for any conclusion.

### Contested, and how each was settled

| Point | For | Against | Settled by |
| --- | --- | --- | --- |
| Removing S2's index stop helps in both windows (+₹1,268, +₹698) | Skeptic round 1: one of two rule changes better in both | Exits: OOS expectancy gets worse (−₹257 to −₹262); the gain is 3 fewer trades; worst trade doubles | Not adopted. Moot if S2 is paused |
| Waiving B1's volume or level check raises expectancy in both windows | Funnel round 1 | Exits and skeptic: the OOS gains were measured on targets of 0.2–6.7 points with above-market fills | Withdrawn by the funnel analyst in round 2 |
| The time stop helps in both windows | Exits round 1 | Funnel and skeptic: differences of ₹983 and ₹688 are below the ₹2,000 noise level and rest on 4 and 2 trades | Downgraded to low confidence; no change follows |
| S3's credit rule is a code bug | Options round 1 | Chair: the code matches the sheet | Withdrawn; it is the sheet's inconsistency |
| The futures splice biases results | Skeptic: 9 of 67 IS alerts fall on 6 post-roll days | Options and funnel: OOS shows 1–3 alerts on its post-roll days and no trades | Real flaw, effect at most about ₹719 in IS. Needs one rerun with per-contract history |
| Base-case slippage | Chair: 0.25 | Options: the live rule refuses legs wider than ₹0.15 (`scalpbot/config.py:34`), so about 0.1. Skeptic: unmeasured, so a decision must also hold at 0.5 | Unsettled. Report 0.1 and 0.5 until live bid-ask is logged |
| "B1 loses with a real target" | Chair's settling runs | Skeptic: 8 pooled trades cannot show a loss, only the absence of profit | Wording changed to "no evidence of profit" |
| Whether to remove S2's "not expiry day after 12:00" check | Chair: redundant | Options, funnel, skeptic: it costs nothing and guards against a later lower minimum | Dropped from the options |

### Predictions written before the sweeps

| # | Prediction | IS | OOS | Verdict |
| --- | --- | --- | --- | --- |
| P1 | Booking B1 at T1 gains about ₹2,000 and leaves it negative | +₹1,163, still negative | −₹977 | Refuted in OOS |
| P2 | S2 stays negative at zero slippage | −₹5,250 | −₹1,951 | Confirmed |
| P3 | Removing the fill-time credit gate adds S2 trades at the same expectancy | +15 trades, −₹271 vs −₹270 | +16 trades, −₹203 | Confirmed |
| P4 | Lowering the credit minimum makes net worse | −₹21,093 to −₹26,840 | −₹9,212 to −₹15,657 | Confirmed |
| P5 | Raising the stop cap is the largest increase in buy alerts | +17 | +20 | Confirmed; the added trades lose |
| P6 | The same-candle rule changes at most 5 trades | 0 | 0 | Confirmed |
| P7 | S1 and S3 barely trade with chart checks waived | 0 trades | 0 trades | Confirmed |
| P8 | No single change makes the system profitable | 0 of 80 | Dropping S2: +₹642 | Confirmed in IS; the OOS exception is the B1 artifact |

Of the 59 experiments that change anything, 17 beat the baseline in both windows, 17 are worse in both and 16 flip sign. All 17 "better in both" are cost assumptions or trading less, except the S2 index stop and a 70% credit target. One window's net has a standard error of about ₹2,000, so smaller differences are noise.

## 5. Sensitivity sweeps

One change at a time against the baseline, all setups together. Per-setup rows, exit mixes and worst trades are in the CSV files. Chair runs are in `docs/review_rounds/chair_*_sweeps_*.csv`.

| Change | IS trades | IS win % | IS break-even % | IS ₹/trade | IS net ₹ | IS max DD ₹ | OOS trades | OOS win % | OOS break-even % | OOS ₹/trade | OOS net ₹ | OOS max DD ₹ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Baseline** | | | | | | | | | | | | |
| the cheat sheet's rules as coded | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| **Fidelity** | | | | | | | | | | | | |
| same-candle stop and target: target first (optimistic bound) | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| a stop the candle opened through fills at the open, not the stop price | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 27 | 49 | -149 | -3,862 | 4,609 |
| slippage 0.5 -> 0 per fill | 49 | 29 | 62 | -194 | -9,529 | 9,554 | 40 | 40 | 43 | -18 | -719 | 3,574 |
| slippage 0.5 -> 0.1 per fill (two ticks) | 48 | 25 | 67 | -233 | -11,187 | 11,186 | 40 | 38 | 45 | -40 | -1,602 | 4,204 |
| slippage 0.5 -> 0.25 per fill | 47 | 23 | 71 | -266 | -12,488 | 12,448 | 35 | 37 | 50 | -71 | -2,485 | 4,248 |
| slippage 0.5 -> 1.0 per fill | 22 | 27 | 96 | -421 | -9,258 | 8,405 | 21 | 33 | 75 | -206 | -4,319 | 4,591 |
| credit minimum checked at the alert only, not again at the fill | 49 | 18 | 67 | -308 | -15,083 | 14,978 | 41 | 32 | 54 | -136 | -5,576 | 7,159 |
| do not skip buys when the index moved over 3 points before the fill | 40 | 25 | 47 | -194 | -7,772 | 8,900 | 27 | 37 | 58 | -124 | -3,357 | 4,435 |
| corrected reference: all setups, B1 target floor 20, gapped stops fill at the open | 30 | 17 | 67 | -313 | -9,377 | 9,272 | 18 | 22 | 70 | -247 | -4,443 | 4,193 |
| corrected reference at slippage 0.1 | 43 | 23 | 64 | -230 | -9,907 | 9,906 | 33 | 30 | 48 | -96 | -3,169 | 3,861 |
| **Exits and risk** | | | | | | | | | | | | |
| buys: book everything at T1 instead of stop to entry+2 and trail | 35 | 20 | 57 | -280 | -9,786 | 9,681 | 26 | 38 | 74 | -157 | -4,083 | 4,234 |
| buys: after T1 keep the original stop, trail under the 9 EMA | 35 | 17 | 63 | -311 | -10,897 | 10,792 | 26 | 23 | 43 | -160 | -4,170 | 3,990 |
| buys: after T1 stop to entry + 0 (break-even before costs) | 35 | 17 | 62 | -304 | -10,625 | 10,520 | 26 | 19 | 38 | -144 | -3,755 | 4,444 |
| buys: after T1 stop to entry + 6 | 35 | 20 | 61 | -291 | -10,171 | 10,066 | 26 | 38 | 59 | -123 | -3,188 | 3,726 |
| buys: time stop off | 35 | 20 | 75 | -330 | -11,536 | 11,431 | 26 | 38 | 61 | -141 | -3,655 | 4,103 |
| buys: time stop after 6 candles instead of 3 | 35 | 20 | 74 | -326 | -11,419 | 11,315 | 26 | 38 | 61 | -141 | -3,655 | 4,103 |
| buys: disaster stop 1.5 -> 1.0 x S x delta | 35 | 20 | 72 | -296 | -10,353 | 10,248 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| buys: disaster stop 1.5 -> 2.0 x S x delta | 35 | 20 | 73 | -309 | -10,800 | 10,696 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| spreads: no index stop (credit stop, target and flat-by only) | 34 | 21 | 68 | -285 | -9,681 | 9,576 | 23 | 48 | 64 | -105 | -2,408 | 3,486 |
| spreads: target 50% -> 30% of credit | 35 | 20 | 68 | -305 | -10,682 | 10,591 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| spreads: target 50% -> 70% of credit | 35 | 23 | 73 | -304 | -10,637 | 11,001 | 26 | 38 | 57 | -115 | -2,986 | 4,064 |
| spreads: stop 1.5x -> 2.0x credit | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B1 target always 2 x S (ignore the VWAP +1 SD band cap) | 33 | 18 | 65 | -312 | -10,305 | 10,200 | 23 | 26 | 51 | -206 | -4,742 | 5,440 |
| B1 target 2 x S and sell everything at T1 | 33 | 18 | 55 | -289 | -9,521 | 9,416 | 23 | 26 | 53 | -214 | -4,933 | 5,440 |
| **Position size** | | | | | | | | | | | | |
| 2 lots, one-lot exit rule (cost effect only) | 35 | 23 | 70 | -274 | -9,604 | 9,546 | 26 | 38 | 52 | -82 | -2,139 | 3,429 |
| 8 lots, one-lot exit rule (cost effect only) | 35 | 29 | 72 | -246 | -8,595 | 8,733 | 26 | 38 | 48 | -54 | -1,413 | 2,863 |
| 10 lots, one-lot exit rule (cost effect only) | 35 | 29 | 71 | -244 | -8,528 | 8,679 | 26 | 38 | 48 | -52 | -1,365 | 2,825 |
| 8 lots: sell half at T1, trail the rest under the 9 EMA (the sheet's rule) | 35 | 26 | 60 | -228 | -7,996 | 8,134 | 26 | 23 | 39 | -95 | -2,457 | 2,526 |
| 8 lots: sell half at T1, rest with stop at entry + 2 and the trail | 35 | 29 | 65 | -229 | -8,022 | 8,160 | 26 | 38 | 54 | -74 | -1,925 | 2,623 |
| 8 lots: sell everything at T1 | 35 | 29 | 59 | -212 | -7,432 | 7,569 | 26 | 38 | 60 | -92 | -2,390 | 2,582 |
| **Entry filters** | | | | | | | | | | | | |
| stop size cap s_max 20 -> 25 | 40 | 22 | 68 | -283 | -11,325 | 11,220 | 31 | 39 | 70 | -222 | -6,874 | 7,952 |
| stop size cap s_max 20 -> 30 | 41 | 22 | 68 | -292 | -11,957 | 11,852 | 34 | 41 | 56 | -145 | -4,945 | 5,759 |
| stop size cap s_max 20 -> 40 | 43 | 23 | 70 | -293 | -12,586 | 12,482 | 42 | 36 | 56 | -212 | -8,911 | 9,083 |
| stop size floor s_min 10 -> 5 | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 28 | 36 | 59 | -140 | -3,929 | 5,007 |
| minimum credit 22 -> 18 (alert and fill) | 66 | 17 | 69 | -320 | -21,093 | 20,988 | 56 | 36 | 64 | -165 | -9,212 | 9,848 |
| minimum credit 22 -> 15 (alert and fill) | 77 | 17 | 68 | -296 | -22,755 | 22,650 | 72 | 28 | 64 | -199 | -14,308 | 14,191 |
| minimum credit 22 -> 12 (alert and fill) | 88 | 16 | 69 | -305 | -26,840 | 26,735 | 78 | 28 | 65 | -201 | -15,657 | 15,540 |
| S2 short-strike delta 0.15-0.30 -> 0.20-0.35 | 68 | 21 | 67 | -309 | -21,044 | 20,939 | 59 | 34 | 60 | -161 | -9,480 | 9,707 |
| S2 short-strike delta 0.15-0.30 -> 0.25-0.40 | 76 | 21 | 63 | -311 | -23,607 | 23,502 | 68 | 29 | 56 | -184 | -12,530 | 12,358 |
| ADX trend threshold 20 -> 15 | 44 | 25 | 75 | -303 | -13,331 | 13,226 | 33 | 36 | 63 | -192 | -6,338 | 7,416 |
| ADX trend threshold 20 -> 25 | 26 | 19 | 72 | -343 | -8,924 | 8,799 | 15 | 27 | 71 | -221 | -3,314 | 3,064 |
| no selling when VIX is up more than 5% -> 8% | 35 | 20 | 73 | -312 | -10,910 | 10,805 | 28 | 39 | 59 | -120 | -3,349 | 4,427 |
| B2 opening range at most 0.4 -> 0.6 x expected move | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B3 break volume 1.5 -> 1.2 x the prior-10 average | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 27 | 37 | 60 | -142 | -3,845 | 4,923 |
| S1 opening range at least 4 -> 2 x ATR | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| alert cooldown 30 -> 15 minutes | 36 | 22 | 76 | -316 | -11,391 | 11,286 | 31 | 36 | 59 | -130 | -4,025 | 5,103 |
| B1: skip when the band-capped target is under 20 index points | 30 | 17 | 67 | -313 | -9,377 | 9,272 | 18 | 22 | 70 | -247 | -4,443 | 4,193 |
| **Single checks dropped** | | | | | | | | | | | | |
| B1: drop the check 'Volume at least the prior candle's' | 39 | 20 | 65 | -286 | -11,147 | 11,042 | 33 | 39 | 44 | -43 | -1,414 | 4,159 |
| B1: drop the check 'No PDH/PDL or 100-strike inside T1' | 38 | 21 | 72 | -309 | -11,730 | 11,626 | 30 | 40 | 50 | -67 | -2,018 | 2,599 |
| B1: drop the check 'ADX(14) is 20 or more' | 37 | 22 | 74 | -300 | -11,099 | 10,994 | 32 | 34 | 67 | -225 | -7,191 | 8,269 |
| B1: drop the check 'Day range under 100%' | 36 | 19 | 73 | -309 | -11,133 | 11,028 | 27 | 37 | 58 | -125 | -3,373 | 4,451 |
| B2: drop the check 'Break volume at least the opening-range average' | 36 | 19 | 73 | -311 | -11,190 | 11,085 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B2: drop the check 'No PDH/PDL or 100-strike inside T1' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B2: drop the check 'Range width at most 0.4' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B2: drop the check 'Option 5-min close above' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B3: drop the check 'Break volume at least 1.5' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 27 | 37 | 60 | -142 | -3,845 | 4,923 |
| B3: drop the check 'Close outside the band' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| B3: drop the check 'Option 5-min close above' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 27 | 37 | 58 | -128 | -3,463 | 4,541 |
| S1: drop the check 'ADX(14) below 20' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S1: drop the check 'Opening range at least 4' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S1: drop the check 'No gap open' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S1: drop the check 'No squeeze' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S2: drop the check 'Day range under 100%' | 40 | 22 | 66 | -290 | -11,593 | 11,734 | 29 | 34 | 57 | -126 | -3,665 | 4,743 |
| S2: drop the check 'India VIX not up' | 36 | 22 | 72 | -297 | -10,698 | 10,594 | 32 | 38 | 58 | -137 | -4,398 | 5,054 |
| S2: drop the check 'Not expiry day after 12:00' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S2: drop the check 'ADX(14) is 20 or more' | 44 | 23 | 78 | -335 | -14,726 | 14,621 | 32 | 38 | 57 | -121 | -3,881 | 4,959 |
| S2: drop the check 'Short strike at least 2 x ATR' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S3: drop the check 'India VIX not making higher' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S3: drop the check 'India VIX not up' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S3: drop the check 'Last 15-min candle' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S3: drop the check 'Day extreme not exceeded' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| S3: drop the check 'Not closing beyond' | 35 | 20 | 73 | -313 | -10,949 | 10,844 | 26 | 38 | 58 | -119 | -3,106 | 4,184 |
| **S1 and S3 diagnostics** | | | | | | | | | | | | |
| S1: waive ADX, range width, gap and squeeze (chart side fully open) | 0 alerts, 0 trades | – | – | – | – | – | 0 alerts, 0 trades | – | – | – | – | – |
| S1: chart side open and condor credit 44 -> 30 | 2 | 0 | 100 | -693 | -1,386 | 587 | 2 | 0 | 100 | -479 | -958 | 495 |
| S3: waive both VIX checks | 0 alerts, 0 trades | – | – | – | – | – | 0 alerts, 0 trades | – | – | – | – | – |
| S3: VIX checks off and credit 22 -> 12 | 21 | 10 | 64 | -271 | -5,694 | 5,555 | 19 | 21 | 66 | -257 | -4,879 | 4,775 |
| **Setups dropped** | | | | | | | | | | | | |
| run B1, B2, B3 only | 13 | 31 | 92 | -386 | -5,013 | 4,599 | 13 | 62 | 55 | 49 | 642 | 1,569 |
| run S1, S2, S3 only | 22 | 14 | 54 | -270 | -5,937 | 5,832 | 15 | 20 | 67 | -257 | -3,849 | 3,753 |
| run B1 only | 11 | 36 | 92 | -337 | -3,709 | 3,295 | 12 | 67 | 54 | 90 | 1,084 | 1,127 |
| run S2 only | 22 | 14 | 54 | -270 | -5,937 | 5,832 | 15 | 20 | 67 | -257 | -3,849 | 3,753 |
| after the recommendations: buys only (S1, S2, S3 paused), B1 target floor 20, gapped stops at the open, 1 lot, slippage 0.5 | 8 | 25 | 91 | -430 | -3,440 | 3,026 | 4 | 50 | 48 | 12 | 46 | 442 |
| same, slippage 0.1 | 8 | 25 | 85 | -385 | -3,076 | 2,714 | 4 | 50 | 41 | 64 | 254 | 390 |
| **Scenarios (several changes at once)** | | | | | | | | | | | | |
| 8 lots and slippage 0.25 | 47 | 28 | 63 | -194 | -9,101 | 9,144 | 35 | 43 | 43 | 0 | -7 | 2,542 |
| 8 lots and slippage 0.1 | 48 | 27 | 56 | -161 | -7,717 | 7,804 | 40 | 40 | 34 | 32 | 1,289 | 2,389 |
| 8 lots, slippage 0.25, sell half at T1 and trail the rest | 47 | 26 | 58 | -190 | -8,951 | 8,994 | 35 | 31 | 39 | -37 | -1,305 | 2,339 |
| 8 lots, slippage 0.25, sell everything at T1 | 47 | 28 | 60 | -186 | -8,722 | 8,764 | 35 | 43 | 51 | -31 | -1,096 | 2,124 |

## 6. Ranked options

The skeptic's verdict is recorded for each. No parameter change is recommended for adoption: the options are fixes, pauses and tests.

| # | Category | Change | Hypothesis | Measured effect | Backfire risk | Out-of-sample requirement | Effort | Skeptic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | fidelity | Simulator: fill a stop at the candle's open when it opened through the stop (`backtest.py:660-667`); fill close-triggered exits at the next open (`:684`, `:694`); build each day's history from the current futures contract instead of splicing (`:158`). Then rerun and freeze a new reference | The baseline flatters buys and reads false jumps on roll days | Gap fill: IS unchanged, OOS −₹756. Next-open exits: −₹276 IS, −₹361 OOS (skeptic's repricing). Splice: at most about ₹719 IS, not yet run | None for results; the splice fix needs one Groww fetch of next-month contracts | None: these are corrections | 1 day | Sign off |
| 2 | drop-setup | Pause S2 alerts | S2 has no edge before costs and pays ₹242 a trade in costs | Removes −₹5,937 (IS) and −₹3,849 (OOS); 22 and 15 fewer trades | Forgoes S2 if live costs prove far lower | To reverse: measured live slippage of 0.1 or less and a pre-registered S2 rule with a 95% lower bound above zero on 30 or more unseen trades | Small: a per-setup switch | Sign off |
| 3 | entry-filter | B1: skip the alert when the band-capped target is under 20 index points (`setups.py:124`) | The sheet's minimum target is 20; a 0.2-point target is not a trade | B1 IS −₹3,709 to −₹2,137 (6 trades); OOS +₹1,185 to −₹152 (2 trades) | B1 falls to about 8 trades a year | None: conformance to the sheet, not a measured improvement | Small | Sign off as conformance only |
| 4 | drop-setup | Leave S1 and S3 off; do not lower their credit minimums | Their credit rule cannot be met at their delta ranges | S3 at a minimum of 12: 21 trades −₹5,694 (IS), 19 trades −₹4,879 (OOS). S1: 0 alerts with chart checks waived | None; they never trade today | The sheet's author would need to restate the rule | None | Sign off; "S1 loses" dropped as 4 trades |
| 5 | exit-risk | Do not scale to 8–10 lots | Lots dilute flat brokerage; they do not change points | 8 lots: IS −₹8,595 per lot (about −₹68,800 in total); OOS −₹1,413 per lot | None | Revisit only after a setup shows positive expectancy | None | Sign off |
| 6 | fidelity | Log bid, ask and last price of every alert leg at the alert and one candle later, including paused setups as paper alerts | Slippage is assumed, and it decides about 26 S2 alerts a window | Not measurable from history. Same trades repriced: IS −₹7,984 at 0.1, −₹10,949 at 0.5; OOS −₹975 and −₹3,106 | None | 30 or more logged alerts before choosing a base case | Small | Sign off logging; dissent on 0.25 as base: report 0.1 and 0.5 |
| 7 | drop-setup | B1, B2, B3: alerts stay on as paper trades, no money | With S2 paused and the B1 floor, the bot trades about 11 times in 246 days | After options 1–4: IS 8 trades −₹3,440; OOS 4 trades +₹46 | A real edge would be missed for the paper period | Stated in advance: review after 6 months of paper alerts or 30 trades pooled with unseen backtest windows, whichever is first | None | Sign off, amended to a time limit |
| 8 | entry-filter | Make no filter looser | Every loosening adds losing trades | Stop cap 25/30/40: IS −₹11,325 to −₹12,586; credit 18/15/12: IS −₹21,093 to −₹26,840, OOS −₹9,212 to −₹15,657 | None | — | None | Sign off |
| 9 | exit-risk | Adopt no exit change now | No exit rule is better in both windows by more than noise | Sell at T1: IS +₹1,163, OOS −₹977. No index stop: +₹1,268, +₹698 with the worst trade doubled | None | — | None | Sign off |
| 10 | exit-risk | Test, do not adopt: B1 target of 0.5 × S × delta premium points, sell all | The pullback pays a small bounce, not a trend leg | Hand calculation from best excursions: IS about −₹240, OOS about +₹1,135. Fitted in hindsight on spent data | Wins of 4.5 points against losses of 5–13 need over 73% winners | 30 or more trades on unseen windows, win rate above 75%, stated before the run | 1 day plus a fetch | Deferred: high overfitting risk if run on these windows |
| 11 | fidelity | Simulator: evaluate and log setups while a position is open; give the simulated chain a bid and ask of last ∓ slippage so the alert credit matches live | Completes the funnel; removes the 53 alerts that pass at the alert and fail at the fill | Not run | Trade sets shift slightly through the cooldown | S2 trade count stays within a few of 22 and 15 | Half a day | Not reviewed individually |

## 7. Validation plan

1. **Both windows are spent for tuning.** 81 experiments ran on each. Nothing chosen from them counts as validated.
2. **Order of work:**
   1. Apply option 1 and option 3, rerun both windows, and publish the result as the frozen reference. Change no parameter.
   2. Turn on bid-ask logging (option 6) in the live bot and run all six setups as paper alerts.
   3. Fetch unseen windows. 2025-05 to 2025-10 is the nearest; earlier windows may have a different lot size and expiry weekday, so check the expiry list first and report points as well as rupees.
   4. Run exactly one pre-registered test (option 10) on the pooled unseen windows.
3. **Rules for any future change:**
   - State the hypothesis, the metric and the pass threshold before the run.
   - One parameter at a time.
   - At least 30 trades for the setup, pooling unseen windows if one is too short.
   - The result must hold at slippage 0.1 and at 0.5.
   - The 95% lower bound of expectancy per trade must be above zero.
   - Differences under about ₹2,000 per six-month window are noise.
4. **Before any money:** a setup must pass the rules above and then match its backtest over at least 30 paper alerts with logged bid-ask.

## 8. Open questions

1. **May I change the live alert code for options 2 and 3?** The review left it untouched as instructed. Option 3 is a defect fix. Option 2 needs a per-setup on/off switch.
2. **May I ask you to fetch more history?** The futures-splice fix needs next-month contract candles, and the unseen windows need a full fetch. Each is roughly the size of the earlier 25-minute run.
3. **Do you want the bot to keep running as paper alerts** with bid-ask logging, or stay off until the reference is rebuilt?
4. **S1 and S3:** the sheet's credit minimums cannot be met at its delta limits. Do you want to restate those rules, or leave both setups off?
5. **Is the goal still this cheat sheet?** The review found no edge in it. The alternative is to use the tooling built here to test a different, simpler rule set from scratch, pre-registered.

## 9. Success criteria

| Criterion | Status |
| --- | --- |
| Counts reconcile: 67 alerts, 35 trades, 26 credit-rejected, 6 moved too far, exits and per-setup totals | Met (section 2) |
| Block counts reported as sole-blocker and near-miss counts | Met (section 2) |
| Every ranked option has a sweep or experiment behind it | Met for 9 of 11. The futures-splice part of option 1 has a measured bound, not a run; option 11 is not run |
| No conclusion rests on the single B2 or B3 trades | Met |
| A fidelity fix is ranked ahead of parameter tuning | Met (option 1) |
| Skeptic signed off or dissented on each of the top 5 | Met: sign-off on all five, with option 3 limited to conformance |
