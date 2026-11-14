"""Option-chain model, strike selection and liquidity checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import pandas as pd

from .config import Rules


@dataclass
class Leg:
    strike: int
    kind: str                 # CE / PE
    symbol: str               # exchange trading symbol
    ltp: float
    delta: float
    bid: Optional[float] = None
    ask: Optional[float] = None

    @property
    def spread(self) -> Optional[float]:
        if self.bid and self.ask and self.ask >= self.bid:
            return self.ask - self.bid
        return None

    @property
    def label(self) -> str:
        return f"{self.strike} {self.kind}"


@dataclass
class Chain:
    spot: float
    expiry: str
    legs: dict[tuple[int, str], Leg]

    def get(self, strike: int, kind: str) -> Optional[Leg]:
        return self.legs.get((strike, kind))

    def atm_straddle(self) -> Optional[float]:
        k = int(round(self.spot / 50) * 50)
        ce, pe = self.get(k, "CE"), self.get(k, "PE")
        return ce.ltp + pe.ltp if ce and pe and ce.ltp and pe.ltp else None


class OptionsData(Protocol):
    def chain(self) -> Chain: ...
    def fill_quote(self, leg: Leg) -> Leg: ...
    def candles(self, leg: Leg) -> pd.DataFrame: ...


def buy_delta_range(dte: int) -> tuple[float, float]:
    """Expiry day: 1-2 strikes ITM. Day before: slightly ITM. Otherwise ATM."""
    if dte <= 0:
        return 0.60, 0.80
    if dte == 1:
        return 0.50, 0.65
    return 0.45, 0.55


def sell_delta_range(setup: str, dte: int) -> tuple[float, float]:
    if setup == "S3":
        return 0.03, 0.20
    if dte <= 0:
        return 0.10, 0.20
    return (0.15, 0.25) if setup == "S1" else (0.15, 0.30)


def pick_buy(chain: Chain, direction: int, dte: int) -> Optional[Leg]:
    kind = "CE" if direction > 0 else "PE"
    lo, hi = buy_delta_range(dte)
    mid = (lo + hi) / 2
    c = [l for (k, t), l in chain.legs.items() if t == kind and lo <= abs(l.delta) <= hi and l.ltp > 0]
    return min(c, key=lambda l: abs(abs(l.delta) - mid)) if c else None


def buy_spread_ok(leg: Leg, rules: Rules) -> Optional[bool]:
    sp = leg.spread
    if sp is None:
        return None
    ref = leg.ltp or (leg.bid + leg.ask) / 2
    return bool(sp <= rules.buy_spread_abs + 1e-9 and sp <= ref * rules.buy_spread_pct / 100 + 1e-9)


@dataclass
class CreditSpread:
    short: Leg
    hedge: Leg

    @property
    def credit(self) -> float:
        """Conservative when quotes exist: sell at the bid, buy the hedge at the ask."""
        s = self.short.bid if self.short.bid else self.short.ltp
        h = self.hedge.ask if self.hedge.ask else self.hedge.ltp
        return s - h

    @property
    def label(self) -> str:
        return f"sell {self.short.label} / buy {self.hedge.label}"


def pick_credit_spread(
    chain: Chain, kind: str, beyond: float, drange: tuple[float, float], rules: Rules
) -> Optional[CreditSpread]:
    """Short strike past `beyond` (spot terms): below it for PE, above it for CE.
    Takes the strike nearest the money that fits the delta range, hedge 100 points further."""
    lo, hi = drange
    step = -rules.spread_width if kind == "PE" else rules.spread_width
    c = []
    for (k, t), l in chain.legs.items():
        if t != kind or l.ltp <= 0 or not (lo <= abs(l.delta) <= hi):
            continue
        if (kind == "PE" and k >= beyond) or (kind == "CE" and k <= beyond):
            continue
        h = chain.get(k + step, kind)
        if h and h.ltp > 0:
            c.append(CreditSpread(l, h))
    if not c:
        return None
    return max(c, key=lambda s: abs(s.short.delta))


def legs_liquid(legs: list[Leg], rules: Rules) -> Optional[bool]:
    sp = [l.spread for l in legs]
    if any(s is None for s in sp):
        return None
    return bool(all(s <= rules.sell_leg_spread + 1e-9 for s in sp))
