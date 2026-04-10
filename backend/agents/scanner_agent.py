"""
Scanner Agent
=============
ROLE: Find and identify events from user queries or automatic feeds.
Extracts key entities and event metadata from natural language input.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class ScannerAgent(OASISBaseAgent):
    ROLE = AgentRole.SCANNER
    AGENT_NAME = "ScannerAgent"
    SYSTEM_PROMPT = """You are the Scanner Agent in an AI decision-making system.

Your role: Identify and extract event information from user queries or event feeds.

Given a user query or event description, you must:
1. Identify the TYPE of event (sports, prediction_market, financial, political, other)
2. Extract KEY ENTITIES (teams, players, organizations, locations)
3. Identify the OUTCOME being predicted
4. Determine the TIMEFRAME
5. Identify the MARKET TYPE (match result, over/under, player props, yes/no, etc.)
6. Estimate IMPLIED PROBABILITY if odds are mentioned (e.g., 2.0 odds → 50%, -150 → 60%)

IMPORTANT: Be precise. If something is ambiguous, flag it explicitly.

Always respond in valid JSON format:
{
    "event_type": "sports|prediction_market|financial|political|other",
    "sport": "football|basketball|tennis|...|null",
    "league": "string or null",
    "teams": ["team1", "team2"],
    "players": ["player1"],
    "outcome_description": "Clear description of what we're predicting",
    "timeframe": "when this will happen",
    "market_type": "match_result|over_under|player_prop|yes_no|other",
    "implied_probability": 0.0-1.0 or null,
    "ambiguities": ["list of unclear aspects"],
    "scan_confidence": 0.0-1.0,
    "reasoning": "Brief explanation of your scan"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        query = context.get("query", "")
        odds = context.get("market_odds", "")
        extra = context.get("context", "")

        msg = f"USER QUERY: {query}"
        if odds:
            msg += f"\n\nMARKET ODDS: {odds}"
        if extra:
            msg += f"\n\nADDITIONAL CONTEXT: {extra}"
        msg += "\n\nScan this query and return structured JSON."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        val = output.get("scan_confidence", output.get("confidence", 0.5))
        return float(max(0.0, min(1.0, val)))
