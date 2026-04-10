"""
Research Service
================
Handles external data gathering for the Research Agent.
Supports: Serper.dev (Google Search), Tavily AI Search, and fallback mock data.

The Research Agent synthesizes this raw data into intelligence.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)


class ResearchService:
    """
    Gathers research data from external sources.
    Falls back gracefully when API keys are not configured.
    """

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=15.0)

    async def search(
        self,
        query: str,
        parsed_event: Optional[Dict[str, Any]] = None,
        max_results: int = None,
    ) -> List[Dict[str, str]]:
        """
        Main search method. Tries providers in order:
        1. Serper.dev (Google Search API)
        2. Tavily AI Search
        3. Mock/demo data
        """
        max_results = max_results or settings.MAX_RESEARCH_SOURCES
        search_query = self._build_search_query(query, parsed_event)

        logger.info("research_search_start", query=search_query[:80])

        if settings.DEMO_MODE:
            return self._demo_results(query, parsed_event)

        # Try Serper first
        if settings.SERPER_API_KEY:
            try:
                results = await self._serper_search(search_query, max_results)
                if results:
                    logger.info("research_source", source="serper", count=len(results))
                    return results
            except Exception as e:
                logger.warning("serper_search_failed", error=str(e))

        # Try Tavily
        if settings.TAVILY_API_KEY:
            try:
                results = await self._tavily_search(search_query, max_results)
                if results:
                    logger.info("research_source", source="tavily", count=len(results))
                    return results
            except Exception as e:
                logger.warning("tavily_search_failed", error=str(e))

        # Fallback
        logger.warning("research_using_demo_data", reason="no_api_keys")
        return self._demo_results(query, parsed_event)

    # ── Search Providers ───────────────────────────────────────────────────

    async def _serper_search(
        self, query: str, max_results: int
    ) -> List[Dict[str, str]]:
        """Search via Serper.dev Google Search API."""
        headers = {
            "X-API-KEY": settings.SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": max_results}

        response = await self.http.post(
            "https://google.serper.dev/search",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("organic", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": "serper",
            })

        # Also include news if available
        for item in data.get("news", [])[:2]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": "serper_news",
                "date": item.get("date", ""),
            })

        return results

    async def _tavily_search(
        self, query: str, max_results: int
    ) -> List[Dict[str, str]]:
        """Search via Tavily AI Search API."""
        payload = {
            "api_key": settings.TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "search_depth": "advanced",
        }

        response = await self.http.post(
            "https://api.tavily.com/search",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:400],
                "source": "tavily",
                "score": str(r.get("score", "")),
            }
            for r in data.get("results", [])[:max_results]
        ]

    # ── Search Query Builder ───────────────────────────────────────────────

    def _build_search_query(
        self,
        query: str,
        parsed_event: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build an optimized search query from the user input."""
        if not parsed_event:
            return f"{query} prediction odds analysis"

        parts = []

        # Add teams/entities
        teams = parsed_event.get("teams", []) or parsed_event.get("primary_entity")
        if teams:
            if isinstance(teams, list) and teams:
                parts.append(" vs ".join(teams[:2]))
            elif isinstance(teams, str):
                parts.append(teams)

        # Add sport/league context
        sport = parsed_event.get("sport")
        league = parsed_event.get("league")
        if sport:
            parts.append(sport)
        if league:
            parts.append(league)

        # Add timeframe
        timeframe = parsed_event.get("timeframe_description", parsed_event.get("timeframe", ""))
        if timeframe and len(timeframe) < 50:
            parts.append(timeframe)

        # Add analytical focus
        parts.append("form stats prediction")

        base = " ".join(parts) if parts else query
        return f"{base} {datetime.now().year}"

    # ── Demo Data ──────────────────────────────────────────────────────────

    def _demo_results(
        self,
        query: str,
        parsed_event: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Return plausible demo research data without API calls."""
        teams = []
        if parsed_event:
            t = parsed_event.get("teams", [])
            if isinstance(t, list):
                teams = t

        team_a = teams[0] if len(teams) > 0 else "Team A"
        team_b = teams[1] if len(teams) > 1 else "Team B"

        return [
            {
                "title": f"{team_a} vs {team_b} — Match Preview and Prediction",
                "url": "https://example.com/preview",
                "snippet": (
                    f"{team_a} enter this fixture in strong form, having won 4 of their last 5 matches. "
                    f"{team_b} have struggled on the road this season with just 2 wins in 8 away games."
                ),
                "source": "demo",
            },
            {
                "title": f"{team_a} Team News and Injury Report",
                "url": "https://example.com/team-news",
                "snippet": (
                    f"No major injury concerns for {team_a} ahead of the fixture. "
                    f"Key striker returns from suspension and is expected to start."
                ),
                "source": "demo",
            },
            {
                "title": f"Head-to-Head: {team_a} vs {team_b} Historical Record",
                "url": "https://example.com/h2h",
                "snippet": (
                    f"In the last 10 meetings, {team_a} have won 6, {team_b} have won 2, "
                    f"with 2 draws. Home record strongly favors {team_a}."
                ),
                "source": "demo",
            },
            {
                "title": f"Odds and Market Analysis — {team_a} vs {team_b}",
                "url": "https://example.com/odds",
                "snippet": (
                    f"Bookmakers have {team_a} as slight favorites at 1.80 (56% implied probability). "
                    f"Line movement has been toward {team_a} in the past 48 hours."
                ),
                "source": "demo",
            },
            {
                "title": f"{team_a} Season Statistics and Form Guide",
                "url": "https://example.com/stats",
                "snippet": (
                    f"{team_a}: 14W-3D-3L this season, scoring 2.1 goals per game. "
                    f"Defense conceding just 0.8 goals per game at home. Strong set piece record."
                ),
                "source": "demo",
            },
        ]

    async def close(self):
        await self.http.aclose()


from datetime import datetime

# Singleton
_research_service: Optional[ResearchService] = None


def get_research_service() -> ResearchService:
    global _research_service
    if _research_service is None:
        _research_service = ResearchService()
    return _research_service
