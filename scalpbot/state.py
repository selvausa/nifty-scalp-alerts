"""Per-day trading state: limits, open position, and which alerts were already sent."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .config import Rules

ONCE_PER_DAY = ("B2", "B3")   # first break only; a second attempt is a do-not-take


@dataclass
class DayState:
    day: str = ""
    trades: int = 0
    consec_losses: int = 0
    pnl: float = 0.0
    position_open: bool = False
    paused: bool = False
    em: Optional[float] = None
    sent: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, today: date) -> "DayState":
        try:
            raw = json.loads(path.read_text())
            if raw.get("day") == today.isoformat():
                return cls(**raw)
            # a new day resets everything except the pause switch
            return cls(day=today.isoformat(), paused=bool(raw.get("paused", False)))
        except (OSError, ValueError, TypeError):
            return cls(day=today.isoformat())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1))
        tmp.replace(path)

    def blocked(self, rules: Rules, capital: float) -> Optional[str]:
        if self.paused:
            return "paused (/resume to restart)"
        if self.position_open:
            return "a position is open (/win, /loss or /flat when it closes)"
        if self.trades >= rules.max_trades:
            return f"{rules.max_trades} trades already taken today"
        if self.consec_losses >= rules.max_consec_losses:
            return f"{rules.max_consec_losses} consecutive losses"
        if capital > 0 and self.pnl <= -capital * rules.daily_stop_pct / 100:
            return f"daily loss limit hit (₹{self.pnl:,.0f})"
        return None

    def can_send(self, key: str, now: datetime, cooldown_min: int) -> bool:
        last = self.sent.get(key)
        if last is None:
            return True
        if key.split(":")[0] in ONCE_PER_DAY:
            return False
        return (now - datetime.fromisoformat(last)).total_seconds() >= cooldown_min * 60

    def mark_sent(self, key: str, now: datetime) -> None:
        self.sent[key] = now.isoformat()

    def once(self, flag: str) -> bool:
        """True the first time a flag is seen today."""
        if self.flags.get(flag):
            return False
        self.flags[flag] = True
        return True
