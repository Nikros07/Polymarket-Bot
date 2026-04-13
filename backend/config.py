"""
Central configuration for the AI Decision System.
All settings load from environment variables or a .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────
    LLM_PROVIDER: str = Field("openrouter", description="LLM backend: anthropic | openai | openrouter")
    LLM_MODEL: str = Field("meta-llama/llama-3.3-70b-instruct:free", description="Model identifier")
    AGENT_TEMPERATURE: float = Field(0.7, ge=0.0, le=1.0)
    LLM_MAX_TOKENS: int = Field(2048, description="Max output tokens; use ≤2048 for free OpenRouter models")

    # ── API Keys ──────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field("", description="Anthropic API key")
    OPENAI_API_KEY: str = Field("", description="OpenAI API key")
    OPENROUTER_API_KEY: str = Field("", description="OpenRouter API key (openrouter.ai)")
    SERPER_API_KEY: str = Field("", description="Serper.dev Google search key")
    TAVILY_API_KEY: str = Field("", description="Tavily AI search key")

    # ── Polymarket ────────────────────────────────────────────────────────
    POLYMARKET_GAMMA_API: str = "https://gamma-api.polymarket.com"
    POLYMARKET_CLOB_API: str  = "https://clob.polymarket.com"
    POLYMARKET_MAX_MARKETS: int = 5          # Max markets to show per search
    POLYMARKET_FEE_RATE: float = Field(0.02, description="Polymarket trading fee deducted from edge (2%)")
    POLYMARKET_MIN_VOLUME: float = Field(500.0, description="Min USD volume to include a market in results")

    # ── App ───────────────────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    DEMO_MODE: bool = Field(False, description="Simulated responses, no API keys")

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/decisions.db"

    # ── Research (Tavily cost control) ────────────────────────────────────
    TAVILY_MAX_RESULTS: int = Field(4, ge=1, le=10, description="Keep low to save API credits")
    TAVILY_SEARCH_DEPTH: str = Field("basic", description="basic=1 credit, advanced=2 credits")
    RESEARCH_CACHE_TTL_SECONDS: int = 300    # Cache same queries for 5 min

    # ── Scoring thresholds ────────────────────────────────────────────────
    BET_EDGE_THRESHOLD: float = 0.10
    BET_CONFIDENCE_THRESHOLD: float = 0.65
    WATCH_EDGE_THRESHOLD: float = 0.03
    MAX_RISK_FOR_BET: float = 0.70

    # ── Position Sizing (Kelly Criterion) ─────────────────────────────────
    KELLY_FRACTION: float = Field(0.25, description="Kelly multiplier (0.25=quarter-Kelly, conservative)")

    # ── Memory ────────────────────────────────────────────────────────────
    ENABLE_MEMORY: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
