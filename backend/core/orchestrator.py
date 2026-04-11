"""
OASIS Orchestrator  (improved — per-agent error recovery)
==========================================================
Changes vs original:
  - Each agent wrapped in individual try/except → pipeline continues on failure
  - BetType injected into shared environment for agent context
  - Polymarket markets searched in parallel with research stage
  - SSE queue sends start/complete events correctly even after agent errors
  - Session always persisted (even on partial failure)
"""
import asyncio
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import structlog

from backend.agents.analyst_agent    import AnalystAgent
from backend.agents.input_parser_agent import InputParserAgent
from backend.agents.predictor_agent  import PredictorAgent
from backend.agents.research_agent   import ResearchAgent
from backend.agents.scanner_agent    import ScannerAgent
from backend.agents.scenario_agent   import ScenarioAgent
from backend.agents.scoring_agent    import ScoringAgent
from backend.agents.skeptic_agent    import SkepticAgent
from backend.agents.synthesizer_agent import SynthesizerAgent
from backend.agents.validator_agent  import ValidatorAgent
from backend.api.models              import (AgentOutput, AgentRole,
                                              AnalysisSession, BetType,
                                              PolymarketMarket)
from backend.core.decision_engine    import get_decision_engine
from backend.core.memory             import get_memory
from backend.services.polymarket_service import get_polymarket_service
from backend.services.research_service  import get_research_service

logger = structlog.get_logger(__name__)
ProgressCallback = Callable[[AgentOutput], None]


