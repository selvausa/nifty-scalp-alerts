# Backtest review, 2026-05-01 to 2026-10-31

**Status: Part 1 of 2. Code and console evidence only. No experiment has run yet.**

The trade CSV and `data/cache` are on the machine that ran the backtest, and the review
session could not reach them or Groww. This part records what the code and the console
output already prove, and the predictions the team commits to before seeing any sweep
result. Part 2 (funnel tables, sweep table, debate record, ranked options) needs the
files produced by `python -m scalpbot.review 2026-05-01 2026-10-31`; see "Next step".

Nothing below marked *inference* or *prediction* has been tested.

## 1. Bottom line so far

- **Why trades lose:** costs. Slippage and charges are about 64% of the ₹10,949 loss. For S2 they are about 90%.
- **Why B1 loses:** no B1 trade kept a T1 profit. At least 3 of its 4 wins are trades that reached T1 and were then stopped at entry + 2, worth about ₹37 each.
- **Why trades are few (S2):** 528 candles passed every chart check and failed only at the option stage, on the 22-point credit minimum. That minimum is then applied a second time at the fill, after slippage, where it rejects 26 of 48 alerts.
- **Why trades are few (buys):** *inference* that the 10–20 point stop cap is binding, because 5-minute ATR sits above 20. The console's overlapping counts cannot confirm it.
- **S1 and S3:** *inference* that their rules cannot all hold at once on current option prices. A calibration problem, not a bug found so far.

## 2. Reconciled numbers

All from the console output.

| Check | Sum | Result |
| --- | --- | --- |
| Alerts | 35 traded + 26 credit-rejected + 6 index-moved = 67 | reconciles |
| Trades by setup | 11 + 1 + 1 + 22 = 35 | reconciles |
| Exits | 14 + 7 + 5 + 3 + 3 + 2 + 1 = 35 | reconciles |
| Net ₹ | −3,709 − 364 − 939 − 5,937 = −10,949 | reconciles |
| Net points | −47 − 5 − 14 − 53 = −119 vs −118 printed | rounding |
| Alerts by side | buys 13 traded + 6 index-moved = 19; spreads 22 traded + 26 credit-rejected = 48 | 19 + 48 = 67 |

The last row assumes all 26 credit rejections are S2. S1 and S3 fired no alerts, and only spreads have a credit, so nothing else can produce them.

### Cost breakdown

Net points in the console are after slippage and before charges (`scalpbot/backtest.py:597-608`). Slippage is 0.5 points on each fill: 2 fills for a buy, 4 for a spread. Charges are net ₹ minus points × 65.

| Setup | Trades | Gross before costs | Slippage | Charges | Net | Costs as share of loss |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | 11 | −36 pts = −₹2,340 | 11 pts = ₹715 | ₹654 | −₹3,709 | 37% |
| S2 | 22 | −9 pts = −₹585 | 44 pts = ₹2,860 | ₹2,492 | −₹5,937 | 90% |
| All | 35 | −61 pts = −₹3,965 | 57 pts = ₹3,705 | ₹3,279 | −₹10,949 | 64% |

B2 and B3 are one trade each and are included only in "All".

| Setup | Cost per trade | Average win | Cost as share of average win |
| --- | --- | --- | --- |
| B1 | ₹124 (₹65 slippage + ₹59 charges) | ₹50 | 250% |
| S2 | ₹243 (₹130 slippage + ₹113 charges) | ₹306 | 79% |

An S2 trade that exits at exactly the price it entered loses ₹243. S2's average loss is ₹361, so about two-thirds of an average S2 loss is cost.

## 3. What the code establishes

### Setup map

Parameters are in `scalpbot/config.py:26-45`. All line numbers are on the `claude/backtest-review` branch.

| Setup | Defining condition (skipped silently if false) | Checks | Strike | Exits |
| --- | --- | --- | --- | --- |
| B1 VWAP pullback | 15-min bias UP or DOWN, 10:15–11:30 or 13:15–14:45 (`setups.py:231-238`) | touch of VWAP or 20 EMA and close beyond 9 EMA; volume ≥ prior candle; ADX ≥ 20 (`:244-249`); common buy checks | delta 0.45–0.55, or 0.50–0.65 at 1 day, 0.60–0.80 on expiry day (`options.py:54`) | buy exits |
| B2 opening-range breakout | first close outside the 09:15–09:45 range, 09:45–11:30 (`:258-270`) | outer half; volume ≥ range average; width ≤ 0.4 × expected move; no event; no gap beyond PDH/PDL (`:273-279`); common buy checks; option close above its prior 3 highs | as B1 | buy exits |
| B3 squeeze release | close outside the Bollinger band with band width at its session low within 6 candles, 13:15–14:45 (`:289-297`) | beyond squeeze range; volume ≥ 1.5 × prior-10 average; VIX not falling sharply (`:301-305`); common buy checks; option breakout | as B1 | buy exits |
| S1 iron condor | 0 or 1 days to expiry, price inside the opening range since 09:45, bias NEUTRAL, 10:15–13:00 (`:363-376`) | ADX < 20 and not rising; range ≥ 4 × ATR; no squeeze; no gap (`:379-384`); sell checks; credit ≥ 44 | short delta 0.15–0.25, or 0.10–0.20 on expiry day (`options.py:63`) | spread exits, range stop |
| S2 trend credit spread | bias UP or DOWN, 11:30–13:30 (`:406`) | close beyond VWAP; ADX ≥ 20; day range < expected move; not expiry day after 12:00 (`:413-417`); sell checks; short strike ≥ 2 × ATR from spot; credit ≥ 22 | short delta 0.15–0.30, nearest the money past VWAP and the swing low (`options.py:122`) | spread exits, VWAP stop |
| S3 exhaustion fade | day range ≥ expected move, at least 1 day to expiry, 11:00–13:30 (`:443-446`) | extreme held 3 candles; 15-min inside bar; VIX not making higher highs; not beyond the band with VIX rising (`:456-460`); sell checks; credit ≥ 22 | short delta ≤ 0.20 beyond the day extreme | spread exits, extreme stop |

