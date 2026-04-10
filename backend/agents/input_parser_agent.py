"""
Input Parser Agent
==================
ROLE: Convert raw scanner output and user intent into a precise,
structured event specification ready for downstream analysis.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class InputParserAgent(OASISBaseAgent):
    ROLE = AgentRole.INPUT_PARSER
    AGENT_NAME = "InputParserAgent"
    SYSTEM_PROMPT = """You are the Input Parser Agent in an AI decision-making system.

Your role: Transform raw scanner data into a precise, unambiguous event specification.

You receive the scanner's output and must:
1. NORMALIZE entity names (correct spelling, full names)
2. RESOLVE ambiguities (pick the most likely interpretation, explain why)
3. STRUCTURE the prediction question precisely
4. IDENTIFY what data would be needed for a good analysis
5. FLAG any parsing issues that downstream agents should be aware of

Your output becomes the canonical reference for all other agents.

Always respond in valid JSON format:
{
    "canonical_query": "The precise, unambiguous question being analyzed",
    "event_type": "sports|prediction_market|financial|political|other",
    "sport": "string or null",
    "league": "string or null",
    "primary_entity": "main team/player/organization",
    "secondary_entity": "opponent/comparison entity or null",
    "prediction_target": "exactly what outcome we are predicting",
    "timeframe_description": "clear timeframe",
    "market_type": "match_result|over_under|player_prop|yes_no|other",
    "implied_probability": null_or_float,
    "data_requirements": ["what research is needed"],
    "parsing_issues": ["any unresolved ambiguities"],
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of parsing decisions"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        scanner_output = context.get("scanner_output", {})
        query = context.get("query", "")

        msg = f"ORIGINAL QUERY: {query}\n\n"
        msg += f"SCANNER OUTPUT:\n{json.dumps(scanner_output, indent=2)}\n\n"
        msg += "Parse this into a precise, canonical event specification."
        return msg
