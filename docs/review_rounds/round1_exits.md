# Exits & Risk, Round 1

Sources: docs/backtest_trades_*.csv ("trades"), docs/backtest_sweeps_*.csv per-setup rows ("sweeps"), scalpbot/backtest.py, scalpbot/setups.py. Rupees are per lot (lot 65). No extra experiments were run. B2 (1 IS trade) and B3 (1 + 1): insufficient sample.

## Findings

1. **No exit or risk rule makes either setup's expectancy positive in both windows.** Best after-T1 variants still leave B1 at -2,092 to -2,931 in IS; S2 is negative in every sweep in both windows. Fact, high.

2. **S2 has no gross edge and costs do the rest: strategy plus cost problem.** Gross before costs: IS -608 (22 trades), OOS -127 (15). Costs: IS 5,329, OOS 3,722. Win % against break-even: IS 13.6 vs 54.1, OOS 20.0 vs 67.1. A spread closed at its entry price loses Rs 242 (4 fills x 0.5 pt x 65 = 130, plus about 112 charges) = 3.7 points, 16% of a 22.7 credit. Fact, high.

3. **S2 index-stop exits were wrong from the start; the stop is not cutting winners.** IS, 14 exits: average best excursion 1.1 pt, average result -5.3 pt (-3.3 before slippage = Rs -215; Rs -456 after all costs; costs are 53% of the loss). OOS, 8 exits: best excursion 0.4, -3.8 pt (-1.8 before slippage; Rs -368 net). Removing it (exit_no_index_stop, S2 row) changes net: IS -5,937 to -4,634, OOS -3,849 to -3,150. But OOS expectancy is slightly worse (-257 to -262; the gain comes from 3 fewer trades) and worst trade roughly doubles (IS -680 to -1,634, OOS -599 to -1,207). Not a robust improvement. Fact, high.

4. **The 50% target is almost never reachable intraday at S2's dte (1-4).** Best excursion as a share of credit: median 0.06 IS, 0.03 OOS; reached 0.5 in 1 of 22 IS and 0 of 15 OOS; reached 0.3 in 3 and 2. Trades held to 15:00 average +1.5 pt IS (Rs -14 after charges) and -0.2 pt OOS (Rs -130). Targets of 0.3/0.7 move S2 by +268/+313 IS and 0/+120 OOS; exit_credit_stop_2.0 changes nothing (the credit stop never fires first). Fact, high.

5. **B1's T1 is not 2 x S in most trades.** setups.py:251-254 caps T1 at the distance to the VWAP 1-SD band. T1 distance in index points: IS 2.5, 3.7, 5.2, 13.7, 18.9 on 5 of 11 trades; OOS 0.2-6.7 on 8 of 10. The "No level inside T1" check and "T1 hit" are therefore measured against a target often smaller than one tick of noise. Fact, high.

6. **B1 payoff: wins capped near 1.5 points, losses 5-13 points: parameter problem.** IS: 3 of 11 reached T1; each kept exactly +1.5 pt (Rs 34-42) after best excursions of 14.2, 9.4 and 9.9, via the entry+2 stop (backtest.py:677-678). Losers: invalidation close 3 at -9.8 pt (Rs -699), time stop 4 at -2.2 (Rs -203), disaster stop 1 (Rs -916). Win 36.4% vs break-even 91.8%. OOS: 8 of 10 reached T1: 5 kept +1.5 pt (Rs 29-40), 2 exited on the 9 EMA trail at a loss (-178, -335), 1 ran to flat-by time (+1,674). Fact, high.

7. **B1's OOS profit is one trade plus a simulation artifact.** Net +1,185; without 2025-12-01 (+1,674) it is -489. When T1 is tiny, the stop moves to entry+2 while the option is below that price, and the next bar fills at entry+2 (backtest.py:660-667); the five OOS exits happened at bar 2-3 after drawdowns of 3.9-6.3 pt. fid_stop_gap_fill (B1 row): OOS 1,185 to 429, win 70% to 40%; IS unchanged. Fact for the numbers; inference (medium) that 429 is nearer the truth.

8. **After-T1 rules: no winner in both windows.** B1 net, IS / OOS: baseline -3,709 / +1,185; exit_at_t1 -2,546 / +208; exit_no_lock -3,658 / +121; exit_lock_be -3,385 / +536; exit_lock_half_t1 -2,931 / +1,103. At 8 lots: lots_8 -3,255 / +1,598; book_half -2,656 / +554; book_half_lock2 -2,682 / +1,086; lots_8_exit_at_t1 -2,092 / +621. Exit-at-T1 is best in IS and loses about 977 in OOS; baseline is best in OOS. Lock-at-half-T1 is the only one near neutral (+778 IS, -82 OOS). Differences rest on 3 and 8 trades. Fact; low confidence in any ranking.

9. **Stops sit inside one normal 5-minute range.** Invalidation is S = 12-20 index points against ATR medians of 22-30; the disaster stop is 10-22 premium points. Wider S hurts: entry_s_max_25 B1 IS -3,709 to -4,085, OOS +1,185 to -2,583 (worst trade -1,563); entry_s_min_5 IS unchanged, OOS +870. exit_stop_1.0/2.0: IS +314/+85, OOS no change (one disaster stop in IS, none OOS). Fact, medium (10-16 trades).

10. **The time stop helps in both windows.** exit_no_time_stop B1: IS -4,692, OOS +497; exit_time_stop_6: -4,576 / +497. IS time-stopped trades had best excursions of 5.3-8.3 pt but averaged -2.2 pt; without the stop they become invalidation closes. Fact, medium.

11. **More lots only dilutes charges.** Points are identical (B1 IS -46.8 at 1, 2, 8, 10 lots). All setups, per lot: IS -10,949 to -8,595 at 8 lots, OOS -3,106 to -1,413; totals for 8 lots are about -68,800 and -11,300. With slippage 0.25 (scn_lots8_slip0.25): IS -9,101 per lot (-72,800 total), OOS -7. Size multiplies a negative result. Fact, high.

12. **Cost drag, B1.** A flat trade loses Rs 126 (65 slippage + 61 charges); cost is 252% of the average win in IS (Rs 50) and 46% in OOS (Rs 278). The entry+2 lock nets about Rs 37. Fact, high.

13. **Drawdown / worst trade (1 lot).** IS: B1 3,295 / -916; S2 5,832 / -680; B3 -939; B2 -364; all 10,844. OOS: B1 386 / -335; S2 3,753 / -599; all 4,184. S2's drawdown equals its whole loss: it never recovered. Fact, high.

## Unknowns
- Whether the entry+2 fills were achievable: check each exit bar's option high in data/cache.
- Whether B1 works with T1 uncapped or with a minimum T1: one run restricted to B1.
- The trades CSV shows B1 deltas of 0.46-0.56 against the 0.60-0.80 rule: check where `_delta` is taken.
- Real slippage on four-leg spreads: live fills needed.
- B1 samples of 10-11 per window cannot rank exit rules.
