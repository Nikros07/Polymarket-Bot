"""
Künstliche Märkte mit bekannter Wahrheit — für den Selbsttest des Prüfstands.

- fair: Der Preis ist die wahre Wahrscheinlichkeit plus Rauschen. Keine
  Strategie darf hier einen belegten Vorteil finden.
- planted: Favoriten (wahre W. ≥ 0,85) werden `bias` zu billig gehandelt.
  Der Prüfstand muss diesen eingebauten Vorteil finden.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from paperbot.models import Market, PricePoint

DAY = 86_400
T0 = 1_700_000_000


def make_dataset(n: int = 2000, *, bias: float = 0.0, seed: int = 0, days: int = 20,
                 noise: float = 0.0) -> List[Tuple[Market, List[PricePoint]]]:
    """noise > 0 macht den Preis zu einer echten Fehlbewertung (Rauschen um die Wahrheit),
    die eine Kalibrierungskurve ausnutzen kann. Für den fairen Selbsttest daher 0."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        q = float(rng.beta(0.6, 0.6))                      # viele klare Favoriten
        outcome = int(rng.random() < q)
        created = T0 + i * 3_600 * 6
        end = created + days * DAY
        shift = 0.0
        if q >= 0.85:
            shift = -bias          # YES-Favorit zu billig
        elif q <= 0.15:
            shift = +bias          # NO-Favorit zu billig (YES zu teuer)
        pts = []
        for d in range(days + 1):
            p = float(np.clip(q + shift + rng.normal(0, noise), 0.01, 0.99))
            pts.append(PricePoint(created + d * DAY - 60, p))
        m = Market(
            source="synthetic", market_id=f"syn-{seed}-{i}", question=f"Synthetisch {i}",
            category="synthetic", created_ts=created, end_ts=end, end_known_in_advance=True,
            volume=10_000.0, liquidity=5_000.0, closed=True, outcome=outcome, resolved_ts=end,
            last_price=float(outcome),
        )
        out.append((m, pts))
    return out
