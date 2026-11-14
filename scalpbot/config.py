from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """Current time as a naive datetime in IST (all bot times are naive IST)."""
    return datetime.now(IST).replace(tzinfo=None)


def hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Rules:
    """Thresholds from the cheat sheet. All are untested heuristics (H)."""

    s_min: float = 10.0
    s_max: float = 20.0
    adx_trend: float = 20.0
    vix_up_block_pct: float = 5.0      # VIX up more than this on the day: no selling
    vix_half_size: float = 18.0        # VIX above this and rising: half size on buys
    vix_fall_sharp_pct: float = 1.0    # B3: VIX down this much over 3 candles = "falling sharply"
    buy_spread_abs: float = 0.50
    buy_spread_pct: float = 0.5
    sell_leg_spread: float = 0.15
    min_credit: float = 22.0
    min_credit_condor: float = 44.0
    spread_width: int = 100
    or_width_em_max: float = 0.4       # B2: opening range at most 0.4 x expected move
    or_width_atr_min: float = 4.0      # S1: opening range at least 4 x ATR
    squeeze_lookback: int = 6
    b3_vol_mult: float = 1.5
    max_trades: int = 4
    max_consec_losses: int = 3
    daily_stop_pct: float = 2.0
    cooldown_min: int = 30             # re-alert gap for the same setup and side
    buy_cost: float = 66.0             # round-trip rupees, one lot (sheet section 7)
    spread_cost: float = 107.5
    condor_cost: float = 215.0


@dataclass
class Settings:
    groww_api_key: str = ""
    groww_api_secret: str = ""
    groww_totp_secret: str = ""
    groww_access_token: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    capital: float = 0.0
    risk_pct: float = 0.5
    fut_groww_symbol: str = ""
    fut_trading_symbol: str = ""
    vix_groww_symbol: str = ""
    vix_trading_symbol: str = ""
    candle_api: str = "auto"
    data_dir: Path = Path("data")
    events_file: Path = Path("events.txt")
    rules: Rules = field(default_factory=Rules)

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:  # pragma: no cover
            pass
        g = lambda k, d="": os.environ.get(k, d).strip()
        fl = lambda k, d: float(g(k) or d)
        return cls(
            groww_api_key=g("GROWW_API_KEY"),
            groww_api_secret=g("GROWW_API_SECRET"),
            groww_totp_secret=g("GROWW_TOTP_SECRET"),
            groww_access_token=g("GROWW_ACCESS_TOKEN"),
            telegram_token=g("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=g("TELEGRAM_CHAT_ID"),
            capital=fl("CAPITAL", 0),
            risk_pct=fl("RISK_PCT", 0.5),
            fut_groww_symbol=g("FUT_GROWW_SYMBOL"),
            fut_trading_symbol=g("FUT_TRADING_SYMBOL"),
            vix_groww_symbol=g("VIX_GROWW_SYMBOL"),
            vix_trading_symbol=g("VIX_TRADING_SYMBOL"),
            candle_api=g("CANDLE_API", "auto") or "auto",
            data_dir=Path(g("DATA_DIR", "data") or "data"),
            events_file=Path(g("EVENTS_FILE", "events.txt") or "events.txt"),
        )


@dataclass(frozen=True)
class Event:
    day: date
    at: time | None
    name: str


def load_events(path: Path) -> list[Event]:
    out: list[Event] = []
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 2)
        try:
            d = date.fromisoformat(parts[0])
        except ValueError:
            continue
        at, name = None, " ".join(parts[1:])
        if len(parts) > 1 and ":" in parts[1]:
            try:
                at, name = hm(parts[1]), (parts[2] if len(parts) > 2 else "event")
            except ValueError:
                pass
        out.append(Event(d, at, name or "event"))
    return out
