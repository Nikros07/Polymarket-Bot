"""
OASIS Orchestrator
==================
The central coordination layer that orchestrates all agents in the
multi-agent decision pipeline.

Implements OASIS-style agent society coordination:
  - Sequential stages with clear data flow
  - Parallel execution where agents can run independently
  - Shared environment (context dict) passed between stages
  - Real-time progress broadcasting via SSE callbacks
  - Full audit trail of all agent outputs

Pipeline Stages:
  Stage 1: Scan + Parse       (sequential — parse depends on scan)
  Stage 2: Research           (sequential — needs parsed event)
  Stage 3: Predict + Analyze  (parallel — analyst & skeptic run simultaneously)
  Stage 4: Scenario modeling  (needs predictor/analyst/skeptic)
  Stage 5: Validate           (needs all above)
  Stage 6: Synthesize         (needs validated outputs)
  Stage 7: Score              (needs synthesis)
"""
import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import structlog

from backend.agents.scanner_agent import ScannerAgent
from backend.agents.input_parser_agent import InputParserAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.predictor_agent import PredictorAgent
from backend.agents.analyst_agent import AnalystAgent
from backend.agents.skeptic_agent import SkepticAgent
from backend.agents.scenario_agent import ScenarioAgent
from backend.agents.validator_agent import ValidatorAgent
from backend.agents.synthesizer_agent import SynthesizerAgent
from backend.agents.scoring_agent import ScoringAgent
from backend.api.models import AgentOutput, AgentRole, AnalysisSession
from backend.core.decision_engine import get_decision_engine
from backend.core.memory import get_memory
from backend.services.research_service import get_research_service

logger = structlog.get_logger(__name__)

# Type alias for progress callbacks
ProgressCallback = Callable[[AgentOutput], None]


