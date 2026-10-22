"""
Regelbasierte Strategien aus docs/HYPOTHESEN.md (H1–H3) und Kontrollen.

Keine dieser Strategien behauptet eine Wahrscheinlichkeit (prob=None): Sie
werden mit festem Einsatz gespielt, bis ein Backtest oder das Live-Papierkonto
zeigt, ob sie etwas taugen.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from paperbot.models import Signal, side_price
from paperbot.strategies.base import Strategy, make_signal
from paperbot.view import MarketView


@dataclass
class FavoriteStrategy:
    """H1: Kauf der Seite, deren Preis im Band [lo, hi] liegt (Favorite-Longshot-Bias)."""
    lo: float = 0.85
    hi: float = 0.97
    max_days_to_end: Optional[float] = None   # nur wenn das Ende vorher bekannt ist
    name: str = "favorite"
    needs_history: bool = False
    live_only: bool = False

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        p = view.price()
        if p is None:
            return None
        days = view.days_to_end()
        if self.max_days_to_end is not None and days is not None and days > self.max_days_to_end:
            return None
        for side in ("YES", "NO"):
            s = side_price(p, side)
            if self.lo <= s <= self.hi:
                return make_signal(self.name, view, side, None, f"Favorit {side} zu {s:.3f}")
        return None


@dataclass
class MomentumStrategy:
    """H2: Bewegung ≥ threshold in lookback_days → Kauf in Bewegungsrichtung."""
    threshold: float = 0.10
    lookback_days: float = 3.0
    room: float = 0.05            # nicht kaufen, wenn die Seite schon < 5 % Luft hat
    name: str = "momentum"
    needs_history: bool = True
    live_only: bool = False

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        p = view.price()
        age = view.age_days()
        if p is None or age is None or age < self.lookback_days:
            return None
        p0 = view.price_days_ago(self.lookback_days)
        if p0 is None:
            return None
        move = p - p0
        side = "YES" if move >= self.threshold else "NO" if move <= -self.threshold else None
        if side is None or not self.room <= side_price(p, side) <= 1 - self.room:
            return None
        return make_signal(self.name, view, side, None,
                           f"Momentum {move:+.2f} in {self.lookback_days:g} Tagen")


@dataclass
class ReversionStrategy:
    """H3: Bewegung ≥ threshold in lookback_days → Kauf gegen die Bewegung."""
    threshold: float = 0.15
    lookback_days: float = 1.0
    room: float = 0.05
    name: str = "reversion"
    needs_history: bool = True
    live_only: bool = False

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        p = view.price()
        age = view.age_days()
        if p is None or age is None or age < self.lookback_days:
            return None
        p0 = view.price_days_ago(self.lookback_days)
        if p0 is None:
            return None
        move = p - p0
        side = "NO" if move >= self.threshold else "YES" if move <= -self.threshold else None
        if side is None or not self.room <= side_price(p, side) <= 1 - self.room:
            return None
        return make_signal(self.name, view, side, None,
                           f"Gegenbewegung auf {move:+.2f} in {self.lookback_days:g} Tagen")


def _coin(key: str) -> str:
    return "YES" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2 == 0 else "NO"


@dataclass
class RandomSideControl:
    """Kontrolle: gleicher Zeitpunkt wie `base`, aber Seite per Münzwurf (reproduzierbar)."""
    base: Strategy
    name: str = "random_control"
    salt: str = ""

    @property
    def needs_history(self) -> bool:
        return self.base.needs_history

    @property
    def live_only(self) -> bool:
        return self.base.live_only

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        if self.base.evaluate(view) is None:
            return None
        side = _coin(self.salt + view.info.market_id)
        return make_signal(self.name, view, side, None, f"Zufallsseite (Zeitpunkt von {self.base.name})")


@dataclass
class AlwaysYesControl:
    """Kontrolle: gleicher Zeitpunkt wie `base`, immer YES."""
    base: Strategy
    name: str = "always_yes"

    @property
    def needs_history(self) -> bool:
        return self.base.needs_history

    @property
    def live_only(self) -> bool:
        return self.base.live_only

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        if self.base.evaluate(view) is None:
            return None
        return make_signal(self.name, view, "YES", None, f"immer YES (Zeitpunkt von {self.base.name})")
