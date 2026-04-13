"""
Research Service  (fixed + Tavily-optimised)
=============================================
Bug-fixes vs original:
  - `datetime` imported at top (was at bottom — NameError in production)
  - Single Tavily call per analysis (saves API credits)
  - `search_depth` and `max_results` driven by config
  - Per-session in-memory cache (TTL = RESEARCH_CACHE_TTL_SECONDS)
  - All exceptions individually caught + logged (no silent swallows)

Provider priority:
  1. Tavily   (best quality, cost-controlled)
  2. Serper   (Google Search fallback)
  3. Demo     (always works, no API needed)
"""
import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)


# ── Simple in-process cache ────────────────────────────────────────────────
_cache: Dict[str, Dict[str, Any]] = {}   # key → {results, ts}


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


def _get_cached(query: str) -> Optional[List[Dict[str, str]]]:
    key = _cache_key(query)
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < settings.RESEARCH_CACHE_TTL_SECONDS:
        logger.debug("research_cache_hit", query=query[:50])
        return entry["results"]
    return None


def _set_cache(query: str, results: List[Dict[str, str]]) -> None:
    _cache[_cache_key(query)] = {"results": results, "ts": time.time()}


# ── Service ────────────────────────────────────────────────────────────────

class ResearchService:
    """
    Gathers web intelligence for the Research Agent.
    Uses a single search call per analysis to stay cost-efficient.
    """

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=12.0)

    async def search(
        self,
        query: str,
        parsed_event: Optional[Dict[str, Any]] = None,
        max_results: int = None,
    ) -> List[Dict[str, str]]:
        """
        Return a list of search-result dicts:
          {"title", "url", "snippet", "source"}
        """
        max_results = max_results or settings.TAVILY_MAX_RESULTS
        search_query = self._build_query(query, parsed_event)

        # Check cache first
        cached = _get_cached(search_query)
        if cached is not None:
            return cached

        if settings.DEMO_MODE:
            return self._demo(query, parsed_event)

        # --- Try Tavily (primary) ---
        if settings.TAVILY_API_KEY:
            try:
                results = await self._tavily(search_query, max_results)
                if results:
                    _set_cache(search_query, results)
                    return results
            except Exception as exc:
                logger.warning("tavily_failed", error=str(exc))

        # --- Try Serper (fallback) ---
        if settings.SERPER_API_KEY:
            try:
                results = await self._serper(search_query, max_results)
                if results:
                    _set_cache(search_query, results)
                    return results
            except Exception as exc:
                logger.warning("serper_failed", error=str(exc))

        logger.warning("research_no_api_keys", fallback="demo_data")
        return self._demo(query, parsed_event)

    # ── Providers ─────────────────────────────────────────────────────────

    async def _tavily(
        self, query: str, max_results: int
    ) -> List[Dict[str, str]]:
        """
        Single Tavily call with cost-control settings.
        include_answer=True gives a free text summary at no extra credit cost.
        search_depth="basic" = 1 credit; "advanced" = 2 credits.
        """
        payload = {
            "api_key":       settings.TAVILY_API_KEY,
            "query":         query,
            "max_results":   max_results,
            "search_depth":  settings.TAVILY_SEARCH_DEPTH,
            "include_answer": True,
            "include_raw_content": False,
        }
        resp = await self._http.post("https://api.tavily.com/search", json=payload)
        resp.raise_for_status()
        data = resp.json()

        results: List[Dict[str, str]] = []

        # Prepend the AI answer as a synthetic "source"
        if data.get("answer"):
            results.append({
                "title":  "Tavily AI Summary",
                "url":    "",
                "snippet": data["answer"][:600],
                "source": "tavily_answer",
            })

        for r in data.get("results", [])[:max_results]:
            results.append({
                "title":  r.get("title", ""),
                "url":    r.get("url", ""),
                "snippet": (r.get("content") or "")[:400],
                "source": "tavily",
                "score":  str(r.get("score", "")),
            })

        logger.info("tavily_ok", results=len(results))
        return results

    async def _serper(
        self, query: str, max_results: int
    ) -> List[Dict[str, str]]:
        """Google Search via Serper.dev."""
        resp = await self._http.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

        results = [
            {"title": i.get("title", ""), "url": i.get("link", ""),
             "snippet": i.get("snippet", ""), "source": "serper"}
            for i in data.get("organic", [])[:max_results]
        ]
        for i in data.get("news", [])[:2]:
            results.append({"title": i.get("title", ""), "url": i.get("link", ""),
                            "snippet": i.get("snippet", ""), "source": "serper_news",
                            "date": i.get("date", "")})
        logger.info("serper_ok", results=len(results))
        return results

    # ── Query builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_query(query: str, parsed: Optional[Dict[str, Any]]) -> str:
        if not parsed:
            return f"{query} prediction statistics {datetime.now().year}"

        parts: List[str] = []
        teams = parsed.get("teams") or []
        if isinstance(teams, list) and teams:
            parts.append(" vs ".join(str(t) for t in teams[:2]))
        elif parsed.get("primary_entity"):
            parts.append(str(parsed["primary_entity"]))

        for key in ("sport", "league"):
            val = parsed.get(key)
            if val:
                parts.append(str(val))

        tf = parsed.get("timeframe_description") or parsed.get("timeframe", "")
        if tf and len(tf) < 40:
            parts.append(tf)

        parts.append(f"form stats prediction {datetime.now().year}")
        return " ".join(parts) if parts else f"{query} analysis {datetime.now().year}"

    @staticmethod
    def build_feature_context(query: str, parsed: Optional[Dict[str, Any]]) -> str:
        """Build a supplemental research context string for the ResearchAgent.

        This provides structured prompting hints so the agent focuses on the
        quantitative features that matter most for edge calculation:
        injuries, fatigue, motivation, and head-to-head record.

        The context is injected into env["research_feature_context"] and
        included in the ResearchAgent's user message.
        """
        if not parsed:
            return ""

        year = datetime.now().year
        teams = parsed.get("teams") or []
        team_a = teams[0] if len(teams) > 0 else parsed.get("primary_entity", "")
        team_b = teams[1] if len(teams) > 1 else parsed.get("secondary_entity", "")
        sport  = parsed.get("sport", "")

        hints: List[str] = []

        if team_a:
            hints.append(
                f"Injury/suspension check: '{team_a} injury suspended unavailable {year}'"
            )
            hints.append(
                f"Fatigue/schedule: '{team_a} fixtures schedule rest days {year}'"
            )
            hints.append(
                f"Motivation/context: '{team_a} standings {sport} motivation relegation title {year}'"
            )

        if team_b:
            hints.append(
                f"Opponent injury check: '{team_b} injury suspended unavailable {year}'"
            )

        if team_a and team_b:
            hints.append(
                f"H2H record: '{team_a} vs {team_b} head to head history {sport}'"
            )
            hints.append(
                f"Venue/travel: '{team_a} home away record {sport} {year}'"
            )

        if not hints:
            return ""

        return (
            "KEY RESEARCH ANGLES (search for these specifically):\n"
            + "\n".join(f"  • {h}" for h in hints)
        )

    # ── Demo data ──────────────────────────────────────────────────────────

    @staticmethod
    def _demo(query: str, parsed: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
        teams = []
        if parsed:
            t = parsed.get("teams", [])
            if isinstance(t, list):
                teams = t
        a = teams[0] if len(teams) > 0 else "Team A"
        b = teams[1] if len(teams) > 1 else "Team B"
        return [
            {"title": f"{a} vs {b} — Match Preview",
             "url": "", "source": "demo",
             "snippet": f"{a} enter in strong form (4W-1D last 5). {b} have won just 2 of 8 away games this season."},
            {"title": f"{a} Team News & Injuries",
             "url": "", "source": "demo",
             "snippet": f"No major injury concerns for {a}. Key striker returns from suspension and is expected to start."},
            {"title": f"Head-to-Head: {a} vs {b}",
             "url": "", "source": "demo",
             "snippet": f"In last 10 meetings: {a} 6W, {b} 2W, 2D. Home record strongly favours {a}."},
            {"title": f"Odds & Market Analysis",
             "url": "", "source": "demo",
             "snippet": f"Bookmakers have {a} at 1.80 (56% implied). Slight line movement toward {a} in last 48h."},
            {"title": f"{a} Season Statistics",
             "url": "", "source": "demo",
             "snippet": f"{a}: 14W-3D-3L this season, 2.1 goals/game scored, 0.8 conceded at home. Strong set-piece record."},
        ]

    async def close(self):
        await self._http.aclose()


# ── Singleton ──────────────────────────────────────────────────────────────
_research_svc: Optional[ResearchService] = None


def get_research_service() -> ResearchService:
    global _research_svc
    if _research_svc is None:
        _research_svc = ResearchService()
    return _research_svc
