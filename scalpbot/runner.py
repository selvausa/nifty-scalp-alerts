"""The live loop: every closed 5-minute candle, evaluate the setups and alert."""
from __future__ import annotations

import csv
import html
import logging
import math
import time as _time
from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

from .config import Settings, ist_now, load_events
from .groww import Groww, GrowwOptions
from .indicators import add_indicators
from .market import Ctx, build_context, session_only
from .setups import Engine, Signal, Sizing
from .state import DayState
from .telegram import Telegram

log = logging.getLogger("scalpbot")
FIRST_EVAL, LAST_EVAL = time(9, 20), time(15, 0)
DISCLAIMER = "Alert only. Rules are untested heuristics; you place and manage every order."
HELP = (
    "<b>Commands</b>\n"
    "/status – limits, position, market read\n"
    "/taken – I entered the last alert (counts a trade, blocks new alerts)\n"
    "/win [₹] · /loss [₹] · /flat – position closed\n"
    "/pause · /resume – stop or restart alerts\n"
    "/brief – today's levels"
)


def next_boundary(now: datetime) -> datetime:
    base = now.replace(second=0, microsecond=0)
    return base + timedelta(minutes=5 - base.minute % 5)


def fmt_signal(sig: Signal, ctx: Ctx) -> str:
    e = html.escape
    icon = "🟢" if sig.side.startswith("BUY") else "🟠"
    out = [f"{icon} <b>{e(sig.setup)} {e(sig.title)} — {e(sig.side)}</b>",
           f"{ctx.now:%H:%M} IST · fut {ctx.row['c']:,.1f} · VIX {ctx.vix:.2f} ({ctx.vix_chg_pct:+.1f}%) · "
           f"bias {ctx.bias} · DTE {ctx.dte}", ""]
    out += [e(l) for l in sig.lines]
    if sig.notes:
        out += [""] + ["⚠️ " + e(n) for n in sig.notes]
    out += ["", "<b>Checks</b>"]
    for c in sig.checks:
        mark = "✅" if c.ok else "❔" if c.ok is None else "❌"
        out.append(f"{mark} {e(c.name)}" + (f" <i>({e(c.detail)})</i>" if c.detail else ""))
    if any(c.ok is None for c in sig.checks):
        out.append("❔ = could not be checked from the data; verify by hand")
    out += ["", f"<i>{DISCLAIMER}</i>", "Reply /taken if you enter."]
    return "\n".join(out)


def fmt_brief(ctx: Ctx, lot: int) -> str:
    b, p, t = ctx.cpr
    orr = f"{ctx.or30[0]:,.1f}–{ctx.or30[1]:,.1f}" if ctx.or30 else "n/a"
    used = ctx.day_range / ctx.em if ctx.em and not math.isnan(ctx.em) else float("nan")
    ev = ", ".join(x.name for x in ctx.events)
    return "\n".join([
        f"<b>NIFTY levels {ctx.now:%d %b %H:%M}</b> (futures prices)",
        f"PDH {ctx.pdh:,.1f} · PDL {ctx.pdl:,.1f} · PDC {ctx.pdc:,.1f}",
        f"CPR {b:,.1f} / {p:,.1f} / {t:,.1f} · R1 {ctx.r1:,.1f} · S1 {ctx.s1:,.1f}",
        f"Opening range (09:15–09:45): {orr}",
        f"Expected move ±{ctx.em:,.0f} · range used {used:.0%}",
        f"VIX {ctx.vix:.2f} ({ctx.vix_chg_pct:+.1f}%) · ADX {ctx.row['adx']:.0f} · ATR {ctx.row['atr']:.1f} · bias {ctx.bias}",
        f"Days to expiry: {ctx.dte} · lot {lot}" + (f"\n⚠️ Event day: {html.escape(ev)}" if ev else ""),
    ])


