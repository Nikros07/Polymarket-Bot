"""
Scoring System
==============
Implements the weighted scoring formula that converts multi-agent outputs
into a single composite score and action recommendation.
"""
from typing import Any, Dict, Optional, Tuple

import structlog

from backend.api.models import (
    DecisionType,
    FinalDecision,
    RiskLevel,
    RiskWarning,
    Scenario,
    ScoreBreakdown,
)
from backend.config import settings

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Weight Configuration
# ─────────────────────────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "predicted_probability": 0.25,
    "confidence_score": 0.20,
    "data_quality": 0.15,
    "argument_strength": 0.15,
    "counter_argument_impact": 0.10,  # Lower counter-impact = stronger bear case
    "validation_score": 0.10,
    "market_signal": 0.05,
}

RISK_WEIGHT_FACTORS = {
    "low_data_quality": 0.15,       # Penalty for poor data
    "high_bear_case": 0.20,         # Penalty for strong counter-arguments
    "bias_detected": 0.10,          # Penalty per bias found
    "validation_failure": 0.20,     # Penalty for failed validation
    "high_variance": 0.15,          # Penalty for high-variance scenarios
}


# ─────────────────────────────────────────────────────────────────────────────
# Scoring Engine
# ─────────────────────────────────────────────────────────────────────────────

