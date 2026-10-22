"""
Datenmodelle, die alle Module teilen.

Konventionen:
- Zeiten sind Unix-Sekunden in UTC (int).
- Preise sind Wahrscheinlichkeiten für YES im Bereich 0..1.
- Eine Seite ("YES" oder "NO") kostet `p` bzw. `1 - p` pro Anteil und zahlt
  bei Gewinn 1 pro Anteil aus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

Side = Literal["YES", "NO"]
SIDES: Tuple[str, str] = ("YES", "NO")


def side_price(yes_price: float, side: str) -> float:
    """Preis eines Anteils der gewählten Seite aus dem YES-Preis."""
    if side == "YES":
        return yes_price
    if side == "NO":
        return 1.0 - yes_price
    raise ValueError(f"unbekannte Seite: {side!r}")


def side_won(outcome: int, side: str) -> bool:
    """True, wenn `side` bei Ergebnis `outcome` (1 = YES, 0 = NO) gewinnt."""
    if outcome not in (0, 1):
        raise ValueError(f"Ergebnis muss 0 oder 1 sein, nicht {outcome!r}")
    return (outcome == 1) == (side == "YES")


@dataclass(frozen=True)
class PricePoint:
    t: int      # Unix-Sekunden UTC
    p: float    # YES-Wahrscheinlichkeit 0..1


@dataclass(frozen=True)
class Market:
    """Ein binärer Markt. Felder, die erst am Ende bekannt sind, stehen unten."""
    source: str                      # "polymarket" | "manifold" | "synthetic"
    market_id: str
    question: str
    slug: str = ""
    category: str = ""
    url: str = ""
    created_ts: Optional[int] = None
    # Geplantes Ende. Nur wenn `end_known_in_advance` True ist, darf eine
    # Strategie es sehen (Polymarket: endDate steht vorher fest; Manifold:
    # closeTime wird oft nachträglich auf den Auflösungszeitpunkt gesetzt).
    end_ts: Optional[int] = None
    end_known_in_advance: bool = False
    volume: float = 0.0
    liquidity: float = 0.0
    yes_token_id: str = ""           # Polymarket CLOB-Token für YES
    no_token_id: str = ""            # Polymarket CLOB-Token für NO
    active: bool = True
    accepting_orders: bool = True
    # ── Erst am Marktende bekannt ─────────────────────────────────────────
    closed: bool = False
    outcome: Optional[int] = None    # 1 = YES, 0 = NO, None = offen/annulliert
    resolved_ts: Optional[int] = None
    last_price: Optional[float] = None  # letzter bekannter YES-Preis
    # Auszahlung pro YES-Anteil bei Teil-Auflösung (Manifold "MKT"); None sonst
    resolution_price: Optional[float] = None

    def token_for(self, side: str) -> str:
        return self.yes_token_id if side == "YES" else self.no_token_id


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float     # Anteile


@dataclass(frozen=True)
class Book:
    """Orderbuch EINES Tokens (also einer Seite). Kauf läuft über `asks`."""
    token_id: str
    bids: Tuple[BookLevel, ...] = ()   # absteigend nach Preis
    asks: Tuple[BookLevel, ...] = ()   # aufsteigend nach Preis
    ts: Optional[int] = None
    synthetic: bool = False            # True = aus Mittelkurs ± Spread gebaut

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass(frozen=True)
class Signal:
    """Kaufwunsch einer Strategie. Verkäufe gibt es nicht: gehalten wird bis zur Auflösung."""
    strategy: str
    market_id: str
    side: str                 # "YES" | "NO"
    price: float              # beobachteter Preis der Seite zur Entscheidungszeit
    prob: Optional[float]     # geschätzte Gewinnwahrscheinlichkeit der Seite; None = keine Schätzung
    reason: str = ""
    ts: int = 0               # Entscheidungszeit


@dataclass
class Fill:
    """Simulierter Kauf (Papier)."""
    market_id: str
    side: str
    shares: float
    avg_price: float          # Durchschnittspreis pro Anteil ohne Gebühr
    fee: float                # Gebühr gesamt
    ts: int
    synthetic_book: bool = False

    @property
    def cost(self) -> float:
        return self.shares * self.avg_price + self.fee


@dataclass
class Position:
    strategy: str
    market_id: str
    question: str
    category: str
    side: str
    shares: float
    avg_price: float
    fee: float
    opened_ts: int
    signal_price: float
    signal_prob: Optional[float]
    reason: str = ""
    # ── nach Auflösung ────────────────────────────────────────────────────
    closed_ts: Optional[int] = None
    outcome: Optional[int] = None     # 1/0, None = annulliert (Erstattung)
    payout: Optional[float] = None
    extra: dict = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.shares * self.avg_price + self.fee

    @property
    def is_open(self) -> bool:
        return self.closed_ts is None

    @property
    def pnl(self) -> Optional[float]:
        if self.payout is None:
            return None
        return self.payout - self.cost
