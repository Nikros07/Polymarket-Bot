"""
Gebührenmodell.

Polymarket (Taker, seit 2026 je Kategorie, Recherche-Stand 2026-10-22):
    fee = Anteile × Preis × feeRate × (Preis × (1 − Preis))
mit feeRate = 4 × Peak-Rate, damit bei Preis 0,5 genau die Peak-Rate pro
Euro Einsatz anfällt. Bei 95 Cent ist die Gebühr dadurch sehr klein.
Die Parameter sind NICHT live geprüft (polymarket.com ist im lokalen Netz
gesperrt). Vor echtem Einsatz gegen docs.polymarket.com/trading/fees prüfen.

Manifold: keine Gebühren (Spielgeld).
"""
from __future__ import annotations

from dataclasses import dataclass

from paperbot.config import peak_fee_for


def polymarket_fee_per_share(price: float, category: str) -> float:
    if not 0.0 < price < 1.0:
        return 0.0
    rate = 4.0 * peak_fee_for(category)
    return price * rate * price * (1.0 - price)


@dataclass(frozen=True)
class FeeModel:
    kind: str = "polymarket"      # "polymarket" | "none"

    def per_share(self, price: float, category: str = "") -> float:
        if self.kind == "none":
            return 0.0
        if self.kind == "polymarket":
            return polymarket_fee_per_share(price, category)
        raise ValueError(f"unbekanntes Gebührenmodell: {self.kind!r}")

    def total(self, shares: float, price: float, category: str = "") -> float:
        return shares * self.per_share(price, category)


def fee_model_for(source: str) -> FeeModel:
    return FeeModel("none") if source in ("manifold", "synthetic") else FeeModel("polymarket")