class Bot:
    def __init__(self, s: Settings, groww: Optional[Groww] = None, tg: Optional[Telegram] = None):
        self.s = s
        self.g = groww or Groww(s)
        self.tg = tg or Telegram(s.telegram_token, s.telegram_chat_id)
        self.state_path = s.data_dir / "state.json"
        self.state = DayState.load(self.state_path, ist_now().date())
        self.ctx: Optional[Ctx] = None
        self.last_err = datetime.min
        self.miss = 0

    # ------------------------------------------------------------------ loop
    def run(self) -> None:
        self.tg.send("🤖 Scalp alert bot started. /help for commands.\n<i>" + DISCLAIMER + "</i>")
        while True:
            now = ist_now()
            nxt = next_boundary(now)
            wake = nxt + timedelta(seconds=2)
            while (rem := (wake - ist_now()).total_seconds()) > 0:
                for text in self.tg.poll(min(rem, 25)):
                    self.safely(self.command, text)
            if nxt.weekday() < 5 and FIRST_EVAL <= nxt.time() <= LAST_EVAL:
                self.safely(self.cycle, nxt)

    def safely(self, fn, *a) -> None:
        try:
            fn(*a)
        except Exception as e:
            log.exception("%s failed", getattr(fn, "__name__", fn))
            if ist_now() - self.last_err > timedelta(minutes=15):
                self.last_err = ist_now()
                self.tg.send(f"⚠️ Bot error in {getattr(fn, '__name__', '?')}: {html.escape(str(e))[:300]}")

    def roll_day(self, today) -> None:
        if self.state.day != today.isoformat():
            self.state = DayState.load(self.state_path, today)
            self.ctx = None

    # ----------------------------------------------------------------- cycle
    def cycle(self, boundary: datetime) -> None:
        """`boundary` is the close time of the candle to evaluate."""
        s, st = self.s, None
        today = boundary.date()
        self.roll_day(today)
        st = self.state
        self.g.ensure(today)
        ts = pd.Timestamp(boundary - timedelta(minutes=5))
        fut = pd.DataFrame()
        for attempt in range(6):          # the closed candle can take a few seconds to appear
            fut = self.g.fut_candles(boundary, need=ts)
            if ts in fut.index:
                break
            if not fut.empty and fut.index[-1].date() < today and attempt >= 1:
                break                     # no candles at all today: holiday or feed down
            _time.sleep(3)
        if ts not in fut.index:
            self.miss += 1
            log.warning("No %s candle from Groww (miss %d)", ts, self.miss)
            if self.miss == 3 and not fut.empty and fut.index[-1].date() == today:
                self.tg.send("⚠️ Groww candles are lagging; alerts may be missed.")
            return
        self.miss = 0
        fut = fut[fut.index <= ts]
        vix = None
        try:
            vix = self.g.vix_candles(boundary)
        except Exception as e:
            log.warning("VIX candles failed: %s", e)
        if (vix is None or vix.empty) and st.once("vix_missing"):
            self.tg.send("⚠️ India VIX data unavailable: VIX filters and expected move are off, sell setups will show ❔.")
        basis = 0.0
        try:
            spot = self.g.spot()
            if spot:
                basis = float(fut["c"].iloc[-1]) - spot
        except Exception as e:
            log.debug("spot failed: %s", e)
        dte = self.g.dte(today)
        if dte <= 0 and st.em is None:    # expiry day: expected move from the ATM straddle
            try:
                sd = self.g.chain().atm_straddle()
                if sd:
                    st.em = sd / 0.8
            except Exception as e:
                log.warning("straddle for expected move failed: %s", e)
        df = add_indicators(session_only(fut))
        ctx = build_context(df, ts, vix, dte, load_events(s.events_file), basis, st.em if dte <= 0 else None)
        if ctx is None:
            log.warning("Not enough history to evaluate %s", ts)
            return
        self.ctx = ctx
        if boundary.time() == time(9, 45) and st.once("brief"):
            self.tg.send(fmt_brief(ctx, self.g.lot_size))
        if st.position_open:
            flat = time(14, 45) if dte <= 0 else time(15, 0)
            if boundary.time() == time(14, 45) and dte > 0 and st.once("warn1445"):
                self.tg.send("⏰ 14:45 — exits only from here. Flat by 15:00.")
            if boundary.time() >= flat and st.once("flat"):
                self.tg.send(f"⏰ {flat:%H:%M} — the sheet says be flat now. Reply /win, /loss or /flat once closed.")
        blocked = st.blocked(s.rules, s.capital)
        if blocked:
            log.info("%s no evaluation: %s", boundary.time(), blocked)
            st.save(self.state_path)
            return
        eng = Engine(s.rules, Sizing(s.capital, s.risk_pct, self.g.lot_size))
        sigs = eng.evaluate(ctx, GrowwOptions(self.g))
        for r in eng.rejects:
            log.info("%s rejected %s", boundary.time(), r)
        for sig in sigs:
            if not st.can_send(sig.key, boundary, s.rules.cooldown_min):
                continue
            if self.tg.send(fmt_signal(sig, ctx)):
                st.mark_sent(sig.key, boundary)
                self.log_alert(sig, ctx)
        if not sigs and not eng.rejects:
            log.info("%s no setup conditions", boundary.time())
        st.save(self.state_path)

    def log_alert(self, sig: Signal, ctx: Ctx) -> None:
        """One row per alert, for forward-testing the rules."""
        path = self.s.data_dir / "alerts.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "setup", "side", "fut_close", "vix", "bias", "dte", "atr", "adx",
                            "details", "unchecked"])
            w.writerow([ctx.now.isoformat(), sig.setup, sig.side, f"{ctx.row['c']:.1f}", f"{ctx.vix:.2f}", ctx.bias,
                        ctx.dte, f"{ctx.row['atr']:.1f}", f"{ctx.row['adx']:.0f}",
                        "; ".join(f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}" for k, v in sig.data.items()),
                        "; ".join(c.name for c in sig.checks if c.ok is None)])

    # -------------------------------------------------------------- commands
    def command(self, text: str) -> None:
        self.roll_day(ist_now().date())
        st, parts = self.state, text.split()
        cmd = parts[0].lower().split("@")[0]
        amt = 0.0
        if len(parts) > 1:
            try:
                amt = abs(float(parts[1].replace(",", "").replace("₹", "")))
            except ValueError:
                pass
        if cmd in ("/start", "/help"):
            self.tg.send(HELP)
            return
        if cmd == "/taken":
            st.position_open, st.trades = True, st.trades + 1
            msg = f"Noted: trade {st.trades} of {self.s.rules.max_trades} is open. New alerts are off until you close it."
        elif cmd == "/win":
            st.position_open, st.consec_losses, st.pnl = False, 0, st.pnl + amt
            msg = "Noted: win."
        elif cmd == "/loss":
            st.position_open, st.consec_losses, st.pnl = False, st.consec_losses + 1, st.pnl - amt
            msg = "Noted: loss."
        elif cmd == "/flat":
            st.position_open = False
            msg = "Noted: flat."
        elif cmd == "/pause":
            st.paused = True
            msg = "Paused."
        elif cmd == "/resume":
            st.paused = False
            msg = "Resumed."
        elif cmd == "/brief":
            self.tg.send(fmt_brief(self.ctx, self.g.lot_size) if self.ctx else "No market data yet today.")
            return
        elif cmd == "/status":
            msg = ""
        else:
            self.tg.send("Unknown command. /help")
            return
        st.save(self.state_path)
        blocked = st.blocked(self.s.rules, self.s.capital)
        self.tg.send("\n".join(filter(None, [
            html.escape(msg),
            f"Trades {st.trades}/{self.s.rules.max_trades} · losses in a row {st.consec_losses} · P&L ₹{st.pnl:,.0f}",
            f"Position: {'OPEN' if st.position_open else 'none'}",
            "Alerts: " + (f"OFF — {html.escape(blocked)}" if blocked else "on"),
        ])))
