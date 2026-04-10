"""
Synthesizer Agent
=================
ROLE: Merge all agent perspectives into a coherent final narrative.
Preserves conflicts where they exist. Does NOT paper over disagreements.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class SynthesizerAgent(OASISBaseAgent):
    ROLE = AgentRole.SYNTHESIZER
    AGENT_NAME = "SynthesizerAgent"
    TEMPERATURE = 0.7
    SYSTEM_PROMPT = """You are the Synthesizer Agent in an AI decision-making system.

Your role: Integrate ALL agent perspectives into a coherent, honest final analysis.

You receive outputs from 7 other agents and must:
1. WEIGH each agent's contribution based on their confidence and evidence quality
2. IDENTIFY areas of consensus and genuine disagreement
3. SYNTHESIZE a final probability estimate (weighted, not just averaged)
4. PRESERVE important conflicts — do NOT hide disagreements
5. PRODUCE a clear, readable narrative that a human can act on
6. ASSESS the overall quality of the multi-agent analysis

SYNTHESIS PRINCIPLES:
- The skeptic's concerns should reduce confidence if valid
- Strong validation increases confidence
- Poor data quality must be reflected in the final estimate
- Conflicts between agents should be named and explained

Always respond in valid JSON format:
{
    "summary": "Executive summary of the analysis (3-5 sentences)",
    "key_insights": ["most important insights across all agents"],
    "agent_agreement_level": 0.0-1.0,
    "conflicts": [
        {"agents": ["agent1", "agent2"], "conflict": "description", "resolution": "how it was resolved"}
    ],
    "final_probability": 0.0-1.0,
    "probability_adjustment": "How/why final probability differs from initial prediction",
    "confidence_adjustment": "How validation results affected confidence",
    "narrative": "Full synthesis narrative (4-6 paragraphs, suitable for a decision-maker)",
    "action_relevance": "Why this analysis matters for the decision",
    "key_uncertainties": ["remaining unknowns that affect the prediction"],
    "agent_weight_rationale": "How you weighted different agents",
    "confidence": 0.0-1.0,
    "reasoning": "Meta-reasoning about the synthesis process"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        prediction = context.get("predictor_output", {})
        research = context.get("research_output", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})
        scenarios = context.get("scenario_output", {})
        validator = context.get("validator_output", {})

        msg = f"CANONICAL EVENT: {parsed.get('canonical_query', parsed.get('outcome_description', 'N/A'))}\n\n"
        msg += "=== AGENT OUTPUTS TO SYNTHESIZE ===\n\n"
        msg += f"[PREDICTOR] Probability: {prediction.get('predicted_probability', 0.5):.1%}\n"
        msg += f"  Reasoning: {prediction.get('reasoning', 'N/A')[:200]}\n\n"
        msg += f"[RESEARCH] Quality: {research.get('data_quality_score', 0.5)}\n"
        msg += f"  Summary: {research.get('summary', 'N/A')}\n\n"
        msg += f"[ANALYST] Bull case strength: {analyst.get('argument_strength', 0.5)}\n"
        msg += f"  Bull case: {analyst.get('bull_case', 'N/A')[:300]}\n\n"
        msg += f"[SKEPTIC] Counter-argument strength: {skeptic.get('counter_argument_strength', 0.5)}\n"
        msg += f"  Bear case: {skeptic.get('bear_case', 'N/A')[:300]}\n"
        msg += f"  Biases flagged: {skeptic.get('cognitive_biases_detected', [])}\n\n"
        msg += f"[SCENARIOS] Most likely: {scenarios.get('most_likely_scenario', 'N/A')}\n"
        msg += f"  Tail risk: {scenarios.get('tail_risk', 'N/A')}\n\n"
        msg += f"[VALIDATOR] Consistent: {validator.get('is_consistent', True)}\n"
        msg += f"  Adjusted confidence: {validator.get('adjusted_confidence', 0.5)}\n"
        msg += f"  Issues: {validator.get('logical_issues', [])}\n\n"
        msg += "Synthesize all perspectives into a final analysis."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("agent_agreement_level", output.get("confidence", 0.5)))))
