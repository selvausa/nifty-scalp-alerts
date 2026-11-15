from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, time, timedelta

import pandas as pd

from .config import Settings, ist_now, load_events
from .groww import Groww
from .indicators import add_indicators
from .market import build_context, session_only
from .runner import Bot, fmt_brief, fmt_signal
from .setups import Engine, Sizing
from .state import DayState
from .telegram import Telegram


def cmd_run(s: Settings, a) -> int:
    Bot(s).run()
    return 0


def cmd_doctor(s: Settings, a) -> int:
    """Checks credentials and prints what each Groww call returns, so a wrong
    assumption about the API shows up here rather than as a silent missed alert."""
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            print(f"\n== {name}")
            fn()
        except Exception as e:
            ok = False
            print(f"   FAILED: {type(e).__name__}: {e}")

    g = Groww(s)
    today, now = ist_now().date(), ist_now()
    step("Groww login and instruments", lambda: (g.connect(today), print(
        f"   future: {g.fut}\n   VIX:    {g.vix}\n   weekly expiry: {g.expiry} (DTE {g.dte(today)}) · lot {g.lot_size}")))
    if g.api is None:
        return 1

    def candles(inst_name):
        inst = getattr(g, inst_name)
        df = g.candles(inst, now - timedelta(days=7), now)
        print(f"   endpoint: {g.mode_for(inst)} · {len(df)} candles · sessions: {sorted(set(df.index.date))[-3:]}")
        print(df.tail(3).to_string().replace("\n", "\n   "))
        if df.empty:
            raise RuntimeError("no candles returned")

    step("Futures 5-min candles", lambda: candles("fut"))
    if g.vix:
        step("India VIX 5-min candles", lambda: candles("vix"))
    else:
        ok = False
        print("\n== India VIX: NOT FOUND. Set VIX_GROWW_SYMBOL / VIX_TRADING_SYMBOL in .env")
    step("NIFTY spot", lambda: print("   ", g.spot()))

    def chain():
        raw = g.api.get_option_chain("NSE", "NIFTY", g.expiry, timeout=15)
        print("   top-level keys:", list(raw.keys())[:10])
        ch = g.chain()
        k = int(round(ch.spot / 50) * 50)
        ce = ch.get(k, "CE")
        print(f"   spot {ch.spot} · {len(ch.legs)} legs · ATM {k} CE: {ce}")
        if not ch.legs or ce is None or not ce.delta:
            raise RuntimeError("chain parsed without legs or deltas; raw sample: " + json.dumps(raw)[:600])
        q = g.api.get_quote(ce.symbol, "NSE", "FNO", timeout=10)
        print("   quote keys:", list(q.keys())[:25])
        leg = g.fill_quote(ce)
        print(f"   bid {leg.bid} · ask {leg.ask} · last {leg.ltp}")
        if leg.bid is None or leg.ask is None:
            raise RuntimeError("no bid/ask parsed from the quote (expected when the market is closed)")
        oc = g.option_candles(leg)
        print(f"   option candles today: {len(oc)}")

    step("Option chain, quote and option candles", chain)
    tg = Telegram(s.telegram_token, s.telegram_chat_id)
    if tg.enabled:
        step("Telegram", lambda: print("   sent" if tg.send("✅ Scalp alert bot: Telegram test") else "   send failed"))
    else:
        print("\n== Telegram: not configured (alerts would print to the console)")
    print("\nAll checks passed." if ok else "\nSome checks failed; see above.")
    return 0 if ok else 1


def cmd_replay(s: Settings, a) -> int:
    """Re-runs the chart-side rules over a past session. Option checks are not replayed."""
    day = date.fromisoformat(a.date)
    g = Groww(s)
    g.connect(ist_now().date())
    end = datetime.combine(day, time(15, 30))
    fut = g.candles(g.fut, end - timedelta(days=7), end)
    vix = g.candles(g.vix, end - timedelta(days=7), end) if g.vix else None
    df = add_indicators(session_only(fut))
    events = load_events(s.events_file)
    eng = Engine(s.rules, Sizing(s.capital, s.risk_pct, g.lot_size))
    dte = a.dte if a.dte is not None else 3
    n, st = 0, DayState(day=day.isoformat())      # same de-duplication as the live bot
    for ts in df.index[df.index.normalize() == pd.Timestamp(day)]:
        ctx = build_context(df, ts, vix, dte, events, vix_fall_pct=s.rules.vix_fall_sharp_pct)
        if ctx is None:
            continue
        if ctx.now.time() == time(9, 45):
            print(_plain(fmt_brief(ctx, g.lot_size)), "\n")
        for sig in eng.evaluate(ctx, None):
            if not st.can_send(sig.key, ctx.now, s.rules.cooldown_min):
                continue
            st.mark_sent(sig.key, ctx.now)
            n += 1
            print(_plain(fmt_signal(sig, ctx)), "\n" + "-" * 60)
        if a.verbose:
            for r in eng.rejects:
                print(f"{ctx.now:%H:%M} rejected {r}")
    print(f"{n} chart-side signal(s) on {day} (assumed DTE {dte}; option checks not replayed)")
    return 0


def _plain(t: str) -> str:
    import re

    return re.sub(r"</?[bi]>", "", t)


def main() -> int:
    p = argparse.ArgumentParser(prog="scalpbot", description="NIFTY options scalping alert bot (alerts only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the live alert loop")
    sub.add_parser("doctor", help="check credentials and data access")
    r = sub.add_parser("replay", help="re-run chart-side rules over a past day")
    r.add_argument("date", help="YYYY-MM-DD")
    r.add_argument("--dte", type=int, help="days to expiry to assume (default 3)")
    r.add_argument("-v", "--verbose", action="store_true", help="also print why setups were rejected")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    return {"run": cmd_run, "doctor": cmd_doctor, "replay": cmd_replay}[a.cmd](s, a)


if __name__ == "__main__":
    sys.exit(main())
