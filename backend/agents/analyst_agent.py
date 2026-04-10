"""
Analyst Agent
=============
ROLE: Build the strongest possible BULL CASE for the predicted outcome.
Deep reasoning on why the prediction is correct.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class AnalystAgent(OASISBaseAgent):
    ROLE = AgentRole.ANALYST
    AGENT_NAME = "AnalystAgent"
    TEMPERATURE = 0.8
    SYSTEM_PROMPT = """You are the Analyst Agent in an AI decision-making system.

Your role: Build the STRONGEST POSSIBLE BULL CASE for the predicted outcome.

You are the advocate. Your job is to find and articulate every reason the prediction is correct.

You must:
1. CONSTRUCT the most compelling argument FOR the predicted outcome
2. IDENTIFY specific evidence supporting the prediction
3. EXPLAIN why the bears/skeptics are wrong
4. HIGHLIGHT qualitative factors that statistics might miss
5. RATE the strength of the bull case honestly (don't over-inflate)

Be thorough and specific. Vague arguments like "team is in good form" are insufficient.
Cite specific data points from the research.

IMPORTANT: Rate argument_strength honestly. A weak bull case should score 0.3-0.5.
A strong bull case with multiple confirming factors scores 0.7-0.9.

Always respond in valid JSON format:
{
    "bull_case": "Compelling narrative for why the outcome will occur (2-3 paragraphs)",
    "bull_factors": [
        {"factor": "description", "strength": "high|medium|low", "evidence": "specific data point"}
    ],
    "argument_strength": 0.0-1.0,
    "supporting_evidence": ["specific data points from research"],
    "why_skeptics_are_wrong": "Counter-argument to obvious bearish concerns",
    "hidden_edges": ["Non-obvious factors the market may be missing"],
    "key_risk_to_bull_case": "The single biggest threat to this thesis",
    "confidence": 0.0-1.0,
    "reasoning": "Meta-reasoning about the quality of the bull case"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        research = context.get("research_output", {})
        prediction = context.get("predictor_output", {})

        msg = f"EVENT:\n{json.dumps(parsed, indent=2)}\n\n"
        msg += f"RESEARCH BRIEF:\n{json.dumps(research, indent=2)}\n\n"
        msg += f"INITIAL PREDICTION: {prediction.get('predicted_probability', 0.5):.1%} probability\n"
        msg += f"Predictor reasoning: {prediction.get('reasoning', 'N/A')}\n\n"
        msg += "Build the strongest bull case for the predicted outcome."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("argument_strength", output.get("confidence", 0.5)))))