class OASISOrchestrator:
    """
    Coordinates the 10-agent OASIS decision society.
    Stages run sequentially; Analyst + Skeptic run in parallel (Stage 3).
    Polymarket search runs in parallel with Stage 2 research.
    """

    def __init__(self):
        self.scanner     = ScannerAgent()
        self.parser      = InputParserAgent()
        self.researcher  = ResearchAgent()
        self.predictor   = PredictorAgent()
        self.analyst     = AnalystAgent()
        self.skeptic     = SkepticAgent()
        self.scenario    = ScenarioAgent()
        self.validator   = ValidatorAgent()
        self.synthesizer = SynthesizerAgent()
        self.scorer      = ScoringAgent()

        self.memory            = get_memory()
        self.research_svc      = get_research_service()
        self.polymarket_svc    = get_polymarket_service()
        self.decision_engine   = get_decision_engine()

        self._sessions: Dict[str, AnalysisSession] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def create_session(self, query: str, bet_type: BetType = BetType.MATCH_WINNER) -> str:
        sid = str(uuid.uuid4())
        self._sessions[sid] = AnalysisSession(
            session_id=sid, query=query, bet_type=bet_type, status="pending"
        )
        return sid

    def get_session(self, session_id: str) -> Optional[AnalysisSession]:
        return self._sessions.get(session_id)

    async def run_analysis(
        self,
        session_id:          str,
        query:               str,
        bet_type:            BetType = BetType.MATCH_WINNER,
        implied_probability: Optional[float] = None,
        market_odds:         Optional[str] = None,
        context:             Optional[str] = None,
        on_progress:         Optional[ProgressCallback] = None,
    ) -> AnalysisSession:

        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.status   = "running"
        session.query    = query
        session.bet_type = bet_type

        # Shared OASIS environment
        env: Dict[str, Any] = {
            "query":              query,
            "bet_type":           bet_type.value,
            "bet_type_label":     bet_type.label,
            "implied_probability": implied_probability or 0.5,
            "market_odds":        market_odds,
            "context":            context,
            "session_id":         session_id,
        }

        await self._inject_memory(env, query)

        try:
            # ── Stage 1: Scan + Parse ────────────────────────────────────
            scan_out   = await self._run(self.scanner, env, session, on_progress)
            env["scanner_output"] = scan_out.output

            parse_out  = await self._run(self.parser,  env, session, on_progress)
            env["parsed_event"] = parse_out.output
            session.parsed_event = _to_parsed_event(parse_out.output, bet_type)

            # ── Stage 2: Research + Polymarket (parallel) ────────────────
            raw_sources, poly_markets = await asyncio.gather(
                self.research_svc.search(query=query, parsed_event=parse_out.output),
                self.polymarket_svc.search_markets(query=query, bet_type=bet_type.value),
                return_exceptions=True,
            )
            if isinstance(raw_sources, Exception):
                logger.warning("research_fetch_failed", error=str(raw_sources))
                raw_sources = []
            if isinstance(poly_markets, Exception):
                logger.warning("polymarket_fetch_failed", error=str(poly_markets))
                poly_markets = []

            env["raw_sources"]       = raw_sources
            env["polymarket_markets"] = poly_markets

            research_out = await self._run(self.researcher, env, session, on_progress)
            env["research_output"] = research_out.output

            # ── Stage 3: Predict ─────────────────────────────────────────
            pred_out = await self._run(self.predictor, env, session, on_progress)
            env["predictor_output"] = pred_out.output

            # ── Stage 4: Analyst + Skeptic (parallel) ────────────────────
            analyst_out, skeptic_out = await asyncio.gather(
                self._run(self.analyst, env, session, on_progress),
                self._run(self.skeptic, env, session, on_progress),
            )
            env["analyst_output"] = analyst_out.output
            env["skeptic_output"] = skeptic_out.output

            # ── Stage 5: Scenarios ────────────────────────────────────────
            scen_out = await self._run(self.scenario, env, session, on_progress)
            env["scenario_output"] = scen_out.output

            # ── Stage 6: Validate ─────────────────────────────────────────
            val_out = await self._run(self.validator, env, session, on_progress)
            env["validator_output"] = val_out.output

            # ── Stage 7: Synthesise ───────────────────────────────────────
            synth_out = await self._run(self.synthesizer, env, session, on_progress)
            env["synthesizer_output"] = synth_out.output

            # ── Stage 8: Score ────────────────────────────────────────────
            score_out = await self._run(self.scorer, env, session, on_progress)
            env["scoring_output"] = score_out.output

            # ── Final decision assembly ───────────────────────────────────
            final = self.decision_engine.assemble(
                agent_outputs=env,
                agent_output_objects=session.agent_outputs,
                implied_probability=implied_probability or 0.5,
            )
            # Attach Polymarket markets to decision
            final.polymarket_markets = [
                PolymarketMarket(**m) if isinstance(m, dict) else m
                for m in (poly_markets or [])
            ]

            session.final_decision = final
            session.status         = "completed"
            session.completed_at   = datetime.utcnow()

        except Exception as exc:
            logger.error("pipeline_error", session_id=session_id, error=str(exc))
            session.status = "error"
            session.error  = str(exc)

        await self._persist(session)
        return session

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _run(
        self,
        agent,
        env: Dict[str, Any],
        session: AnalysisSession,
        on_progress: Optional[ProgressCallback],
    ) -> AgentOutput:
        """Run one agent step; always returns an AgentOutput (never raises)."""
        # Notify: agent starting
        if on_progress:
            try:
                on_progress(AgentOutput(
                    role=agent.ROLE, agent_name=agent.AGENT_NAME,
                    status="running", output={}, processing_time_ms=0,
                ))
            except Exception:
                pass

        try:
            out = await agent.step(env)
        except Exception as exc:
            logger.error("agent_step_exception", agent=agent.AGENT_NAME, error=str(exc))
            out = AgentOutput(
                role=agent.ROLE, agent_name=agent.AGENT_NAME,
                status="error", output={}, error=str(exc),
            )

        session.agent_outputs.append(out)

        if on_progress:
            try:
                on_progress(out)
            except Exception:
                pass

        return out

    async def _inject_memory(self, env: Dict[str, Any], query: str):
        try:
            past = await self.memory.get_similar_past_decisions(query, limit=2)
            if past:
                env["historical_context"] = past
        except Exception as exc:
            logger.debug("memory_inject_skip", reason=str(exc))

    async def _persist(self, session: AnalysisSession):
        try:
            fd = session.final_decision
            await self.memory.save_session({
                "session_id":    session.session_id,
                "query":         session.query,
                "event_type":    session.parsed_event.event_type if session.parsed_event else None,
                "status":        session.status,
                "agent_outputs": [o.model_dump() for o in session.agent_outputs],
                "parsed_event":  session.parsed_event.model_dump() if session.parsed_event else None,
                "final_decision": fd.model_dump() if fd else None,
                "decision":      str(fd.decision) if fd else None,
                "confidence":    fd.confidence_score if fd else None,
                "predicted_prob": fd.predicted_probability if fd else None,
                "edge":          fd.edge if fd else None,
                "created_at":    session.created_at.isoformat(),
                "completed_at":  session.completed_at.isoformat() if session.completed_at else None,
                "error":         session.error,
            })
        except Exception as exc:
            logger.error("persist_failed", error=str(exc))


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_parsed_event(output: Dict[str, Any], bet_type: BetType):
    from backend.api.models import ParsedEvent, EventType
    try:
        return ParsedEvent(
            event_type=output.get("event_type", "sports"),
            sport=output.get("sport"),
            teams=output.get("teams", []) or [],
            players=output.get("players", []) or [],
            outcome_description=output.get("prediction_target",
                                output.get("outcome_description", "")),
            timeframe=output.get("timeframe_description",
                      output.get("timeframe", "")),
            market_type=output.get("market_type", ""),
            bet_type=bet_type,
            implied_probability=output.get("implied_probability"),
            raw_query=output.get("canonical_query", ""),
        )
    except Exception:
        return ParsedEvent(bet_type=bet_type)


# ── Singleton ─────────────────────────────────────────────────────────────────
_orchestrator: Optional[OASISOrchestrator] = None

def get_orchestrator() -> OASISOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OASISOrchestrator()
    return _orchestrator