class ScoringEngine:
    """
    Deterministic scoring engine that translates agent outputs into
    actionable scores and recommendations.
    """

    def compute(
        self,
        agent_outputs: Dict[str, Any],
        implied_probability: float = 0.5,
    ) -> Tuple[ScoreBreakdown, RiskWarning, DecisionType]:
        """
        Main entry point. Returns (ScoreBreakdown, RiskWarning, DecisionType).
        """
        scores = self._extract_component_scores(agent_outputs)
        breakdown = self._compute_breakdown(scores, implied_probability)
        risk = self._assess_risk(agent_outputs, breakdown)
        decision = self._make_decision(breakdown, risk)

        logger.info(
            "scoring_complete",
            composite=breakdown.composite_score,
            edge=breakdown.edge,
            risk=risk.level,
            decision=decision,
        )

        return breakdown, risk, decision

    def _extract_component_scores(
        self, agent_outputs: Dict[str, Any]
    ) -> Dict[str, float]:
        """Extract individual metric scores from agent outputs."""

        predictor = agent_outputs.get("predictor_output", {})
        research = agent_outputs.get("research_output", {})
        analyst = agent_outputs.get("analyst_output", {})
        skeptic = agent_outputs.get("skeptic_output", {})
        validator = agent_outputs.get("validator_output", {})
        synthesis = agent_outputs.get("synthesizer_output", {})
        scoring_agent = agent_outputs.get("scoring_output", {})

        # If scoring agent ran, prefer its scores
        if scoring_agent and "scores" in scoring_agent:
            raw = scoring_agent["scores"]
            return {
                "predicted_probability": _clamp(raw.get("predicted_probability", 0.5)),
                "confidence_score": _clamp(raw.get("confidence_score", 0.5)),
                "data_quality": _clamp(raw.get("data_quality", 0.5)),
                "argument_strength": _clamp(raw.get("argument_strength", 0.5)),
                "counter_argument_impact": _clamp(raw.get("counter_argument_impact", 0.5)),
                "validation_score": _clamp(raw.get("validation_score", 0.5)),
                "market_signal": _clamp(raw.get("market_signal", 0.0), -1.0, 1.0),
            }

        # Derive from individual agent outputs
        final_prob = synthesis.get("final_probability",
                     predictor.get("predicted_probability", 0.5))

        # Counter-argument impact: invert so higher bear strength = lower score
        bear_strength = skeptic.get("counter_argument_strength", 0.5)
        counter_impact = 1.0 - bear_strength  # High bear = low counter_impact (bad for bull)

        return {
            "predicted_probability": _clamp(final_prob),
            "confidence_score": _clamp(
                synthesis.get("agent_agreement_level",
                validator.get("adjusted_confidence",
                predictor.get("confidence", 0.5)))
            ),
            "data_quality": _clamp(research.get("data_quality_score", 0.5)),
            "argument_strength": _clamp(analyst.get("argument_strength", 0.5)),
            "counter_argument_impact": _clamp(counter_impact),
            "validation_score": _clamp(validator.get("validation_score", 0.5)),
            "market_signal": _clamp(0.0, -1.0, 1.0),  # Default neutral
        }

    def _compute_breakdown(
        self,
        scores: Dict[str, float],
        implied_probability: float,
    ) -> ScoreBreakdown:
        """Apply weighted formula to produce composite score."""

        # Normalize market signal from [-1, 1] to [0, 1] for weighting
        market_signal_normalized = (scores["market_signal"] + 1) / 2

        weighted_scores = {
            "predicted_probability": scores["predicted_probability"] * SCORE_WEIGHTS["predicted_probability"],
            "confidence_score": scores["confidence_score"] * SCORE_WEIGHTS["confidence_score"],
            "data_quality": scores["data_quality"] * SCORE_WEIGHTS["data_quality"],
            "argument_strength": scores["argument_strength"] * SCORE_WEIGHTS["argument_strength"],
            "counter_argument_impact": scores["counter_argument_impact"] * SCORE_WEIGHTS["counter_argument_impact"],
            "validation_score": scores["validation_score"] * SCORE_WEIGHTS["validation_score"],
            "market_signal": market_signal_normalized * SCORE_WEIGHTS["market_signal"],
        }

        composite = sum(weighted_scores.values())
        edge = scores["predicted_probability"] - implied_probability

        return ScoreBreakdown(
            predicted_probability=scores["predicted_probability"],
            confidence_score=scores["confidence_score"],
            data_quality=scores["data_quality"],
            argument_strength=scores["argument_strength"],
            counter_argument_strength=scores["counter_argument_impact"],
            risk_level=0.5,  # Will be filled by risk assessment
            market_signal=scores["market_signal"],
            validation_score=scores["validation_score"],
            agent_agreement=scores["confidence_score"],
            composite_score=_clamp(composite),
            edge=edge,
        )

    def _assess_risk(
        self,
        agent_outputs: Dict[str, Any],
        breakdown: ScoreBreakdown,
    ) -> RiskWarning:
        """Compute risk level and warnings."""

        risk_score = 0.0
        warnings = []

        # Low data quality → high risk
        if breakdown.data_quality < 0.4:
            risk_score += RISK_WEIGHT_FACTORS["low_data_quality"]
            warnings.append("Limited data quality — prediction is less reliable")

        # Strong counter-arguments → elevated risk
        counter = 1.0 - breakdown.counter_argument_strength
        if counter > 0.65:
            risk_score += RISK_WEIGHT_FACTORS["high_bear_case"]
            warnings.append("Strong bear case — significant downside risk identified")

        # Validation issues
        if breakdown.validation_score < 0.5:
            risk_score += RISK_WEIGHT_FACTORS["validation_failure"]
            warnings.append("Analysis has logical inconsistencies — exercise caution")

        # Low confidence
        if breakdown.confidence_score < 0.5:
            risk_score += 0.15
            warnings.append("Agent disagreement is high — outcome uncertain")

        # Biases detected
        skeptic = agent_outputs.get("skeptic_output", {})
        biases = skeptic.get("cognitive_biases_detected", [])
        if biases:
            bias_penalty = min(len(biases) * RISK_WEIGHT_FACTORS["bias_detected"], 0.25)
            risk_score += bias_penalty
            warnings.append(f"Cognitive biases detected: {', '.join(str(b) for b in biases[:3])}")

        # High variance scenarios
        scenarios = agent_outputs.get("scenario_output", {}).get("scenarios", [])
        if scenarios:
            probs = [s.get("probability", 0) for s in scenarios if isinstance(s, dict)]
            if probs:
                max_prob = max(probs)
                if max_prob < 0.45:  # No dominant scenario
                    risk_score += RISK_WEIGHT_FACTORS["high_variance"]
                    warnings.append("High variance — no dominant outcome scenario")

        # Edge too small
        if abs(breakdown.edge) < 0.03:
            risk_score += 0.10
            warnings.append("Edge is very thin — may not be profitable after variance")

        risk_score = _clamp(risk_score)

        # Categorize
        if risk_score < 0.3:
            level = RiskLevel.LOW
            exposure = "Up to 2-3% of bankroll"
        elif risk_score < 0.55:
            level = RiskLevel.MEDIUM
            exposure = "Up to 1-2% of bankroll"
        elif risk_score < 0.75:
            level = RiskLevel.HIGH
            exposure = "Avoid or micro-stake only (0.5%)"
        else:
            level = RiskLevel.EXTREME
            exposure = "Do not bet — risk is too high"

        # Update breakdown risk_level
        breakdown.risk_level = risk_score

        return RiskWarning(
            level=level,
            warnings=warnings if warnings else ["No major risk factors identified"],
            max_exposure_recommendation=exposure,
        )

    def _make_decision(
        self,
        breakdown: ScoreBreakdown,
        risk: RiskWarning,
    ) -> DecisionType:
        """Apply threshold rules to produce BET / WATCH / SKIP."""

        edge = breakdown.edge
        confidence = breakdown.confidence_score
        risk_level = breakdown.risk_level

        if (
            edge >= settings.BET_EDGE_THRESHOLD
            and confidence >= settings.BET_CONFIDENCE_THRESHOLD
            and risk_level < settings.MAX_RISK_FOR_BET
        ):
            return DecisionType.BET

        if (
            edge >= settings.WATCH_EDGE_THRESHOLD
            or (confidence > 0.5 and breakdown.composite_score > 0.58)
        ):
            return DecisionType.WATCH

        return DecisionType.SKIP


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, val)))


# Singleton
_scoring_engine: Optional[ScoringEngine] = None


def get_scoring_engine() -> ScoringEngine:
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = ScoringEngine()
    return _scoring_engine