class OASISOrchestrator:
    """
    OASIS-compatible multi-agent orchestrator.

    Manages the "agent society" — coordinates all 10 agents through
    structured stages with shared context (environment) passing.
    """

    def __init__(self):
        # Initialize all agents (the OASIS "society")
        self.scanner = ScannerAgent()
        self.parser = InputParserAgent()
        self.researcher = ResearchAgent()
        self.predictor = PredictorAgent()
        self.analyst = AnalystAgent()
        self.skeptic = SkepticAgent()
        self.scenario = ScenarioAgent()
        self.validator = ValidatorAgent()
        self.synthesizer = SynthesizerAgent()
        self.scorer = ScoringAgent()

        self.memory = get_memory()
        self.research_service = get_research_service()
        self.decision_engine = get_decision_engine()

        # Active sessions registry
        self._sessions: Dict[str, AnalysisSession] = {}

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def create_session(self, query: str, implied_probability: Optional[float] = None) -> str:
        """Create a new analysis session and return its ID."""
        session_id = str(uuid.uuid4())
        session = AnalysisSession(
            session_id=session_id,
            query=query,
            status="pending",
            created_at=datetime.utcnow(),
        )
        self._sessions[session_id] = session
        return session_id

    def get_session(self, session_id: str) -> Optional[AnalysisSession]:
        """Retrieve a session (in-memory first, then DB)."""
        return self._sessions.get(session_id)

    async def run_analysis(
        self,
        session_id: str,
        query: str,
        implied_probability: Optional[float] = None,
        market_odds: Optional[str] = None,
        context: Optional[str] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> AnalysisSession:
        """
        Execute the full multi-agent analysis pipeline.

        This is the main orchestration method — runs all 10 agents
        through 7 stages, broadcasting progress via callback.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.status = "running"
        session.query = query

        # Shared context — the OASIS "environment"
        env: Dict[str, Any] = {
            "query": query,
            "implied_probability": implied_probability or 0.5,
            "market_odds": market_odds,
            "context": context,
            "session_id": session_id,
        }

        # Inject memory context if enabled
        await self._inject_memory_context(env, query)

        try:
            # ── Stage 1: Scan & Parse ────────────────────────────────────
            logger.info("stage_1_start", session_id=session_id)
            scanner_out = await self._run_agent(
                self.scanner, env, session, on_progress
            )
            env["scanner_output"] = scanner_out.output

            parser_out = await self._run_agent(
                self.parser, env, session, on_progress
            )
            env["parsed_event"] = parser_out.output
            session.parsed_event = self._to_parsed_event(parser_out.output)

            # ── Stage 2: Research ────────────────────────────────────────
            logger.info("stage_2_start", session_id=session_id)
            raw_sources = await self.research_service.search(
                query=query,
                parsed_event=parser_out.output,
            )
            env["raw_sources"] = raw_sources

            research_out = await self._run_agent(
                self.researcher, env, session, on_progress
            )
            env["research_output"] = research_out.output
            env["research_data"] = research_out.output

            # ── Stage 3: Predict + Analyze (parallel) ───────────────────
            logger.info("stage_3_start", session_id=session_id)
            predictor_out = await self._run_agent(
                self.predictor, env, session, on_progress
            )
            env["predictor_output"] = predictor_out.output

            # Analyst and Skeptic run in parallel (OASIS parallel coordination)
            analyst_out, skeptic_out = await asyncio.gather(
                self._run_agent(self.analyst, env, session, on_progress),
                self._run_agent(self.skeptic, env, session, on_progress),
            )
            env["analyst_output"] = analyst_out.output
            env["skeptic_output"] = skeptic_out.output

            # ── Stage 4: Scenario Simulation ────────────────────────────
            logger.info("stage_4_start", session_id=session_id)
            scenario_out = await self._run_agent(
                self.scenario, env, session, on_progress
            )
            env["scenario_output"] = scenario_out.output

            # ── Stage 5: Validation ──────────────────────────────────────
            logger.info("stage_5_start", session_id=session_id)
            validator_out = await self._run_agent(
                self.validator, env, session, on_progress
            )
            env["validator_output"] = validator_out.output

            # ── Stage 6: Synthesis ───────────────────────────────────────
            logger.info("stage_6_start", session_id=session_id)
            synthesizer_out = await self._run_agent(
                self.synthesizer, env, session, on_progress
            )
            env["synthesizer_output"] = synthesizer_out.output

            # ── Stage 7: Scoring ─────────────────────────────────────────
            logger.info("stage_7_start", session_id=session_id)
            scoring_out = await self._run_agent(
                self.scorer, env, session, on_progress
            )
            env["scoring_output"] = scoring_out.output

            # ── Final Decision Assembly ───────────────────────────────────
            final_decision = self.decision_engine.assemble(
                agent_outputs=env,
                agent_output_objects=session.agent_outputs,
                implied_probability=implied_probability or 0.5,
            )
            session.final_decision = final_decision
            session.status = "completed"
            session.completed_at = datetime.utcnow()

            # Persist to memory
            await self._persist_session(session)

            logger.info(
                "analysis_complete",
                session_id=session_id,
                decision=final_decision.decision,
                confidence=final_decision.confidence_score,
            )

        except Exception as e:
            logger.error("analysis_error", session_id=session_id, error=str(e))
            session.status = "error"
            session.error = str(e)
            await self._persist_session(session)

        return session

    # ─────────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────────

    async def _run_agent(
        self,
        agent,
        env: Dict[str, Any],
        session: AnalysisSession,
        on_progress: Optional[ProgressCallback],
    ) -> AgentOutput:
        """Run a single agent step and append output to session."""
        # Broadcast start
        start_output = AgentOutput(
            role=agent.ROLE,
            agent_name=agent.AGENT_NAME,
            status="running",
            output={},
            processing_time_ms=0,
        )
        if on_progress:
            on_progress(start_output)

        # Execute agent
        output = await agent.step(env)
        session.agent_outputs.append(output)

        # Broadcast completion
        if on_progress:
            on_progress(output)

        return output

    async def _inject_memory_context(self, env: Dict[str, Any], query: str):
        """Inject relevant historical decisions into the environment."""
        try:
            past = await self.memory.get_similar_past_decisions(query, limit=2)
            if past:
                env["historical_context"] = past
                logger.debug("memory_injected", count=len(past))
        except Exception as e:
            logger.warning("memory_inject_failed", error=str(e))

    async def _persist_session(self, session: AnalysisSession):
        """Save session to the memory layer."""
        try:
            decision = None
            confidence = None
            predicted_prob = None
            edge = None

            if session.final_decision:
                decision = session.final_decision.decision
                confidence = session.final_decision.confidence_score
                predicted_prob = session.final_decision.predicted_probability
                edge = session.final_decision.edge

            await self.memory.save_session({
                "session_id": session.session_id,
                "query": session.query,
                "event_type": session.parsed_event.event_type if session.parsed_event else None,
                "status": session.status,
                "agent_outputs": [o.model_dump() for o in session.agent_outputs],
                "parsed_event": session.parsed_event.model_dump() if session.parsed_event else None,
                "final_decision": session.final_decision.model_dump() if session.final_decision else None,
                "decision": str(decision) if decision else None,
                "confidence": confidence,
                "predicted_prob": predicted_prob,
                "edge": edge,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
                "error": session.error,
            })
        except Exception as e:
            logger.error("persist_session_failed", error=str(e))

    @staticmethod
    def _to_parsed_event(output: Dict[str, Any]):
        """Convert parser output dict to ParsedEvent model."""
        from backend.api.models import ParsedEvent, EventType
        try:
            return ParsedEvent(
                event_type=output.get("event_type", "other"),
                sport=output.get("sport"),
                teams=output.get("teams", []) or output.get("players", []),
                players=output.get("players", []),
                outcome_description=output.get(
                    "prediction_target",
                    output.get("outcome_description", "")
                ),
                timeframe=output.get("timeframe_description", output.get("timeframe", "")),
                market_type=output.get("market_type", ""),
                implied_probability=output.get("implied_probability"),
                raw_query=output.get("canonical_query", ""),
            )
        except Exception:
            return ParsedEvent()


# Singleton orchestrator
_orchestrator: Optional[OASISOrchestrator] = None


def get_orchestrator() -> OASISOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OASISOrchestrator()
    return _orchestrator
