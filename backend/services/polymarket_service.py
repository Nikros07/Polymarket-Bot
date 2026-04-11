"""
Polymarket Service
==================
Searches and fetches prediction markets from Polymarket via the
public Gamma Markets API — no private key required for reading.

Endpoints used:
  GET https://gamma-api.polymarket.com/markets
    ?search=<query>&active=true&limit=<n>&closed=false

Maps sports-betting bet-types to Polymarket search queries so the
user can find the relevant market automatically.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)


# ── Bet-type → Polymarket search hint ─────────────────────────────────────
BET_TYPE_HINTS: Dict[str, str] = {
    "match_winner":       "win",
    "over_under":         "goals over under",
    "btts":               "both teams score",
    "asian_handicap":     "handicap",
    "double_chance":      "draw or win",
    "clean_sheet":        "clean sheet",
    "correct_score":      "score",
    "tournament_winner":  "champion winner",
    "player_prop":        "score goal",
    "outright":           "winner champion",
}


class PolymarketService:
    """
    Reads public Polymarket markets — no API key needed.
    Falls back to empty list on any network / parse error.
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "PolymarketBot/1.0"},
        )

    # ── Public API ─────────────────────────────────────────────────────────

    async def search_markets(
        self,
        query: str,
        bet_type: str = "match_winner",
        limit: int = None,
    ) -> List[Dict[str, Any]]:
        """
        Search Polymarket for prediction markets related to `query`.
        Returns a list of cleaned market dicts, sorted by volume desc.
        """
        limit = limit or settings.POLYMARKET_MAX_MARKETS
        search_query = self._build_search_query(query, bet_type)

        try:
            params = {
                "search":  search_query,
                "active":  "true",
                "closed":  "false",
                "limit":   limit * 2,        # fetch more, filter client-side
                "order":   "volumeNum",
                "ascending": "false",
            }
            url = f"{self.BASE_URL}/markets?{urlencode(params)}"
            logger.info("polymarket_search", query=search_query[:60])

            resp = await self._client.get(url)
            resp.raise_for_status()
            raw: List[Dict] = resp.json()

            markets = [self._clean_market(m) for m in raw if self._is_usable(m)]
            markets = sorted(markets, key=lambda m: m["volume"], reverse=True)
            result   = markets[:limit]

            logger.info("polymarket_found", count=len(result))
            return result

        except Exception as exc:
            logger.warning("polymarket_search_failed", error=str(exc))
            return []

    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by its conditionId or slug."""
        try:
            url  = f"{self.BASE_URL}/markets/{market_id}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            return self._clean_market(resp.json())
        except Exception as exc:
            logger.warning("polymarket_get_market_failed", id=market_id, error=str(exc))
            return None

    async def close(self):
        await self._client.aclose()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_search_query(self, query: str, bet_type: str) -> str:
        hint = BET_TYPE_HINTS.get(bet_type, "")
        base = query.strip()
        # Remove generic trailing words to keep it tight
        for suffix in ["?", "win their next game", "win the next match"]:
            base = base.replace(suffix, "").strip()
        if hint and hint.lower() not in base.lower():
            return f"{base} {hint}".strip()
        return base

    @staticmethod
    def _is_usable(market: Dict) -> bool:
        """Filter out markets with no price data or closed markets."""
        try:
            prices = market.get("outcomePrices") or market.get("bestAsk")
            if not prices:
                return False
            if market.get("closed") or not market.get("active", True):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _clean_market(raw: Dict) -> Dict[str, Any]:
        """Normalise a raw Gamma API market dict."""
        # Parse outcome prices (can be a JSON string or a list)
        raw_prices = raw.get("outcomePrices", "[]")
        if isinstance(raw_prices, str):
            try:
                prices = [float(p) for p in json.loads(raw_prices)]
            except Exception:
                prices = []
        else:
            prices = [float(p) for p in raw_prices]

        # Parse outcomes list
        raw_outcomes = raw.get("outcomes", '["Yes","No"]')
        if isinstance(raw_outcomes, str):
            try:
                outcomes = json.loads(raw_outcomes)
            except Exception:
                outcomes = ["Yes", "No"]
        else:
            outcomes = raw_outcomes

        # Yes / No probability (first outcome = Yes by convention)
        yes_prob = prices[0] if prices else None
        no_prob  = prices[1] if len(prices) > 1 else (1 - yes_prob if yes_prob else None)

        # Volume
        try:
            volume = float(raw.get("volumeNum") or raw.get("volume") or 0)
        except Exception:
            volume = 0.0

        # End date
        end_date_raw = raw.get("endDate") or raw.get("end_date_iso")
        end_date = end_date_raw[:10] if end_date_raw else None

        return {
            "id":           raw.get("id") or raw.get("conditionId", ""),
            "question":     raw.get("question", "Unknown market"),
            "slug":         raw.get("slug", ""),
            "description":  (raw.get("description") or "")[:300],
            "outcomes":     outcomes,
            "prices":       prices,
            "yes_prob":     round(yes_prob, 4) if yes_prob is not None else None,
            "no_prob":      round(no_prob,  4) if no_prob  is not None else None,
            "volume_usd":   round(volume, 2),
            "end_date":     end_date,
            "url":          f"https://polymarket.com/event/{raw.get('slug', '')}",
            "active":       bool(raw.get("active", True)),
        }


# ── Singleton ──────────────────────────────────────────────────────────────
_poly_service: Optional[PolymarketService] = None

def get_polymarket_service() -> PolymarketService:
    global _poly_service
    if _poly_service is None:
        _poly_service = PolymarketService()
    return _poly_service
