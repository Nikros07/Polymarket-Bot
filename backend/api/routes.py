"""
API Routes
==========
FastAPI router implementing all REST endpoints and SSE streaming.

Endpoints:
  POST /api/analyze              → Start analysis session
  GET  /api/analyze/{id}/stream  → SSE stream of agent progress
  GET  /api/analyze/{id}         → Get session status and results
  GET  /api/history              → Get analysis history
  POST /api/outcome/{id}         → Record actual outcome (calibration)
  GET  /api/health               → Health check
  GET  /api/stats                → System statistics
"""
import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from backend.api.models import (
    AgentOutput,
    AnalysisRequest,
    AnalysisResponse,
    HistoryItem,
    HistoryResponse,
    SessionStatusResponse,
)
from backend.core.memory import get_memory
from backend.core.orchestrator import get_orchestrator
from backend.services.market_service import get_market_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api")

# In-memory SSE queues per session
_sse_queues: Dict[str, asyncio.Queue] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Analysis Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalysisResponse)
async def start_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a new multi-agent analysis session.
    Returns session_id immediately; use /analyze/{id}/stream for live updates.
    """
    orchestrator = get_orchestrator()
    market = get_market_service()

    # Parse implied probability from odds string
    implied_prob = request.implied_probability
    if not implied_prob and request.market_odds:
        implied_prob = market.parse_odds(request.market_odds)

    # Create session
    session_id = orchestrator.create_session(
        query=request.query,
        implied_probability=implied_prob,
    )

    # Create SSE queue for this session
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues[session_id] = queue

    def on_progress(agent_output: AgentOutput):
        """Callback fired by each agent — puts event into SSE queue."""
        try:
            queue.put_nowait({
                "event": (
                    "agent_running" if agent_output.status == "running"
                    else "agent_complete"
                ),
                "data": agent_output.model_dump(mode="json"),
            })
        except asyncio.QueueFull:
            logger.warning("sse_queue_full", session_id=session_id)

    # Run analysis in background
    background_tasks.add_task(
        _run_analysis_background,
        session_id=session_id,
        query=request.query,
        implied_probability=implied_prob,
        market_odds=request.market_odds,
        context=request.context,
        on_progress=on_progress,
        queue=queue,
    )

    logger.info("analysis_started", session_id=session_id, query=request.query[:80])
    return AnalysisResponse(
        session_id=session_id,
        status="running",
        message="Analysis started. Connect to /api/analyze/{session_id}/stream for live updates.",
    )


@router.get("/analyze/{session_id}/stream")
async def stream_analysis(session_id: str):
    """
    SSE endpoint — streams real-time agent progress for a session.
    Events: agent_running, agent_complete, session_complete, error
    """
    queue = _sse_queues.get(session_id)
    if queue is None:
        # Session might already be complete, check DB
        orchestrator = get_orchestrator()
        session = orchestrator.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Session complete — send final event
        async def complete_stream():
            yield {
                "event": "session_complete",
                "data": json.dumps(_session_to_dict(session)),
            }
        return EventSourceResponse(complete_stream())

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "keepalive", "data": "{}"}
                    continue

                if event.get("event") == "session_complete":
                    yield {
                        "event": "session_complete",
                        "data": json.dumps(event.get("data", {})),
                    }
                    break
                elif event.get("event") == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": event.get("error", "Unknown error")}),
                    }
                    break
                else:
                    yield {
                        "event": event["event"],
                        "data": json.dumps(event["data"]),
                    }
        except Exception as e:
            logger.error("sse_stream_error", session_id=session_id, error=str(e))
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
        finally:
            _sse_queues.pop(session_id, None)

    return EventSourceResponse(event_generator())


@router.get("/analyze/{session_id}", response_model=SessionStatusResponse)
async def get_analysis(session_id: str):
    """Get the current status and results of an analysis session."""
    orchestrator = get_orchestrator()
    memory = get_memory()

    # Check in-memory first
    session = orchestrator.get_session(session_id)
    if session:
        return SessionStatusResponse(
            session_id=session_id,
            status=session.status,
            agent_outputs=session.agent_outputs,
            final_decision=session.final_decision,
            error=session.error,
        )

    # Check database
    db_session = await memory.get_session(session_id)
    if db_session:
        return SessionStatusResponse(
            session_id=session_id,
            status=db_session.get("status", "unknown"),
            agent_outputs=[],
            final_decision=db_session.get("final_decision"),
            error=db_session.get("error"),
        )

    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# History & Calibration
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/history", response_model=HistoryResponse)
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get paginated analysis history."""
    memory = get_memory()
    items_raw = await memory.get_history(limit=limit, offset=offset)
    total = await memory.get_total_sessions()

    items = [
        HistoryItem(
            session_id=row["session_id"],
            query=row["query"],
            decision=row.get("decision"),
            confidence=row.get("confidence"),
            created_at=_parse_dt(row.get("created_at")),
            status=row.get("status", "unknown"),
        )
        for row in items_raw
    ]

    return HistoryResponse(items=items, total=total)


@router.post("/outcome/{session_id}")
async def record_outcome(
    session_id: str,
    actual_outcome: str = Query(..., description="What actually happened"),
    was_correct: bool = Query(..., description="Did the system's prediction prove correct?"),
):
    """Record the actual outcome for calibration and learning."""
    memory = get_memory()
    session = await memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await memory.record_outcome(session_id, actual_outcome, was_correct)
    return {"status": "recorded", "session_id": session_id}


# ─────────────────────────────────────────────────────────────────────────────
# System Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check():
    """System health check."""
    from backend.config import settings
    return {
        "status": "healthy",
        "version": "1.0.0",
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "demo_mode": settings.DEMO_MODE,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stats")
async def get_stats():
    """Get system statistics including calibration metrics."""
    memory = get_memory()
    total = await memory.get_total_sessions()
    calibration = await memory.get_calibration_stats()

    return {
        "total_analyses": total,
        "calibration": calibration,
        "agents": [
            "ScannerAgent", "InputParserAgent", "ResearchAgent",
            "PredictorAgent", "AnalystAgent", "SkepticAgent",
            "ScenarioAgent", "ValidatorAgent", "SynthesizerAgent",
            "ScoringAgent"
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Background Task
# ─────────────────────────────────────────────────────────────────────────────

async def _run_analysis_background(
    session_id: str,
    query: str,
    implied_probability: Optional[float],
    market_odds: Optional[str],
    context: Optional[str],
    on_progress,
    queue: asyncio.Queue,
):
    """Background coroutine that runs the full analysis pipeline."""
    try:
        orchestrator = get_orchestrator()
        session = await orchestrator.run_analysis(
            session_id=session_id,
            query=query,
            implied_probability=implied_probability,
            market_odds=market_odds,
            context=context,
            on_progress=on_progress,
        )

        # Emit session_complete event
        queue.put_nowait({
            "event": "session_complete",
            "data": _session_to_dict(session),
        })

    except Exception as e:
        logger.error("background_analysis_error", session_id=session_id, error=str(e))
        queue.put_nowait({
            "event": "error",
            "error": str(e),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _session_to_dict(session) -> Dict[str, Any]:
    """Convert AnalysisSession to JSON-serializable dict."""
    return {
        "session_id": session.session_id,
        "status": session.status,
        "query": session.query,
        "final_decision": (
            session.final_decision.model_dump(mode="json")
            if session.final_decision
            else None
        ),
        "agent_count": len(session.agent_outputs),
        "error": session.error,
    }


def _parse_dt(dt_str) -> datetime:
    if not dt_str:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.utcnow()
