"""
AI Decision System — FastAPI Application Entry Point
====================================================
Initializes the OASIS multi-agent decision engine and serves the
web application (API + static frontend).

Start with: uvicorn backend.main:app --reload --port 8000
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.api.routes import router
from backend.config import settings
from backend.core.memory import get_memory

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    logger.info(
        "ai_decision_system_starting",
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
        demo_mode=settings.DEMO_MODE,
    )

    # Initialize memory layer (creates DB schema)
    memory = get_memory()
    await memory.initialize()

    # Validate LLM configuration
    if not settings.DEMO_MODE:
        if settings.LLM_PROVIDER == "anthropic" and not settings.ANTHROPIC_API_KEY:
            logger.warning(
                "anthropic_key_missing",
                hint="Set ANTHROPIC_API_KEY in .env or enable DEMO_MODE=true",
            )
        elif settings.LLM_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
            logger.warning(
                "openai_key_missing",
                hint="Set OPENAI_API_KEY in .env or enable DEMO_MODE=true",
            )
        elif settings.LLM_PROVIDER == "openrouter" and not settings.OPENROUTER_API_KEY:
            logger.warning(
                "openrouter_key_missing",
                hint="Set OPENROUTER_API_KEY in .env or enable DEMO_MODE=true",
            )

    logger.info("ai_decision_system_ready", host=settings.APP_HOST, port=settings.APP_PORT)
    yield

    # Shutdown
    logger.info("ai_decision_system_shutdown")


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Decision System",
    description=(
        "Production-ready multi-agent decision engine powered by OASIS. "
        "Analyzes sports betting, prediction markets, and event-based decisions "
        "using a 10-agent collaborative reasoning pipeline."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# Serve frontend static files
if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )

    @app.get("/")
    async def serve_frontend():
        """Serve the frontend dashboard."""
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "AI Decision System API", "docs": "/docs"}
else:
    @app.get("/")
    async def root():
        return {
            "message": "AI Decision System API",
            "docs": "/docs",
            "health": "/api/health",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Dev entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
