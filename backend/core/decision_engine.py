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
    PersonaBreakdown,
    Scenario,
    SportsPredictions,
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

        # Debate summary
        debate = agent_outputs.get("debate_output", {})
        debate_summary = debate.get("debate_summary", "")

        # Sports predictions
        sports_predictions = self._extract_sports_predictions(
            synthesis, agent_outputs
        )

        # Persona breakdown (Wisdom-of-Crowd)
        persona_breakdown = self._extract_persona_breakdown(synthesis, final_prob)

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
            debate_summary=debate_summary,
            scenarios=scenarios,
            conflicts=conflict_strs,
            key_insights=key_insights if isinstance(key_insights, list) else [],
            sports_predictions=sports_predictions,
            persona_breakdown=persona_breakdown,
        )

    def _extract_sports_predictions(
        self,
        synthesis: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> Optional[SportsPredictions]:
        """Extract sport-specific probabilities from synthesizer output."""
        sp_raw = synthesis.get("sports_predictions")
        if not sp_raw or not isinstance(sp_raw, dict):
            return None

        def _f(key, default=None):
            v = sp_raw.get(key, default)
            if v is None:
                return None
            try:
                return float(max(0.0, min(1.0, v)))
            except (TypeError, ValueError):
                return None

        home_win = _f("home_win_probability")
        draw = _f("draw_probability")
        away_win = _f("away_win_probability")
        over_2_5 = _f("over_2_5_probability")
        under_2_5 = _f("under_2_5_probability")
        btts_yes = _f("btts_yes_probability")
        btts_no = _f("btts_no_probability")

        # Normalize match winner probabilities to sum to 1
        if home_win is not None and draw is not None and away_win is not None:
            total = home_win + draw + away_win
            if total > 0:
                home_win /= total
                draw /= total
                away_win /= total

        # Normalize over/under
        if over_2_5 is not None and under_2_5 is None:
            under_2_5 = 1.0 - over_2_5
        elif under_2_5 is not None and over_2_5 is None:
            over_2_5 = 1.0 - under_2_5

        # Normalize BTTS
        if btts_yes is not None and btts_no is None:
            btts_no = 1.0 - btts_yes
        elif btts_no is not None and btts_yes is None:
            btts_yes = 1.0 - btts_no

        # Extract team names
        parsed = agent_outputs.get("parsed_event", {})
        teams = []
        if isinstance(parsed, dict):
            teams = parsed.get("teams", [])

        # Generate bet recommendations (threshold: 65%)
        BET_THRESHOLD = 0.65

        match_winner_bet = None
        if home_win is not None and draw is not None and away_win is not None:
            best_prob = max(home_win, draw, away_win)
            if best_prob >= BET_THRESHOLD:
                if best_prob == home_win:
                    match_winner_bet = "HOME"
                elif best_prob == away_win:
                    match_winner_bet = "AWAY"
                else:
                    match_winner_bet = "DRAW"
            else:
                match_winner_bet = "NO BET"

        over_under_bet = None
        if over_2_5 is not None:
            if over_2_5 >= BET_THRESHOLD:
                over_under_bet = "OVER"
            elif (1.0 - over_2_5) >= BET_THRESHOLD:
                over_under_bet = "UNDER"
            else:
                over_under_bet = "NO BET"

        btts_bet = None
        if btts_yes is not None:
            if btts_yes >= BET_THRESHOLD:
                btts_bet = "YES"
            elif btts_no is not None and btts_no >= BET_THRESHOLD:
                btts_bet = "NO"
            else:
                btts_bet = "NO BET"

        return SportsPredictions(
            home_team=teams[0] if len(teams) > 0 else None,
            away_team=teams[1] if len(teams) > 1 else None,
            home_win_probability=home_win,
            draw_probability=draw,
            away_win_probability=away_win,
            over_2_5_probability=over_2_5,
            under_2_5_probability=under_2_5,
            btts_yes_probability=btts_yes,
            btts_no_probability=btts_no,
            match_winner_bet=match_winner_bet,
            over_under_bet=over_under_bet,
            btts_bet=btts_bet,
        )

    def _extract_persona_breakdown(
        self,
        synthesis: Dict[str, Any],
        final_prob: float,
    ) -> Optional[PersonaBreakdown]:
        """Extract Wisdom-of-Crowd persona probabilities and compute aggregation."""
        pp_raw = synthesis.get("persona_probabilities")
        if not pp_raw or not isinstance(pp_raw, dict):
            return None

        def _f(key, fallback=final_prob):
            v = pp_raw.get(key)
            if v is None:
                return fallback
            try:
                return float(max(0.0, min(1.0, v)))
            except (TypeError, ValueError):
                return fallback

        analyst_p = _f("analyst")
        skeptic_p = _f("skeptic")
        market_p = _f("market_reader")
        heuristic_p = _f("heuristic")
        synth_p = _f("synthesizer")

        # Wisdom-of-Crowd weights (from Nick's docs)
        weights = {"analyst": 0.30, "skeptic": 0.15, "market_reader": 0.20,
                   "heuristic": 0.20, "synthesizer": 0.15}

        weighted_prob = (
            analyst_p * weights["analyst"] +
            skeptic_p * weights["skeptic"] +
            market_p * weights["market_reader"] +
            heuristic_p * weights["heuristic"] +
            synth_p * weights["synthesizer"]
        )
        weighted_prob = max(0.0, min(1.0, weighted_prob))

        # Herd behavior adjustment (from Nick's ARCHITECTURE.md)
        probs = [analyst_p, skeptic_p, market_p, heuristic_p, synth_p]
        mean_p = weighted_prob
        variance = sum((p - mean_p) ** 2 for p in probs) / len(probs)
        disagreement = variance ** 0.5  # std dev

        if mean_p > 0.65:
            herd_factor = 0.92 - (disagreement * 0.5)
        elif mean_p < 0.35:
            herd_factor = 1.08 + (disagreement * 0.5)
        else:
            herd_factor = 1.0

        herd_adjusted = max(0.0, min(1.0, weighted_prob * herd_factor))

        return PersonaBreakdown(
            analyst=analyst_p,
            skeptic=skeptic_p,
            market_reader=market_p,
            heuristic=heuristic_p,
            synthesizer=synth_p,
            weighted_probability=round(weighted_prob, 4),
            herd_adjusted_probability=round(herd_adjusted, 4),
            disagreement=round(disagreement, 4),
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
