"""
Papier-Broker: simuliert einen Kauf gegen das Orderbuch.

Kein Netzwerkzugriff, keine Orders. Gekauft wird, indem die Verkaufsangebote
(asks) von unten nach oben abgearbeitet werden, bis das Budget verbraucht ist.
So kostet ein großer Kauf in einem dünnen Markt realistisch mehr.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from paperbot.fees import FeeModel
from paperbot.models import Book, Fill


@dataclass(frozen=True)
class FillResult:
    fill: Optional[Fill]
    reason: str = ""


def simulate_buy(book: Book, budget: float, *, side: str, market_id: str, ts: int,
                 fee: FeeModel, category: str = "", min_shares: float = 5.0,
                 max_price: float = 0.98) -> FillResult:
    if budget <= 0:
        return FillResult(None, "Budget 0")
    # Kalshi rundet die Gebühr je Order auf den Cent auf: diesen Cent vorher zurücklegen,
    # sonst können die Kosten das Budget (und damit das Bargeld) knapp übersteigen.
    remaining = budget - (0.01 if fee.kind == "kalshi" else 0.0)
    shares = notional = fee_total = 0.0
    for level in book.asks:
        if level.price > max_price:
            break
        per_share = level.price + fee.per_share(level.price, category)
        take = min(level.size, remaining / per_share)
        if take <= 0:
            break
        shares += take
        notional += take * level.price
        fee_total += take * (per_share - level.price)
        remaining -= take * per_share
        if remaining <= 1e-9:
            break

    if not book.asks:
        return FillResult(None, "keine Verkaufsangebote")
    # auf 0,01 Anteile abrunden; +1e-6 fängt 4,999999… bei genau der Mindestgröße ab
    rounded = math.floor(shares * 100 + 1e-6) / 100
    if rounded < min_shares:
        return FillResult(None, f"nur {rounded:.2f} Anteile ≤ {max_price:.2f} erreichbar (min. {min_shares:g})")

    # Abrunden kürzt alle Stufen anteilig: Durchschnittspreis bleibt, Gebühr schrumpft mit.
    scale = rounded / shares
    return FillResult(Fill(
        market_id=market_id,
        side=side,
        shares=rounded,
        avg_price=notional / shares,
        fee=fee.round_total(fee_total * scale),
        ts=ts,
        synthetic_book=book.synthetic,
    ))
