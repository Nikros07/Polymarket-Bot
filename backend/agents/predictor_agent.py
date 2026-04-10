"""
Predictor Agent
===============
ROLE: Output an initial probability estimate based on research data.
This is the first numerical prediction — subsequent agents will challenge it.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class PredictorAgent(OASISBaseAgent):
    ROLE = AgentRole.PREDICTOR
    AGENT_NAME = "PredictorAgent"
    TEMPERATURE = 0.5  # Lower temp for more consistent probability estimates
    SYSTEM_PROMPT = """You are the Predictor Agent in an AI decision-making system.

Your role: Produce an initial probability estimate for the predicted outcome.

You receive the research intelligence brief and must:
1. ESTIMATE the probability of the specified outcome (0.0 = impossible, 1.0 = certain)
2. IDENTIFY the key factors driving your estimate
3. LIST factors that could push the probability higher or lower
4. QUANTIFY your uncertainty range (e.g., "I estimate 62% ± 8%")
5. COMPARE to implied market probability if available

Be precise. A probability of 0.50 means "I have no edge." Only deviate from 0.50 if the data justifies it.

CALIBRATION GUIDE:
- 0.90+ = Near certain (very strong evidence)
- 0.70-0.89 = Strong lean (solid evidence)
- 0.55-0.69 = Moderate lean (some evidence)
- 0.45-0.54 = Toss-up (insufficient data to differentiate)
- <0.45 = Lean against (evidence points to opposite outcome)

Always respond in valid JSON format:
{
    "predicted_probability": 0.0-1.0,
    "uncertainty_range": {"low": 0.0, "high": 1.0},
    "implied_market_probability": null_or_float,
    "estimated_edge": null_or_float,
    "key_factors": ["factor1", "factor2"],
    "upside_factors": ["what could push probability higher"],
    "downside_factors": ["what could push probability lower"],
    "base_rate": "What is the historical base rate for this type of outcome?",
    "reasoning": "Step-by-step probability reasoning",
    "confidence": 0.0-1.0
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        research = context.get("research_output", {})

        msg = f"EVENT TO PREDICT:\n{json.dumps(parsed, indent=2)}\n\n"
        msg += f"RESEARCH BRIEF:\n{json.dumps(research, indent=2)}\n\n"

        implied_prob = parsed.get("implied_probability") or context.get("implied_probability")
        if implied_prob:
            msg += f"MARKET IMPLIED PROBABILITY: {implied_prob:.1%}\n\n"

        msg += "Estimate the probability of the predicted outcome."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("confidence", 0.5))))
