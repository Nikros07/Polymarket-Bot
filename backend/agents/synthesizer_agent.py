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

You receive outputs from all agents including a Debate summary and must:
1. WEIGH each agent's contribution based on their confidence and evidence quality
2. IDENTIFY areas of consensus and genuine disagreement
3. SYNTHESIZE a final probability estimate (weighted, not just averaged)
4. PRESERVE important conflicts — do NOT hide disagreements
5. PRODUCE a clear, readable narrative that a human can act on
6. ASSESS the overall quality of the multi-agent analysis
7. IF this is a sports event (football/soccer), provide SPECIFIC market probabilities

SYNTHESIS PRINCIPLES:
- The debate exchange reveals the strongest arguments — weight them accordingly
- The skeptic's valid concerns reduce confidence
- Strong validation increases confidence
- Poor data quality must be reflected in the final estimate
- Conflicts between agents should be named and explained

SPORTS BETTING SPECIFICS (for football/soccer events):
If the event is a sports match, you MUST provide specific probabilities for:
- Match winner: home win %, draw %, away win % (must sum to ~100%)
- Over/Under 2.5 goals: over %, under %
- Both teams to score: yes %, no %
Base these on the research data, stats, form, and agent consensus.

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
    "sports_predictions": {
        "home_win_probability": 0.0-1.0,
        "draw_probability": 0.0-1.0,
        "away_win_probability": 0.0-1.0,
        "over_2_5_probability": 0.0-1.0,
        "under_2_5_probability": 0.0-1.0,
        "btts_yes_probability": 0.0-1.0,
        "btts_no_probability": 0.0-1.0
    },
    "persona_probabilities": {
        "analyst": 0.0-1.0,
        "skeptic": 0.0-1.0,
        "market_reader": 0.0-1.0,
        "heuristic": 0.0-1.0,
        "synthesizer": 0.0-1.0
    },
    "confidence": 0.0-1.0,
    "reasoning": "Meta-reasoning about the synthesis process"
}

Note: For non-sports events, include sports_predictions as null.
For persona_probabilities, estimate how each analytical lens would rate the probability:
- analyst: pure data/stats based estimate
- skeptic: conservative/contrarian estimate
- market_reader: what market odds imply
- heuristic: pattern-based estimate
- synthesizer: your meta-synthesis"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        prediction = context.get("predictor_output", {})
        research = context.get("research_output", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})
        debate = context.get("debate_output", {})
        scenarios = context.get("scenario_output", {})
        validator = context.get("validator_output", {})
        event_type = parsed.get("event_type", "other") if isinstance(parsed, dict) else "other"
        teams = parsed.get("teams", []) if isinstance(parsed, dict) else []

        msg = f"CANONICAL EVENT: {parsed.get('canonical_query', parsed.get('outcome_description', 'N/A'))}\n"
        msg += f"EVENT TYPE: {event_type}\n"
        if teams:
            msg += f"TEAMS: {' vs '.join(str(t) for t in teams[:2])}\n"
        msg += "\n=== AGENT OUTPUTS TO SYNTHESIZE ===\n\n"
        msg += f"[PREDICTOR] Probability: {prediction.get('predicted_probability', 0.5):.1%}\n"
        msg += f"  Reasoning: {str(prediction.get('reasoning', 'N/A'))[:200]}\n\n"
        msg += f"[RESEARCH] Quality: {research.get('data_quality_score', 0.5)}\n"
        msg += f"  Summary: {str(research.get('summary', 'N/A'))[:200]}\n\n"
        msg += f"[ANALYST] Bull case strength: {analyst.get('argument_strength', 0.5)}\n"
        msg += f"  Bull case: {str(analyst.get('bull_case', 'N/A'))[:300]}\n\n"
        msg += f"[SKEPTIC] Counter-argument strength: {skeptic.get('counter_argument_strength', 0.5)}\n"
        msg += f"  Bear case: {str(skeptic.get('bear_case', 'N/A'))[:300]}\n"
        msg += f"  Biases flagged: {skeptic.get('cognitive_biases_detected', [])}\n\n"

        if debate:
            msg += f"[DEBATE SUMMARY]\n  {str(debate.get('debate_summary', 'No debate data'))[:400]}\n"
            msg += f"  Final consensus: {str(debate.get('consensus', 'N/A'))[:200]}\n\n"

        msg += f"[SCENARIOS] Most likely: {scenarios.get('most_likely_scenario', 'N/A')}\n"
        msg += f"  Tail risk: {str(scenarios.get('tail_risk', 'N/A'))[:200]}\n\n"
        msg += f"[VALIDATOR] Consistent: {validator.get('is_consistent', True)}\n"
        msg += f"  Adjusted confidence: {validator.get('adjusted_confidence', 0.5)}\n"
        msg += f"  Issues: {validator.get('logical_issues', [])}\n\n"

        if event_type == "sports" and teams:
            msg += f"\nIMPORTANT: This is a SPORTS event. Provide specific probabilities for:\n"
            msg += f"- Match winner: {teams[0] if teams else 'Home'} win, draw, {teams[1] if len(teams)>1 else 'Away'} win\n"
            msg += f"- Over/Under 2.5 goals\n- Both teams to score\n"

        msg += "\nSynthesize all perspectives into a final analysis."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("agent_agreement_level", output.get("confidence", 0.5)))))
