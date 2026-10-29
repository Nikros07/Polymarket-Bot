"""
Gebührenmodell.

Polymarket (Taker, seit 2026 je Kategorie, Recherche-Stand 2026-10-22):
    fee = Anteile × Preis × feeRate × (Preis × (1 − Preis))
mit feeRate = 4 × Peak-Rate, damit bei Preis 0,5 genau die Peak-Rate pro
Euro Einsatz anfällt. Bei 95 Cent ist die Gebühr dadurch sehr klein.
Die Parameter sind NICHT live geprüft (polymarket.com ist im lokalen Netz
gesperrt). Vor echtem Einsatz gegen docs.polymarket.com/trading/fees prüfen.

Kalshi (Taker): fee = ceil_cent(0,07 × Anteile × P × (1 − P)) je Order.
Quelle: Bürgi, Deng, Whelan (2026) und /series (fee_type "quadratic").
Maker-Gebühren (seit 04/2025 bei manchen Serien) spielen keine Rolle, weil der
Papier-Bot nur sofort gegen das Orderbuch kauft.

Manifold: keine Gebühren (Spielgeld).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from paperbot.config import peak_fee_for

KALSHI_TAKER_RATE = 0.07


def polymarket_fee_per_share(price: float, category: str) -> float:
    if not 0.0 < price < 1.0:
        return 0.0
    rate = 4.0 * peak_fee_for(category)
    return price * rate * price * (1.0 - price)


def kalshi_fee_per_share(price: float) -> float:
    """Kalshi-Taker: 0,07 · P · (1 − P) pro Kontrakt (Serien mit fee_multiplier 1,
    das sind laut /series 15.211 von rund 15.400). Ohne Cent-Aufrundung."""
    if not 0.0 < price < 1.0:
        return 0.0
    return KALSHI_TAKER_RATE * price * (1.0 - price)


@dataclass(frozen=True)
class FeeModel:
    kind: str = "polymarket"      # "polymarket" | "kalshi" | "none"

    def per_share(self, price: float, category: str = "") -> float:
        if self.kind == "none":
            return 0.0
        if self.kind == "polymarket":
            return polymarket_fee_per_share(price, category)
        if self.kind == "kalshi":
            return kalshi_fee_per_share(price)
        raise ValueError(f"unbekanntes Gebührenmodell: {self.kind!r}")

    def total(self, shares: float, price: float, category: str = "") -> float:
        return self.round_total(shares * self.per_share(price, category))

    def round_total(self, fee: float) -> float:
        """Kalshi rundet die Gebühr je Order auf den nächsten Cent auf. Bei kleinen
        Papier-Orders (5 Kontrakte) macht das einen spürbaren Unterschied."""
        if self.kind == "kalshi" and fee > 0:
            return math.ceil(fee * 100 - 1e-9) / 100
        return fee


def fee_model_for(source: str) -> FeeModel:
    if source in ("manifold", "synthetic"):
        return FeeModel("none")
    if source.startswith("kalshi"):
        return FeeModel("kalshi")
    return FeeModel("polymarket")
