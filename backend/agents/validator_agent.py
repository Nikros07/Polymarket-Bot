"""
Validator Agent
===============
ROLE: Check logical consistency, data quality, and cognitive biases
across all agent outputs. Acts as quality control.
"""
import json
from typing import Any, Dict

from backend.agents.base_agent import OASISBaseAgent
from backend.api.models import AgentRole


class ValidatorAgent(OASISBaseAgent):
    ROLE = AgentRole.VALIDATOR
    AGENT_NAME = "ValidatorAgent"
    TEMPERATURE = 0.4  # Low temp for consistent logical checking
    SYSTEM_PROMPT = """You are the Validator Agent in an AI decision-making system.

Your role: Quality control. Check ALL agent outputs for logical consistency, data issues, and biases.

You are the system's integrity layer. You must:
1. CHECK for logical contradictions between agents
2. VERIFY that probability estimates are internally consistent
3. DETECT cognitive biases (recency, availability, anchoring, narrative, etc.)
4. ASSESS data quality and flag thin evidence
5. IDENTIFY circular reasoning or unfounded assumptions
6. ADJUST confidence based on data quality and consistency
7. FLAG any critical missing information

VALIDATION CHECKLIST:
- Do all probability estimates add up correctly?
- Are claims supported by actual data or speculation?
- Is the sample size sufficient for the confidence level claimed?
- Are there selection bias issues in the data used?
- Does the bull case address the skeptic's main concerns?
- Is the prediction time-sensitive in a way that matters?

Always respond in valid JSON format:
{
    "is_consistent": true|false,
    "consistency_issues": ["list of contradictions found"],
    "logical_issues": ["specific logical flaws"],
    "data_quality_flags": ["data quality concerns"],
    "cognitive_biases_detected": [
        {"bias": "bias name", "description": "how it manifests", "severity": "high|medium|low"}
    ],
    "unfounded_assumptions": ["assumptions without supporting evidence"],
    "missing_critical_information": ["what's missing that could change the analysis"],
    "inter_agent_conflicts": ["conflicts between different agent outputs"],
    "adjusted_confidence": 0.0-1.0,
    "validation_score": 0.0-1.0,
    "reliability_assessment": "Overall assessment of analysis reliability",
    "confidence": 0.0-1.0,
    "reasoning": "Summary of validation findings"
}"""

    def _build_user_message(self, context: Dict[str, Any]) -> str:
        parsed = context.get("parsed_event", {})
        prediction = context.get("predictor_output", {})
        research = context.get("research_output", {})
        analyst = context.get("analyst_output", {})
        skeptic = context.get("skeptic_output", {})
        scenarios = context.get("scenario_output", {})

        msg = "VALIDATE THE FOLLOWING MULTI-AGENT ANALYSIS:\n\n"
        msg += f"EVENT: {json.dumps(parsed, indent=2)}\n\n"
        msg += f"PREDICTION: {prediction.get('predicted_probability', 0.5):.1%} (confidence: {prediction.get('confidence', 0.5):.1%})\n"
        msg += f"Research quality: {research.get('data_quality_score', 0.5)}\n\n"
        msg += f"BULL CASE STRENGTH: {analyst.get('argument_strength', 0.5)}\n"
        msg += f"Bull factors: {analyst.get('bull_factors', [])}\n\n"
        msg += f"BEAR CASE STRENGTH: {skeptic.get('counter_argument_strength', 0.5)}\n"
        msg += f"Flaws identified: {skeptic.get('flaws_in_analysis', [])}\n"
        msg += f"Biases flagged: {skeptic.get('cognitive_biases_detected', [])}\n\n"
        msg += f"SCENARIOS: {len(scenarios.get('scenarios', []))} scenarios modeled\n\n"
        msg += "Perform comprehensive validation of this analysis."
        return msg

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        return float(max(0.0, min(1.0, output.get("validation_score", output.get("confidence", 0.5)))))
