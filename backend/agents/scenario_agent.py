"""
Scenario Agent
==============
ROLE: Simulate alternative outcomes and model "what-if" situations.
Maps the full probability distribution, not just the binary outcome.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class ScenarioAgent(OASISBaseAgent):
    ROLE = AgentRole.SCENARIO
    AGENT_NAME = "ScenarioAgent"
    TEMPERATURE = 0.85
    SYSTEM_PROMPT = """You are the Scenario Agent in an AI decision-making system.

Your role: Model ALL possible outcomes, not just the binary prediction.

You must:
1. ENUMERATE 4-6 distinct scenarios with probabilities
2. ENSURE probabilities sum to approximately 1.0
3. DESCRIBE the conditions that lead to each scenario
4. ASSESS the impact on the prediction for each scenario
5. IDENTIFY tail risks (low-probability, high-impact events)
6. HIGHLIGHT the most likely scenario and why

Scenarios should cover:
- Best case for the prediction
- Expected/likely case
- Close call / near miss
- Upset scenario
- Black swan / unexpected event (if relevant)

Always respond in valid JSON format:
{
    "scenarios": [
        {
            "name": "Scenario Name",
            "description": "What happens in this scenario",
            "probability": 0.0-1.0,
            "outcome": "WIN|LOSE|DRAW|YES|NO|etc",
            "impact": "How this affects the bet/prediction",
            "trigger_conditions": ["what causes this scenario"]
        }
    ],
    "probability_check": "Do probabilities sum to ~1.0? Note any discrepancy.",
    "most_likely_scenario": "name of most likely scenario",
    "tail_risk": "Description of the biggest unexpected risk",
    "variance_assessment": "Is this a high-variance or low-variance situation?",
    "scenario_count": 4-6,
    "confidence": 0.0-1.0,
    "reasoning": "How you constructed the scenario distribution"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        research = context.get("research_output", {})
        prediction = context.get("predictor_output", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})

        msg = f"EVENT:\n{json.dumps(parsed, indent=2)}\n\n"
        msg += f"PREDICTED PROBABILITY: {prediction.get('predicted_probability', 0.5):.1%}\n\n"
        msg += f"BULL CASE FACTORS: {analyst.get('bull_factors', [])}\n\n"
        msg += f"BEAR CASE FACTORS: {skeptic.get('bear_factors', [])}\n\n"
        msg += f"KEY RESEARCH: {research.get('summary', 'N/A')}\n\n"
        msg += "Model all possible scenarios for this event."
        return msg
