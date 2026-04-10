"""
Research Agent
==============
ROLE: Gather, synthesize, and evaluate relevant context, statistics,
news, and signals for the event being analyzed.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class ResearchAgent(OASISBaseAgent):
    ROLE = AgentRole.RESEARCH
    AGENT_NAME = "ResearchAgent"
    SYSTEM_PROMPT = """You are the Research Agent in an AI decision-making system.

Your role: Synthesize ALL available research data into a comprehensive intelligence brief.

You receive:
- The structured event specification
- Raw research data (web search results, statistics, news)

You must:
1. EXTRACT key facts relevant to predicting the outcome
2. IDENTIFY recent news that could impact the event
3. COMPILE relevant statistics (form, head-to-head, trends)
4. ASSESS market context if available
5. RATE the quality and completeness of the available data
6. FLAG missing information that would improve the analysis

Be objective. Do NOT make predictions. Just synthesize the information.

Always respond in valid JSON format:
{
    "key_facts": ["fact1", "fact2", "..."],
    "recent_news": ["news1", "news2", "..."],
    "statistics": {
        "recent_form": "description",
        "head_to_head": "description",
        "home_away_splits": "description",
        "injuries_suspensions": "description",
        "other": {}
    },
    "market_signals": {
        "odds_movement": "description or null",
        "sharp_money_indicators": "description or null",
        "public_sentiment": "description or null"
    },
    "data_quality_score": 0.0-1.0,
    "missing_information": ["what we don't know"],
    "summary": "2-3 sentence research brief",
    "confidence": 0.0-1.0,
    "reasoning": "Assessment of information quality and completeness"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        research_data = context.get("research_data", {})
        raw_sources = context.get("raw_sources", [])

        msg = f"EVENT SPECIFICATION:\n{json.dumps(parsed, indent=2)}\n\n"

        if research_data:
            msg += f"RAW RESEARCH DATA:\n{json.dumps(research_data, indent=2)}\n\n"

        if raw_sources:
            msg += "SEARCH RESULTS:\n"
            for i, source in enumerate(raw_sources[:8], 1):
                msg += f"\n[Source {i}] {source.get('title', 'N/A')}\n"
                msg += f"URL: {source.get('url', 'N/A')}\n"
                msg += f"Snippet: {source.get('snippet', 'N/A')}\n"

        msg += "\nSynthesize this research into a comprehensive intelligence brief."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        val = output.get("data_quality_score", output.get("confidence", 0.5))
        return float(max(0.0, min(1.0, val)))
