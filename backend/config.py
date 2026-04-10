"""
Central configuration for the AI Decision System.
Loads from environment variables / .env file.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────
    LLM_PROVIDER: str = Field("anthropic", description="LLM backend: anthropic | openai")
    LLM_MODEL: str = Field("claude-opus-4-6", description="Model identifier")
    AGENT_TEMPERATURE: float = Field(0.7, ge=0.0, le=1.0)

    # ── API Keys ──────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field("", description="Anthropic API key")
    OPENAI_API_KEY: str = Field("", description="OpenAI API key")
    SERPER_API_KEY: str = Field("", description="Serper.dev Google search key")
    TAVILY_API_KEY: str = Field("", description="Tavily AI search key")

    # ── App ───────────────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    DEMO_MODE: bool = Field(False, description="Simulated responses, no API keys needed")

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/decisions.db"

    # ── Research ──────────────────────────────────────────────────────
    MAX_RESEARCH_SOURCES: int = 5

    # ── Scoring thresholds ────────────────────────────────────────────
    BET_EDGE_THRESHOLD: float = 0.10
    BET_CONFIDENCE_THRESHOLD: float = 0.65
    WATCH_EDGE_THRESHOLD: float = 0.03
    MAX_RISK_FOR_BET: float = 0.70

    # ── Memory ───────────────────────────────────────────────────────
    ENABLE_MEMORY: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
