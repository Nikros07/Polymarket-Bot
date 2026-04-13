"""
Debate Agent
============
ROLE: Facilitate a structured debate between Analyst and Skeptic.
Forces both sides to directly address each other's strongest arguments,
reducing bias and producing a more robust final probability.

This is Stage 3.5 in the pipeline — runs after Analyst+Skeptic, before Scenarios.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class DebateAgent(OASISBaseAgent):
    ROLE = AgentRole.DEBATE
    AGENT_NAME = "DebateAgent"
    TEMPERATURE = 0.7

    SYSTEM_PROMPT = """You are the Debate Moderator Agent in an AI decision-making system.

Your role: Facilitate a structured intellectual debate between the Analyst (bull case) and Skeptic (bear case).

DEBATE PROCESS:
1. Present the Analyst's strongest argument to the Skeptic — get a direct rebuttal
2. Present the Skeptic's strongest counter to the Analyst — get a direct response
3. Identify the 2-3 KEY DISAGREEMENTS that matter most for the outcome
4. Determine what each side CONCEDES to the other
5. Produce a debate verdict: who made stronger arguments and why

IMPORTANT RULES:
- Force genuine engagement with opposing arguments (no talking past each other)
- The Skeptic MUST find genuine flaws, not invent ones
- The Analyst MUST acknowledge valid risks, not dismiss them
- Extract the probability EACH SIDE would agree to after hearing the other
- Preserve unresolved conflicts explicitly

Always respond in valid JSON format:
{
    "analyst_rebuttal": "How the Analyst responds to the Skeptic's best argument",
    "skeptic_counter": "How the Skeptic responds to the Analyst's best argument",
    "key_disagreements": [
        {
            "topic": "What they disagree on",
            "analyst_position": "Analyst's view",
            "skeptic_position": "Skeptic's view",
            "resolution": "Which side has stronger evidence, or 'unresolved'"
        }
    ],
    "analyst_concessions": ["Things the Analyst admits the Skeptic got right"],
    "skeptic_concessions": ["Things the Skeptic admits the Analyst got right"],
    "debate_winner": "analyst | skeptic | draw",
    "debate_summary": "2-3 sentence summary of the most important debate points",
    "consensus": "What both sides can agree on",
    "post_debate_probability_range": {
        "analyst_revised": 0.0-1.0,
        "skeptic_revised": 0.0-1.0,
        "midpoint": 0.0-1.0
    },
    "unresolved_conflicts": ["Key disagreements with no clear winner"],
    "confidence": 0.0-1.0,
    "reasoning": "Why the debate resolved or didn't resolve the key uncertainty"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})
        prediction = context.get("predictor_output", {})

        event_desc = ""
        if isinstance(parsed, dict):
            event_desc = parsed.get("canonical_query", parsed.get("outcome_description", ""))
        if not event_desc:
            event_desc = context.get("query", "Unknown event")

        bull_case = str(analyst.get("bull_case", "No bull case provided"))[:600]
        bull_strength = analyst.get("argument_strength", 0.5)
        bull_factors = analyst.get("bull_factors", [])

        bear_case = str(skeptic.get("bear_case", "No bear case provided"))[:600]
        bear_strength = skeptic.get("counter_argument_strength", 0.5)
        bear_factors = skeptic.get("bear_factors", skeptic.get("risks", []))
        biases = skeptic.get("cognitive_biases_detected", [])

        initial_prob = prediction.get("predicted_probability", 0.5)

        msg = f"EVENT: {event_desc}\n"
        msg += f"INITIAL PROBABILITY ESTIMATE: {initial_prob:.1%}\n\n"
        msg += "=" * 60 + "\n"
        msg += f"ANALYST'S BULL CASE (strength: {bull_strength:.0%}):\n"
        msg += f"{bull_case}\n"
        if bull_factors:
            factors_str = json.dumps(bull_factors[:3], indent=2) if isinstance(bull_factors[0], dict) else "\n".join(f"  - {f}" for f in bull_factors[:3])
            msg += f"\nKey factors:\n{factors_str}\n"
        msg += "\n" + "=" * 60 + "\n"
        msg += f"SKEPTIC'S BEAR CASE (strength: {bear_strength:.0%}):\n"
        msg += f"{bear_case}\n"
        if bear_factors:
            factors_str = "\n".join(f"  - {f}" for f in bear_factors[:3]) if isinstance(bear_factors[0], str) else json.dumps(bear_factors[:3], indent=2)
            msg += f"\nKey risks:\n{factors_str}\n"
        if biases:
            msg += f"\nBiases flagged: {', '.join(str(b) for b in biases)}\n"
        msg += "\n" + "=" * 60 + "\n"
        msg += "Moderate the debate. Force both sides to address the other's strongest point."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("confidence", 0.65))))