- **Common buy checks** (`setups.py:118-143`): stop size S = max(distance to invalidation, ATR) must be 10–20; T1 = 2 × S; no PDH, PDL or 100-strike inside T1; day range under the expected move in the trade's direction; no event block.
- **Sell checks** (`setups.py:311-317`): VIX not up more than 5% on the day; not an event day; before 13:30.
- **Buy exits** (`backtest.py:624-659`): disaster stop at 1.5 × S × delta below entry; at T1 the stop moves to entry + 2 and the trade trails under the 9 EMA; invalidation close; time stop after 3 candles under +0.5 S; flat by 15:00.
- **Spread exits** (`backtest.py:661-687`): stop at 1.5 × credit; the setup's index stop; target at 50% of credit; flat by 15:00.

### Findings from code

1. **The console lists only the top four blockers per setup** (`backtest.py:742`). Every failing check is recorded; the report truncates. Sole-blocker counts need the new instrumentation.
2. **Checks run in two stages.** Option checks run only when every chart check has passed (`setups.py:187`, `:387`, `:421`, `:464`). So "Credit at least 22 points (528)" on S2 means 528 candles passed the whole chart side. Chart-stage counts overlap; option-stage counts do not overlap with chart-stage ones.
3. **The credit minimum is one number applied twice, under different conditions.**
   - At the alert: last traded prices at the signal candle's close, no slippage (`setups.py:334`, `options.py:93`).
   - At the fill: the next candle's open, minus 0.5 on each of two legs (`backtest.py:568-576`).
   - So an alert needs 23 points of raw credit at the next open to survive. Alerts cluster just above 22 by selection, which is why 26 of 48 fail. This is a simulation artifact stacked on a real constraint.
4. **The same-candle stop-first rule cannot explain the 14 index stops.** Spread exits are judged on candle closes only (`backtest.py:661`). The rule applies only to the buys' intrabar stops: the 2 disaster stops and the 3 stops after T1 (`backtest.py:630-633`).
5. **Stops fill at the stop price even when the candle opened through it** (`backtest.py:633-637`). That is optimistic for buys. The size is unknown; `fid_stop_gap_fill` measures it.
6. **T1 is detected on the futures high or low, not on a close** (`backtest.py:628`). A wick can mark T1 as reached, move the stop to entry + 2, and the option can already be below that level on the next candle. *Inference*: this contributes to the "stop after T1" exits.
7. **"VIX not making higher 5-min highs" is one candle against the previous one** (`market.py:190`). A single uptick blocks S3. It blocked 217 of 509 S3 candles.
8. **Expected move uses the first futures candle and first VIX candle of the day** (`market.py:193`), every day including expiry day in the backtest.

## 4. Predictions recorded before any sweep

Written down first so the sweeps test them, instead of the team explaining whatever the sweeps show.

| # | Prediction | Basis | Sweep that tests it |
| --- | --- | --- | --- |
| P1 | Booking B1 at T1 improves B1 by about ₹2,000 but leaves it negative | 3 trades reached T1 and kept ₹37 each; T1 is worth about S − 1 points | `exit_at_t1`, `exit_no_lock`, `exit_lock_be` |
| P2 | S2 stays negative at zero slippage, by roughly its ₹2,492 of charges plus ₹585 | cost table | `fid_slip_0` |
| P3 | Removing the fill-time credit gate adds up to 26 S2 trades with the same negative expectancy | they are the same alerts, a point or two lower in credit | `fid_no_entry_credit_gate` |
| P4 | Lowering the credit minimum adds many S2 trades and makes net ₹ worse | fixed ₹243 cost against a smaller credit | `entry_min_credit_18`, `_15`, `_12` |
| P5 | Raising the stop cap is the largest single increase in buy alerts | 5-minute ATR above 20 on most pattern candles | `entry_s_max_25`, `_30`, `_40` |
| P6 | The optimistic same-candle rule changes at most 5 trades | only 5 intrabar stop exits exist | `fid_target_first` |
| P7 | S1 and S3 produce few or no trades even with every chart check waived | credit minimum against low-delta shorts | `diag_s1_*`, `diag_s3_*` |
| P8 | No single change makes the whole system profitable after costs | costs are 64% of the loss and no setup beats break-even | all |

