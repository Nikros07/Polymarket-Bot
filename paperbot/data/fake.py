"""Speicher-Datenquelle für Tests und Demos (kein Netzwerk)."""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from paperbot.models import Book, BookLevel, Market, PricePoint, side_price


class FakeClient:
    def __init__(self, markets: List[Market], histories: Optional[Dict[str, List[PricePoint]]] = None,
                 half_spread: float = 0.01, depth: float = 1_000.0, source: str = "fake"):
        self.source = source
        self.markets: Dict[str, Market] = {m.market_id: m for m in markets}
        self.histories = histories or {}
        self.half_spread = half_spread
        self.depth = depth
        self.calls: List[str] = []

    def set_market(self, market_id: str, **changes) -> None:
        self.markets[market_id] = replace(self.markets[market_id], **changes)

    def list_open_markets(self, limit: int = 200) -> List[Market]:
        self.calls.append("list")
        return [m for m in self.markets.values() if not m.closed][:limit]

    def get_market(self, market_id: str) -> Optional[Market]:
        self.calls.append(f"get:{market_id}")
        return self.markets.get(market_id)

    def price_history(self, market: Market, start_ts: int, end_ts: int) -> List[PricePoint]:
        self.calls.append(f"hist:{market.market_id}")
        return [p for p in self.histories.get(market.market_id, []) if start_ts <= p.t <= end_ts]

    def book(self, market: Market, side: str) -> Optional[Book]:
        self.calls.append(f"book:{market.market_id}:{side}")
        if market.last_price is None:
            return None
        s = side_price(market.last_price, side)
        return Book(token_id=f"{market.market_id}:{side}",
                    bids=(BookLevel(round(max(0.001, s - self.half_spread), 4), self.depth),),
                    asks=(BookLevel(round(min(0.999, s + self.half_spread), 4), self.depth),),
                    synthetic=True)
