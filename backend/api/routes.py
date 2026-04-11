"""
API Routes  (updated — Polymarket endpoint, BetType param, SSE cleanup)
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from backend.api.models import (
    AnalysisRequest, AnalysisResponse, BetType,
    HistoryItem, HistoryResponse, SessionStatusResponse,
)
from backend.core.memory             import get_memory
from backend.core.orchestrator       import get_orchestrator
from backend.services.market_service import get_market_service
from backend.services.polymarket_service import get_polymarket_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api")

# Per-session SSE queues  {session_id: asyncio.Queue}
_sse_queues: Dict[str, asyncio.Queue] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalysisResponse)
async def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    """Start a new analysis session. Returns session_id immediately."""
    orchestrator = get_orchestrator()
    market       = get_market_service()

    implied_prob = req.implied_probability
    if not implied_prob and req.market_odds:
        implied_prob = market.parse_odds(req.market_odds)

    session_id = orchestrator.create_session(query=req.query, bet_type=req.bet_type)

    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_queues[session_id] = queue

    from backend.api.models import AgentOutput

    def on_progress(agent_out: AgentOutput):
        try:
            queue.put_nowait({
                "event": "agent_running" if agent_out.status == "running" else "agent_complete",
                "data":  agent_out.model_dump(mode="json"),
            })
        except asyncio.QueueFull:
            pass   # drop if consumer is too slow

    background_tasks.add_task(
        _run_bg,
        session_id=session_id,
        query=req.query,
        bet_type=req.bet_type,
        implied_probability=implied_prob,
        market_odds=req.market_odds,
        context=req.context,
        on_progress=on_progress,
        queue=queue,
    )

    logger.info("analysis_started", sid=session_id, query=req.query[:60])
    return AnalysisResponse(
        session_id=session_id,
        status="running",
        message=f"Analysis started. Stream: /api/analyze/{session_id}/stream",
    )


@router.get("/analyze/{session_id}/stream")
async def stream_analysis(session_id: str):
    """SSE stream of real-time agent progress."""
    queue = _sse_queues.get(session_id)
    if queue is None:
        # Already completed — return a single done event
        orchestrator = get_orchestrator()
        sess = orchestrator.get_session(session_id)
        if not sess:
            raise HTTPException(404, f"Session {session_id} not found")

        async def _done():
            yield {"event": "session_complete", "data": json.dumps(_sess_dict(sess))}

        return EventSourceResponse(_done())

    async def _generator():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=180.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": "{}"}
                    continue

                if ev.get("event") == "session_complete":
                    yield {"event": "session_complete",
                           "data": json.dumps(ev.get("data", {}))}
                    break
                elif ev.get("event") == "error":
                    yield {"event": "error",
                           "data": json.dumps({"error": ev.get("error", "Unknown")})}
                    break
                else:
                    yield {"event": ev["event"],
                           "data": json.dumps(ev["data"])}
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}
        finally:
            _sse_queues.pop(session_id, None)   # cleanup

    return EventSourceResponse(_generator())


@router.get("/analyze/{session_id}", response_model=SessionStatusResponse)
async def get_analysis(session_id: str):
    orchestrator = get_orchestrator()
    memory       = get_memory()

    sess = orchestrator.get_session(session_id)
    if sess:
        return SessionStatusResponse(
            session_id=session_id, status=sess.status,
            agent_outputs=sess.agent_outputs,
            final_decision=sess.final_decision, error=sess.error,
        )

    db = await memory.get_session(session_id)
    if db:
        return SessionStatusResponse(
            session_id=session_id,
            status=db.get("status", "unknown"),
            agent_outputs=[],
            final_decision=db.get("final_decision"),
            error=db.get("error"),
        )

    raise HTTPException(404, f"Session {session_id} not found")


# ─────────────────────────────────────────────────────────────────────────────
# Polymarket
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/polymarket/search")
async def polymarket_search(
    q:        str      = Query(..., min_length=2),
    bet_type: BetType  = Query(BetType.MATCH_WINNER),
    limit:    int      = Query(5, ge=1, le=20),
):
    """Search Polymarket Gamma API for prediction markets."""
    svc = get_polymarket_service()
    markets = await svc.search_markets(query=q, bet_type=bet_type.value, limit=limit)
    return {"markets": markets, "count": len(markets)}


# ─────────────────────────────────────────────────────────────────────────────
# History & calibration
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/history", response_model=HistoryResponse)
async def get_history(
    limit:  int = Query(20, ge=1, le=100),
    offset: int = Query(0,  ge=0),
):
    memory  = get_memory()
    rows    = await memory.get_history(limit=limit, offset=offset)
    total   = await memory.get_total_sessions()
    items   = [
        HistoryItem(
            session_id=r["session_id"], query=r["query"],
            decision=r.get("decision"), confidence=r.get("confidence"),
            created_at=_parse_dt(r.get("created_at")),
            status=r.get("status", "unknown"),
        )
        for r in rows
    ]
    return HistoryResponse(items=items, total=total)


@router.post("/outcome/{session_id}")
async def record_outcome(
    session_id:    str,
    actual_outcome: str  = Query(...),
    was_correct:   bool  = Query(...),
):
    memory = get_memory()
    if not await memory.get_session(session_id):
        raise HTTPException(404, "Session not found")
    await memory.record_outcome(session_id, actual_outcome, was_correct)
    return {"status": "recorded"}


# ─────────────────────────────────────────────────────────────────────────────
# System
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    from backend.config import settings
    return {
        "status":       "healthy",
        "version":      "2.0.0",
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model":    settings.LLM_MODEL,
        "demo_mode":    settings.DEMO_MODE,
        "timestamp":    datetime.utcnow().isoformat(),
    }


@router.get("/stats")
async def stats():
    memory      = get_memory()
    total       = await memory.get_total_sessions()
    calibration = await memory.get_calibration_stats()
    return {"total_analyses": total, "calibration": calibration,
            "agents": 10, "pipeline_stages": 8}


# ─────────────────────────────────────────────────────────────────────────────
# Background task
# ─────────────────────────────────────────────────────────────────────────────

async def _run_bg(session_id, query, bet_type, implied_probability,
                  market_odds, context, on_progress, queue):
    try:
        orchestrator = get_orchestrator()
        sess = await orchestrator.run_analysis(
            session_id=session_id, query=query, bet_type=bet_type,
            implied_probability=implied_probability, market_odds=market_odds,
            context=context, on_progress=on_progress,
        )
        queue.put_nowait({"event": "session_complete", "data": _sess_dict(sess)})
    except Exception as exc:
        logger.error("bg_error", sid=session_id, error=str(exc))
        queue.put_nowait({"event": "error", "error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sess_dict(sess) -> Dict[str, Any]:
    return {
        "session_id":    sess.session_id,
        "status":        sess.status,
        "query":         sess.query,
        "final_decision": (sess.final_decision.model_dump(mode="json")
                           if sess.final_decision else None),
        "agent_count":   len(sess.agent_outputs),
        "error":         sess.error,
    }


def _parse_dt(s) -> datetime:
    if not s:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.utcnow()
