"""
Strategie-Schnittstelle.

Eine Strategie bekommt nur eine MarketView (gekürzt auf die Entscheidungszeit)
und gibt höchstens ein Signal zurück. Sie kennt weder Kontostand noch
Ergebnis. Größe und Risiko entscheidet paperbot.risk, nicht die Strategie.
"""
from __future__ import annotations

from typing import Optional, Protocol

from paperbot.models import Signal, side_price
from paperbot.view import MarketView


class Strategy(Protocol):
    name: str
    needs_history: bool    # braucht mehr als den aktuellen Preis
    live_only: bool        # nicht per Backtest prüfbar (z. B. LLM)

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        ...


def make_signal(strategy: str, view: MarketView, side: str,
                prob: Optional[float], reason: str) -> Signal:
    p = view.price()
    if p is None:
        raise ValueError("make_signal ohne Preis")
    return Signal(
        strategy=strategy,
        market_id=view.info.market_id,
        side=side,
        price=side_price(p, side),
        prob=prob,
        reason=reason,
        ts=view.now_ts,
    )
