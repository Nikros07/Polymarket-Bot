"""
Scoring Agent
=============
ROLE: Compute final scores and recommendation (BET / WATCH / SKIP).
Applies weighted scoring, confidence thresholds, and risk filters.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class ScoringAgent(OASISBaseAgent):
    ROLE = AgentRole.SCORING
    AGENT_NAME = "ScoringAgent"
    TEMPERATURE = 0.3  # Low temp for deterministic scoring
    SYSTEM_PROMPT = """You are the Scoring Agent in an AI decision-making system.

Your role: Compute the final composite score and action recommendation.

You receive the full synthesized analysis and must:
1. COMPUTE individual component scores (each 0.0-1.0)
2. APPLY weighted formula to compute composite score
3. CALCULATE the edge (predicted probability vs implied market probability)
4. ASSESS risk level based on multiple factors
5. APPLY threshold rules to produce BET / WATCH / SKIP recommendation
6. EXPLAIN the decision clearly

SCORING COMPONENTS & WEIGHTS:
- predicted_probability (25%): Core probability estimate
- confidence_score (20%): How confident agents are collectively
- data_quality (15%): Research quality and completeness
- argument_strength (15%): Strength of bull case
- counter_argument_impact (10%): How much bear case weakens the thesis (lower = stronger bear case)
- validation_score (10%): Logical consistency and quality
- market_signal (5%): Odds movement / sharp money indicators

DECISION THRESHOLDS:
- BET: edge > 0.10 AND confidence > 0.65 AND risk_level < 0.70
- WATCH: edge > 0.03 OR interesting pattern
- SKIP: insufficient edge or too much risk

RISK LEVELS:
- LOW (0.0-0.3): High confidence, good data, no major concerns
- MEDIUM (0.3-0.6): Some uncertainty, moderate concerns
- HIGH (0.6-0.8): Significant concerns, data issues, or strong bear case
- EXTREME (0.8-1.0): Do not bet regardless of edge

Always respond in valid JSON format:
{
    "scores": {
        "predicted_probability": 0.0-1.0,
        "confidence_score": 0.0-1.0,
        "data_quality": 0.0-1.0,
        "argument_strength": 0.0-1.0,
        "counter_argument_impact": 0.0-1.0,
        "validation_score": 0.0-1.0,
        "market_signal": -1.0 to 1.0
    },
    "composite_score": 0.0-1.0,
    "edge": -1.0 to 1.0,
    "risk_level": 0.0-1.0,
    "risk_category": "low|medium|high|extreme",
    "decision": "BET|WATCH|SKIP",
    "decision_explanation": "Why this decision was made",
    "risk_warnings": ["specific risk warnings for the user"],
    "max_exposure_guidance": "How much to risk if betting",
    "confidence": 0.0-1.0,
    "reasoning": "Full scoring rationale"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        prediction = context.get("predictor_output", {})
        research = context.get("research_output", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})
        validator = context.get("validator_output", {})
        synthesis = context.get("synthesizer_output", {})
        implied_prob = parsed.get("implied_probability") or context.get("implied_probability") or 0.5

        msg = "COMPUTE FINAL SCORES FOR:\n\n"
        msg += f"Event: {parsed.get('canonical_query', parsed.get('outcome_description', 'N/A'))}\n\n"
        msg += f"=== KEY METRICS ===\n"
        msg += f"Final Probability (synthesis): {synthesis.get('final_probability', prediction.get('predicted_probability', 0.5)):.1%}\n"
        msg += f"Implied Market Probability: {implied_prob:.1%}\n"
        msg += f"Estimated Edge: {(synthesis.get('final_probability', 0.5) - implied_prob):.1%}\n\n"
        msg += f"Research Quality: {research.get('data_quality_score', 0.5)}\n"
        msg += f"Bull Case Strength: {analyst.get('argument_strength', 0.5)}\n"
        msg += f"Bear Case Strength: {skeptic.get('counter_argument_strength', 0.5)}\n"
        msg += f"Validation Score: {validator.get('validation_score', 0.5)}\n"
        msg += f"Agent Agreement: {synthesis.get('agent_agreement_level', 0.5)}\n\n"
        msg += f"Key Conflicts: {synthesis.get('conflicts', [])}\n"
        msg += f"Biases Detected: {skeptic.get('cognitive_biases_detected', [])}\n"
        msg += f"Risk Factors: {skeptic.get('risks', [])}\n\n"
        msg += "Apply the scoring formula and produce the final recommendation."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("composite_score", output.get("confidence", 0.5)))))
