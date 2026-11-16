# Draft playbook for red-team review (NIFTY and SENSEX index options, intraday)

Owner: Rs 1,00,000 capital, broker Groww (Rs 20 per order), wants positive expectancy after costs per trade, relative to risk and screen time.

## Verified facts (as of 2026-11-16; sources: exchange circulars via secondary reports, see research notes)
- NIFTY lot 65 (NSE/FAOP/70616), weekly expiry Tuesday (holiday -> previous day: 9 Nov, 23 Nov 2026 were Mondays). NSE F&O close 15:40 since 3 Aug 2026.
- SENSEX lot 20; 25 for contracts expiring from Jan 2027 (BSE, via Zerodha bulletin 7 Oct 2026). Weekly expiry Thursday. BSE close at 15:40 NOT confirmed.
- STT 0.15% of option sell premium from 1 Apr 2026. NSE txn ~Rs 3,503/cr premium (Oct 2024); BSE SENSEX options Rs 3,250/cr. Expiry-day extra 2% ELM on short options; no expiry-day calendar-spread benefit; intraday position-limit monitoring; one weekly expiry per exchange.

## Evidence (all NIFTY, 5-min, 2025-11-01..2026-10-31, 245 days, cached Groww futures/spot/VIX/option candles)
Code: research/playbook/study.py, trendday.py, analyse.py. Outputs: research/playbook/out_*.csv, out_analysis.txt.
Prior review of the old cheat sheet's six setups: docs/backtest_review_2026-05_2026-10.md (none had an edge; S2 -Rs264/trade over 37 trades, CI -354..-170).
Fills: signal on a close, entry and close-triggered exits at the NEXT candle open; option legs priced from real option candles; Groww/NSE charges; slippage 0.1 and 0.5 per fill.

| Test | Trades | Rs/trade @0.1 | 95% CI | Rs/trade @0.5 | H1 Nov-Apr / H2 May-Oct (Rs/trade @0.1) | Notes |
| ORB30 (pre-registered) | 124 | -249 | -492..14 | -301 (CI -543..-38) | -205 / -290 | signal's index move in its own direction: mean -3.8 pts |
| VWAPF fade (pre-registered) | 40 | -149 | -463..153 | -201 | -228 / -42 | signal move -2.9 pts |
| IFLY expiry iron fly W150 (pre-registered) | 45 (+6 days missing data) | +65 | -496..607 | -124 | +580 / -386 | W100 -118/-318, W200 +161/-55 |
| IFLY-R (pre-registered filter) | 20 | +113 | -768..939 | -62 | +1576 (n5) / -375 (n15) | |
| TREND10 (designed AFTER seeing the regime study: in-sample) | 43 | +866 | -245..2077 | +814 | +341 / +1469 | top 3 trades = 77% of net; median trade -191; 11 losses <= -2,000; worst -4,775 |

Regime study (out_analysis.txt): trend day = |move 09:45->15:00| >= 0.5 x expected move; 36% of days.
Trend share: VIX>18 49% (n47) vs <12 30%; gap <= -0.5% 57% (n28); OR30 > 0.5xEM 43% (n93) vs 0.25-0.35 24%; ADX at 10:15 no relation (30-42%).
Median 5-min range by time: 09:15-09:30 40 pts, 10:00 21, 11:00-13:00 16-17, 14:00-15:00 19.

## Draft core strategies
1. TREND10, trend-day continuation (NIFTY, any weekday). Qualify at 10:15: VIX at open > 18 OR gap <= -0.5% OR OR30 > 0.5 x EM.
   10:10 close outside 09:15-09:45 range -> buy ATM (delta 0.45-0.55) at 10:15 open in that direction. Stop: 5-min close beyond OR midpoint.
   No target; exit 14:45. 1 per day. Status: paper until validated on an unseen window.
2. IFLY, NIFTY expiry-day iron fly (Tuesday or holiday-shifted). At 10:15 if not a trend-qualified day: sell ATM CE+PE, buy 150-point wings.
   Exit at 50% of credit, stop at 1.5x credit, else 14:30. Median credit 83 pts, max loss median 67 pts = ~Rs 4,355/lot.
   Status: paper only (sign depends on slippage; flips between halves).
- Everything else -> no trade (range days: nothing tested works).
- SENSEX: same structures on Thursday are untested heuristics (no SENSEX data). NIFTY is the default index.

## Draft regime filter
09:15: event day / data problem -> no trade. 09:45: VIX up > 5% on day -> no selling. 10:15:
 A. Trend-qualified (VIX>18 or gap<=-0.5% or OR30>0.5xEM)? yes -> 10:10 close outside OR30? yes -> TREND10; no -> no trade.
 B. Not trend-qualified: NIFTY expiry day and |gap| <= 0.5% and 09:15-10:15 range <= 0.7 x EM -> IFLY (paper); else no trade.

## Draft risk
1% of Rs 1,00,000 = Rs 1,000. TREND10 stop distance = index distance to OR mid x delta 0.5 x 65: often Rs 1,600-3,250 per lot; worst -4,775.
IFLY worst case ~Rs 4,355 + costs per lot; expiry-day margin roughly Rs 40-80k per lot (estimate, not sourced). One lot max.
