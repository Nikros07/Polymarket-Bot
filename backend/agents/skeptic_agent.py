"""
Skeptic Agent
=============
ROLE: Challenge the prediction. Find flaws, risks, and blind spots.
Disagreement is required — the skeptic MUST push back.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class SkepticAgent(OASISBaseAgent):
    ROLE = AgentRole.SKEPTIC
    AGENT_NAME = "SkepticAgent"
    TEMPERATURE = 0.9  # Higher temp to encourage creative counter-arguments
    SYSTEM_PROMPT = """You are the Skeptic Agent in an AI decision-making system.

Your role: CHALLENGE the prediction. Find every flaw, risk, and blind spot.

You are the devil's advocate. Your MANDATE is to disagree with the bull case and find reasons the prediction could be WRONG.

You must:
1. IDENTIFY flaws in the analyst's reasoning
2. FIND overlooked risks and negative factors
3. QUESTION the data quality and sample sizes
4. CONSIDER what could go wrong (upset scenarios)
5. EVALUATE whether the market price already captures the edge
6. LOOK FOR cognitive biases in the analysis (recency bias, home team bias, etc.)

CRITICAL RULE: You MUST find at least 3 genuine concerns. "Everything looks fine" is NOT acceptable.
Your job is adversarial — if the bull case is strong, you must find the cracks in it.

Always respond in valid JSON format:
{
    "bear_case": "Compelling narrative for why the prediction could be WRONG (2-3 paragraphs)",
    "bear_factors": [
        {"factor": "description", "severity": "high|medium|low", "evidence": "specific concern"}
    ],
    "counter_argument_strength": 0.0-1.0,
    "flaws_in_analysis": ["specific logical or factual issues with the bull case"],
    "risks": ["concrete risk factors that could cause the prediction to fail"],
    "market_efficiency_concern": "Has the market already priced in this edge?",
    "cognitive_biases_detected": ["list of possible biases in the analysis"],
    "upset_probability": 0.0-1.0,
    "key_question_unanswered": "The most important unknown that changes everything",
    "confidence": 0.0-1.0,
    "reasoning": "Why these counter-arguments are valid and important"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        research = context.get("research_output", {})
        prediction = context.get("predictor_output", {})
        analyst = context.get("analyst_output", {})

        msg = f"EVENT:\n{json.dumps(parsed, indent=2)}\n\n"
        msg += f"RESEARCH BRIEF:\n{json.dumps(research, indent=2)}\n\n"
        msg += f"PREDICTION: {prediction.get('predicted_probability', 0.5):.1%} probability\n\n"
        msg += f"ANALYST BULL CASE:\n{analyst.get('bull_case', 'N/A')}\n"
        msg += f"Analyst factors: {analyst.get('bull_factors', [])}\n"
        msg += f"Argument strength: {analyst.get('argument_strength', 0.5)}\n\n"
        msg += "Challenge this prediction. Find every flaw and risk. Do NOT simply agree."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        # Counter-argument strength: higher means the skeptic found more issues
        return float(max(0.0, min(1.0, output.get("counter_argument_strength", output.get("confidence", 0.5)))))
