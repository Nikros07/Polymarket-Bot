"""
Schnittstelle für Marktdaten-Quellen. Alle Quellen sind NUR LESEND.

Implementierungen:
- paperbot.data.polymarket.PolymarketClient (Gamma + CLOB, öffentlich)
- paperbot.data.manifold.ManifoldClient (Spielgeld-Plattform, als Ersatz)
- paperbot.data.fake.FakeClient (Tests)
"""
from __future__ import annotations

from typing import List, Optional, Protocol, Tuple

from paperbot.models import Book, Market, PricePoint


class DataError(RuntimeError):
    """Daten fehlen oder sind unplausibel. Lieber laut scheitern als still raten."""


class MarketDataClient(Protocol):
    source: str

    def list_open_markets(self, limit: int = 200) -> List[Market]:
        """Offene, handelbare binäre Märkte, nach Aktivität sortiert."""
        ...

    def get_market(self, market_id: str) -> Optional[Market]:
        """Aktueller Stand eines Marktes (auch geschlossen/aufgelöst)."""
        ...

    def price_history(self, market: Market, start_ts: int, end_ts: int) -> List[PricePoint]:
        """YES-Preise im Zeitraum, aufsteigend nach Zeit."""
        ...

    def book(self, market: Market, side: str) -> Optional[Book]:
        """Orderbuch der Seite (Token). None, wenn nicht verfügbar."""
        ...


class HistoricalSource(Protocol):
    source: str

    def resolved_markets(self, limit: int) -> List[Tuple[Market, List[PricePoint]]]:
        """Aufgelöste binäre Märkte (outcome 0/1) mit vollständiger Preishistorie."""
        ...
