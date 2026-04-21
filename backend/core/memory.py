"""
Memory Layer
============
Stores past decisions, detects patterns, and supports cross-session learning.
Uses SQLite via aiosqlite for async-safe persistence.
"""
import json
import asyncio
import aiosqlite
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "decisions.db"


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_sessions (
    session_id      TEXT PRIMARY KEY,
    query           TEXT NOT NULL,
    query_hash      TEXT,
    event_type      TEXT,
    status          TEXT DEFAULT 'pending',
    agent_outputs   TEXT DEFAULT '[]',
    parsed_event    TEXT,
    final_decision  TEXT,
    decision        TEXT,
    confidence      REAL,
    predicted_prob  REAL,
    edge            REAL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    error           TEXT
)
"""

CREATE_OUTCOMES_TABLE = """
CREATE TABLE IF NOT EXISTS outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    outcome_result  TEXT,
    actual_outcome  TEXT,
    was_correct     INTEGER,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES analysis_sessions(session_id)
)
"""

CREATE_PATTERNS_TABLE = """
CREATE TABLE IF NOT EXISTS detected_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type    TEXT NOT NULL,
    description     TEXT,
    occurrences     INTEGER DEFAULT 1,
    confidence      REAL,
    last_seen       TEXT,
    metadata        TEXT DEFAULT '{}'
)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Memory Manager
# ─────────────────────────────────────────────────────────────────────────────

class MemoryManager:
    """
    Async memory layer for the AI decision system.
    Provides persistence, pattern detection, and historical lookup.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Create database schema if not exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(CREATE_SESSIONS_TABLE)
            await db.execute(CREATE_OUTCOMES_TABLE)
            await db.execute(CREATE_PATTERNS_TABLE)
            await db.commit()
        self._initialized = True
        logger.info("memory_initialized", db_path=str(self.db_path))

    # ── Session Operations ─────────────────────────────────────────────────

    async def save_session(self, session: Dict[str, Any]):
        """Persist a session (upsert)."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO analysis_sessions
                (session_id, query, query_hash, event_type, status,
                 agent_outputs, parsed_event, final_decision, decision,
                 confidence, predicted_prob, edge, created_at, completed_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    session.get("query", ""),
                    self._hash_query(session.get("query", "")),
                    session.get("event_type"),
                    session.get("status", "pending"),
                    json.dumps(session.get("agent_outputs", [])),
                    json.dumps(session.get("parsed_event")) if session.get("parsed_event") else None,
                    json.dumps(session.get("final_decision")) if session.get("final_decision") else None,
                    session.get("decision"),
                    session.get("confidence"),
                    session.get("predicted_prob"),
                    session.get("edge"),
                    session.get("created_at", datetime.utcnow().isoformat()),
                    session.get("completed_at"),
                    session.get("error"),
                ),
            )
            await db.commit()

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session by ID."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return self._row_to_session(row) if row else None

    async def get_history(
        self, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get session history ordered by recency."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT session_id, query, decision, confidence, status, created_at
                   FROM analysis_sessions
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_total_sessions(self) -> int:
        """Get total count of sessions."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM analysis_sessions"
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ── Outcome Tracking ───────────────────────────────────────────────────

    async def record_outcome(
        self,
        session_id: str,
        actual_outcome: str,
        was_correct: bool,
    ):
        """Record what actually happened (for calibration)."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO outcomes (session_id, actual_outcome, was_correct, recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, actual_outcome, int(was_correct), datetime.utcnow().isoformat()),
            )
            await db.commit()

    # ── Pattern Detection ──────────────────────────────────────────────────

    async def get_similar_past_decisions(
        self, query: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Find similar past analyses for context injection.

        Results are ranked by keyword overlap count (most matching keywords
        first), with recency as a tiebreaker.
        """
        await self._ensure_initialized()
        keywords = query.lower().split()[:5]
        like_params = [f"%{kw}%" for kw in keywords]

        # Build a relevance score column by summing per-keyword CASE expressions.
        # This ranks rows with more matching keywords above those with fewer.
        relevance_expr = " + ".join(
            [f"CASE WHEN LOWER(query) LIKE ? THEN 1 ELSE 0 END" for _ in keywords]
        )
        filter_clause = " OR ".join(["LOWER(query) LIKE ?" for _ in keywords])

        # like_params appears twice: once for the SELECT relevance column,
        # once for the WHERE filter clause.
        params = like_params + like_params + [limit]

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT session_id, query, decision, confidence, predicted_prob, created_at,
                       ({relevance_expr}) AS relevance
                FROM analysis_sessions
                WHERE ({filter_clause}) AND status = 'completed'
                ORDER BY relevance DESC, created_at DESC
                LIMIT ?
                """,
                params,
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_calibration_stats(self) -> Dict[str, Any]:
        """Get accuracy statistics for confidence calibration."""
        await self._ensure_initialized()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(o.was_correct) as correct,
                    AVG(s.confidence) as avg_confidence
                FROM outcomes o
                JOIN analysis_sessions s ON o.session_id = s.session_id
                """
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0] > 0:
                    return {
                        "total_outcomes": row[0],
                        "correct": row[1] or 0,
                        "accuracy": (row[1] or 0) / row[0],
                        "avg_confidence": row[2] or 0.5,
                    }
                return {"total_outcomes": 0, "correct": 0, "accuracy": None, "avg_confidence": None}

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _ensure_initialized(self):
        if not self._initialized:
            await self.initialize()

    @staticmethod
    def _hash_query(query: str) -> str:
        import hashlib
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]

    @staticmethod
    def _row_to_session(row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("agent_outputs", "parsed_event", "final_decision"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d


# Singleton
_memory: Optional[MemoryManager] = None


def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory
