"""
Decision Engine
===============
Assembles the final FinalDecision object from all agent outputs
and scoring results. Acts as the integration layer between
the orchestrator and the API response.
"""
from typing import Any, Dict, List, Optional

import structlog

from backend.api.models import (
    AgentOutput,
    DecisionType,
    FinalDecision,
    ParsedEvent,
    Scenario,
)
from backend.core.scoring import get_scoring_engine

logger = structlog.get_logger(__name__)


class DecisionEngine:
    """
    Assembles the final decision from all agent outputs.
    Coordinates with the ScoringEngine and formats for API consumption.
    """

    def assemble(
        self,
        agent_outputs: Dict[str, Any],
        agent_output_objects: List[AgentOutput],
        implied_probability: float = 0.5,
    ) -> FinalDecision:
        """
        Build the FinalDecision from all pipeline outputs.

        Args:
            agent_outputs: Dict mapping agent key → raw output dict
            agent_output_objects: List of AgentOutput model instances
            implied_probability: Market implied probability (0.5 if unknown)

        Returns:
            FinalDecision ready to return to the user
        """
        # Run the scoring engine
        scoring_engine = get_scoring_engine()
        breakdown, risk, decision_type = scoring_engine.compute(
            agent_outputs, implied_probability
        )

        # Extract synthesis and predictor outputs
        synthesis = agent_outputs.get("synthesizer_output", {})
        predictor = agent_outputs.get("predictor_output", {})
        analyst = agent_outputs.get("analyst_output", {})
        skeptic = agent_outputs.get("skeptic_output", {})
        scenario_data = agent_outputs.get("scenario_output", {})
        scoring_raw = agent_outputs.get("scoring_output", {})

        # Final probability (prefer synthesis → predictor)
        final_prob = float(
            synthesis.get("final_probability",
            predictor.get("predicted_probability", 0.5))
        )

        # Build scenarios list
        scenarios = self._extract_scenarios(scenario_data)

        # Conflicts from synthesizer
        conflicts = synthesis.get("conflicts", [])
        if isinstance(conflicts, list):
            conflict_strs = [
                c.get("conflict", str(c)) if isinstance(c, dict) else str(c)
                for c in conflicts
            ]
        else:
            conflict_strs = []

        # Key insights
        key_insights = synthesis.get("key_insights", [])

        # Decision explanation (prefer scoring agent → synthesizer → generic)
        if scoring_raw.get("decision_explanation"):
            explanation = scoring_raw["decision_explanation"]
        else:
            explanation = self._generate_explanation(decision_type, breakdown, synthesis)

        # Reasoning summary
        reasoning_summary = synthesis.get("narrative", synthesis.get("summary", ""))

        logger.info(
            "decision_assembled",
            decision=decision_type,
            probability=final_prob,
            confidence=breakdown.confidence_score,
            edge=breakdown.edge,
        )

        return FinalDecision(
            decision=decision_type,
            confidence_score=breakdown.confidence_score,
            predicted_probability=final_prob,
            edge=breakdown.edge,
            risk=risk,
            score_breakdown=breakdown,
            explanation=explanation,
            reasoning_summary=reasoning_summary,
            bull_case=analyst.get("bull_case", ""),
            bear_case=skeptic.get("bear_case", ""),
            scenarios=scenarios,
            conflicts=conflict_strs,
            key_insights=key_insights if isinstance(key_insights, list) else [],
        )

    def _extract_scenarios(self, scenario_data: Dict[str, Any]) -> List[Scenario]:
        """Convert raw scenario dicts to Scenario models."""
        raw_scenarios = scenario_data.get("scenarios", [])
        result = []
        for s in raw_scenarios:
            if not isinstance(s, dict):
                continue
            try:
                result.append(
                    Scenario(
                        name=s.get("name", "Unknown"),
                        description=s.get("description", ""),
                        probability=float(s.get("probability", 0.0)),
                        outcome=s.get("outcome", ""),
                        impact=s.get("impact", ""),
                    )
                )
            except Exception:
                pass
        return result

    def _generate_explanation(
        self,
        decision: DecisionType,
        breakdown,
        synthesis: Dict[str, Any],
    ) -> str:
        """Generate a plain-English explanation of the decision."""
        edge_pct = abs(breakdown.edge) * 100
        conf_pct = breakdown.confidence_score * 100
        prob_pct = breakdown.predicted_probability * 100

        if decision == DecisionType.BET:
            return (
                f"Strong edge detected. The system estimates a {prob_pct:.0f}% probability "
                f"({edge_pct:.0f}% edge over market), with {conf_pct:.0f}% confidence. "
                f"Multiple agents concur and validation passed. Risk level is acceptable."
            )
        elif decision == DecisionType.WATCH:
            return (
                f"Moderate interest. The system estimates a {prob_pct:.0f}% probability "
                f"({edge_pct:.0f}% {'edge' if breakdown.edge > 0 else 'disadvantage'} vs market), "
                f"with {conf_pct:.0f}% confidence. Monitor for better pricing or additional signals."
            )
        else:
            return (
                f"Insufficient edge or high risk. Estimated probability: {prob_pct:.0f}%. "
                f"Edge is {edge_pct:.0f}% — below the threshold for action. "
                f"Agents disagree or data quality is poor. Skip this event."
            )


# Singleton
_decision_engine: Optional[DecisionEngine] = None


def get_decision_engine() -> DecisionEngine:
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = DecisionEngine()
    return _decision_engine