## 5. Debate record

Not started. Round 1 needs the trade rows and the funnel tables. Running the specialists on the console output alone would produce opinions without evidence, which the brief rules out.

Questions the first data will settle:

- Which checks are sole blockers for B1, B2, B3, S1 and S3.
- The ATR distribution on buy pattern candles, and so whether the stop cap or the pattern itself limits buys.
- S2 results split by days to expiry.
- For each of the 26 credit rejections: credit at the alert, at the open, and after slippage.
- For the 5 intrabar stop exits: whether stop and target shared a candle, and whether the candle opened through the stop.

## 6. Tooling added on `claude/backtest-review`

The live alert code is unchanged: `git diff claude/scalp-alert-bot` is empty for `setups.py`, `runner.py`, `market.py`, `options.py`, `config.py`, `groww.py`, `state.py` and `telegram.py`. Default backtest results are identical before and after on synthetic data.

| Piece | What it does |
| --- | --- |
| `python -m scalpbot.review START END` | Runs the baseline with diagnostics, then 70 experiments in parallel from the cache |
| `experiments/sweeps_<range>.json` | The exact overrides of every experiment, written on first run and reused after |
| `docs/backtest_funnel_setups_*.csv` | Per setup: pattern candles, distinct episodes, near misses, passed, alerts, trades, ATR |
| `docs/backtest_funnel_checks_*.csv` | Per check: raw blocks, sole-blocker candles, episodes and days, chart or option stage |
| `docs/backtest_trades_*.csv` | Each trade with days to expiry, candles held, fills, slippage, charges, best and worst excursion, S, T1, delta |
| `docs/backtest_untraded_*.csv` | Each untraded alert with its credit at the alert, at the open and after slippage, or its entry gap |
| `docs/backtest_costs_*.csv` | Gross, slippage, charges and net per setup |
| `docs/backtest_sweeps_*.csv` | One row per experiment and setup: trades, win %, break-even win %, expectancy per trade, net ₹, drawdown, exits |
| `backtest --offline` | Runs from `data/cache` alone, with no Groww login |

The 70 experiments: 7 fidelity, 12 exit and risk, 41 entry filters (16 parameter changes and 25 single-check waivers), 4 diagnostics for S1 and S3, 5 setup subsets, and the baseline.

## 7. Next step

On the machine that has `data/cache`:

```bash
git fetch
git checkout claude/backtest-review
python -m scalpbot.review 2026-05-01 2026-10-31
git add docs experiments
git add -f data/cache data/backtest_2026-05-01_2026-10-31.csv
git commit -m "Backtest review data"
git push
```

The review command makes a few dozen Groww requests on its baseline run, to store the contract lists and the current month's expiries for offline use. The sweeps then run from the cache. Expect about 15 minutes.

Pushing `data/cache` (market candles only; `.env` is not included) lets the team rerun experiments in the review session. Without it, only the fixed set of 70 can be analysed.

## 8. Owner's answers and what they imply

| Question | Answer | Effect on the review |
| --- | --- | --- |
| Slippage | 0.5 is not fixed; use an industry-standard figure | Sweeps cover 0, 0.1, 0.25, 0.5 and 1.0 points per fill. The right figure is still to be chosen; see open question 1 |
| Brokerage | ₹20 per order | Unchanged. Being flat per order, its cost per lot falls as lots rise |
| Position size | Up to 8–10 lots | The one-lot exit rule no longer has to apply. Experiments now cover 2, 8 and 10 lots and the sheet's rule for two or more lots: sell half at T1 and trail the rest |

Estimate from the console numbers, before any sweep. It assumes the same 35 trades and the same exits, with only costs changing.

| Lots | Slippage per fill | Charges per lot | Slippage per lot | Net per lot | Net for the whole position |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.5 | ₹3,266 | ₹3,705 | −₹10,936 | −₹10,936 |
| 8 | 0.5 | ₹912 | ₹3,705 | −₹8,582 | −₹68,656 |
| 8 | 0.25 | ₹912 | ₹1,852 | −₹6,730 | −₹53,836 |
| 8 | 0.1 | ₹912 | ₹741 | −₹5,618 | −₹44,944 |
| 10 | 0.25 | ₹845 | ₹1,852 | −₹6,662 | −₹66,622 |

More lots cut charges per lot by about 72%, but the trades lose ₹3,965 per lot before any cost. So a larger position loses more in total, not less, until the gross result turns positive. The one-lot row reproduces the console's −₹10,949 to within ₹13, which checks the split of fixed and per-lot charges.

## 9. Open questions

1. Which slippage figure should the team treat as the base case? A common choice for near-the-money NIFTY weekly options is 0.25 points per fill; 0.1 is two ticks and optimistic for a market order. This is an assumption to pick, not something the data can settle without bid-ask history.
2. May the team fetch an out-of-sample window (for example 2025-11-01 to 2026-04-30)? It costs about 25 minutes and 3,400 Groww requests, once.
3. With 8–10 lots available, should the base case use the sheet's two-or-more-lots exit rule (sell half at T1, trail the rest) from now on?
