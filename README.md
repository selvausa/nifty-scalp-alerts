# nifty-scalp-alerts

Telegram alert bot for the *NIFTY 50 Options Scalping Cheat Sheet*. On every closed
5-minute candle of NIFTY futures it checks the sheet's six setups (B1–B3 buys, S1–S3
credit spreads) and sends an alert when every check passes.

**It only sends alerts. It places no orders.** Every threshold comes from the cheat
sheet, which itself marks them as untested heuristics. Forward-test at one lot.

> **Status: not yet run against a live Groww account.** The rules engine is covered by
> tests on synthetic data. The Groww calls were written from the SDK source, so run
> `python -m scalpbot doctor` first — it shows what each call returns and what fails.

## Setup

Needs Python 3.10+ and a machine that stays on from 09:15 to 15:00 IST on market days.

```bash
git clone https://github.com/selvausa/nifty-scalp-alerts && cd nifty-scalp-alerts
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill it in; never commit .env
```

1. **Groww Trading API** (paid subscription). On the Groww API keys page create a
   **TOTP** key and put the key in `GROWW_API_KEY` and the TOTP secret in
   `GROWW_TOTP_SECRET`. This logs in by itself each morning. A key + secret pair also
   works (`GROWW_API_SECRET`) but needs a manual approval on Groww every day.
2. **Telegram**. Message `@BotFather`, send `/newbot`, copy the token to
   `TELEGRAM_BOT_TOKEN`. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` to
   `TELEGRAM_CHAT_ID`. The bot ignores every other chat.
3. **Sizing** (optional). Set `CAPITAL` to get lot counts in alerts and the 2% daily stop.
4. **Events**. Add RBI policy, Budget, election-result and post-CPI/FOMC dates to
   `events.txt`.

## Run

```bash
python -m scalpbot doctor               # check login, data and Telegram (run in market hours)
python -m scalpbot replay 2026-11-13 -v # chart-side rules over a past day, printed to the console
python -m scalpbot run                  # the live loop
```

To keep it running on a Linux server, a systemd unit:

```ini
[Unit]
Description=NIFTY scalp alerts
After=network-online.target

[Service]
WorkingDirectory=/home/you/nifty-scalp-alerts
ExecStart=/home/you/nifty-scalp-alerts/.venv/bin/python -m scalpbot run
Restart=always
RestartSec=10
Environment=TZ=Asia/Kolkata

[Install]
WantedBy=multi-user.target
```

## Telegram commands

| Command | Effect |
| --- | --- |
| `/taken` | You entered the last alert. Counts a trade; alerts stop until you close it |
| `/win [₹]`, `/loss [₹]`, `/flat` | Position closed. Feeds the 3-losses and daily-loss limits |
| `/status` | Trades, losses in a row, P&L, whether alerts are on |
| `/pause`, `/resume` | Switch alerts off or on |
| `/brief` | PDH/PDL/PDC, CPR, opening range, expected move, VIX, bias |

The bot cannot see your positions; the limits (4 trades, 3 losses in a row, 2% of
capital, one position at a time) work only if you send these commands.

## What you get

- 09:45: a levels brief.
- An alert per setup with strike, premium, invalidation level, stop size S, T1,
  disaster stop, time stop, lot count and the full checklist with the numbers behind it.
- Reminders at 14:45 and 15:00 while a position is open.
- `data/alerts.csv`: one row per alert, for forward-testing.
- B2 and B3 alert once a day per side; other setups at most once every 30 minutes per side.
- Commands sent while the bot is not running are ignored when it starts; send them again.
- If option data cannot be fetched, the alert still goes out with those checks marked ❔.

## Where the sheet needed interpreting

| Sheet wording | What the bot does |
| --- | --- |
| Monday / Tuesday rules | Uses days to the weekly expiry (1 / 0), so holiday-shifted expiries work |
| "Volume at least the prior pullback candle's" (B1) | Compares with the previous candle |
| "Touches VWAP or the 20 EMA" | Candle low within 1 point of the level, close back above it |
| "Chopping across VWAP" | 3 or more VWAP crosses in the last 10 candles with ADX below 20. A veto for B1; a warning on B2/B3, which break out of a range by definition |
| "Squeeze range's swing high/low" (B3) | High/low of the 6 candles before the break |
| "VIX falling sharply" (B3) | VIX down 1% or more over 3 candles |
| "Nearest swing low" (S2) | Lowest low of the last 12 candles |
| "Not rising" ADX (S1) | Not above its value 3 candles ago |
| Expected move | Spot × VIX / 100 / √252 from the first candle; on expiry day the ATM straddle / 0.8 |
| 100-strike inside T1 | Checked on spot; PDH/PDL on the futures chart |
| Event day with no time in `events.txt` | No buys all day |

Not automated: the 3-minute chart rules, exits and trailing after entry, the monthly
rollover-week contract switch (set `FUT_GROWW_SYMBOL` by hand), and exchange holidays
(the bot just finds no candles and stays quiet).

## Layout

`scalpbot/indicators.py` indicators · `market.py` per-candle context · `setups.py` the six
setups · `options.py` strike selection · `groww.py` data · `runner.py` live loop and
alert text · `state.py` daily limits · `tests/` synthetic-data tests (`pytest`).
