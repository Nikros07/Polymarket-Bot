"""
OASIS-Compatible Base Agent Framework
======================================
Implements the core agent interface inspired by OASIS (Camel-AI) multi-agent
orchestration principles. Each agent is a self-contained reasoning unit with:
  - A defined role and system prompt
  - Structured input/output contracts
  - LLM-powered reasoning (Anthropic Claude or OpenAI)
  - Confidence scoring
  - Error handling and fallback modes

OASIS Principles Applied:
  - Agents observe shared environment (context dict)
  - Agents communicate via structured messages
  - Disagreement is expected and preserved
  - Reasoning must be transparent and auditable
"""
import asyncio
import json
import time
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
from datetime import datetime

import anthropic
import structlog

from backend.config import settings
from backend.api.models import AgentOutput, AgentRole

logger = structlog.get_logger(__name__)

T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# LLM Client Abstraction
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """Unified LLM client supporting Anthropic and OpenAI providers."""

    def __init__(self):
        self._anthropic: Optional[anthropic.AsyncAnthropic] = None
        self._openai = None
        self._init_clients()

    def _init_clients(self):
        if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            self._anthropic = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
        elif settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                self._openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            except ImportError:
                logger.warning("openai package not available")

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = None,
        max_tokens: int = 4096,
    ) -> str:
        """Send a completion request to the configured LLM provider."""
        temp = temperature if temperature is not None else settings.AGENT_TEMPERATURE

        if settings.DEMO_MODE:
            return self._demo_response(system_prompt, user_message)

        if self._anthropic:
            return await self._anthropic_complete(
                system_prompt, user_message, temp, max_tokens
            )
        elif self._openai:
            return await self._openai_complete(
                system_prompt, user_message, temp, max_tokens
            )
        else:
            logger.warning("No LLM client available, using demo mode")
            return self._demo_response(system_prompt, user_message)

    async def _anthropic_complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = await self._anthropic.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def _openai_complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content

    def _demo_response(self, system_prompt: str, user_message: str) -> str:
        """Generate a plausible demo response without calling an LLM."""
        role_hint = system_prompt[:100].lower()
        if "scanner" in role_hint:
            return json.dumps({
                "event_type": "sports",
                "sport": "football",
                "teams": ["Team A", "Team B"],
                "outcome": "Team A wins",
                "timeframe": "upcoming match",
                "confidence": 0.7
            })
        elif "research" in role_hint:
            return json.dumps({
                "key_facts": ["Team A has won 4 of last 5 matches", "Home advantage significant"],
                "recent_news": ["Team A in good form", "No major injuries reported"],
                "data_quality_score": 0.65,
                "summary": "Team A appears to be in strong form heading into this fixture."
            })
        elif "predict" in role_hint:
            return json.dumps({
                "predicted_probability": 0.62,
                "reasoning": "Based on recent form and historical performance, Team A has a clear edge.",
                "key_factors": ["Recent form", "Home advantage", "Head-to-head record"],
                "uncertainty_factors": ["Weather conditions", "Potential tactical changes"]
            })
        elif "analyst" in role_hint or "bull" in role_hint:
            return json.dumps({
                "bull_case": "Strong recent form and favorable conditions point to a positive outcome.",
                "bull_factors": ["5-game win streak", "Strong home record", "Opponent weaknesses"],
                "argument_strength": 0.72,
                "supporting_evidence": ["4W-1D in last 5", "Opponent missing key players"]
            })
        elif "skeptic" in role_hint or "bear" in role_hint:
            return json.dumps({
                "bear_case": "Market may be over-pricing the favorite. Historical variance is high.",
                "bear_factors": ["Overvalued by market", "Historical upset rate", "Fixture congestion"],
                "counter_argument_strength": 0.58,
                "risks": ["Short odds leave little value", "Cup fatigue possible"],
                "flaws": ["Small sample size", "Ignores opponent's recent away form"]
            })
        elif "scenario" in role_hint:
            return json.dumps({
                "scenarios": [
                    {"name": "Dominant Win", "probability": 0.35, "description": "Clear victory", "outcome": "WIN", "impact": "High value"},
                    {"name": "Narrow Win", "probability": 0.27, "description": "Close but wins", "outcome": "WIN", "impact": "Moderate value"},
                    {"name": "Draw", "probability": 0.22, "description": "Balanced contest", "outcome": "DRAW", "impact": "Loss"},
                    {"name": "Upset Loss", "probability": 0.16, "description": "Underdog wins", "outcome": "LOSS", "impact": "Full loss"}
                ],
                "most_likely": "Narrow Win",
                "tail_risk": "Upset Loss (16% probability) represents significant downside."
            })
        elif "valid" in role_hint:
            return json.dumps({
                "is_consistent": True,
                "logical_issues": [],
                "data_quality_flags": ["Limited historical data available"],
                "bias_warnings": ["Recency bias possible in form analysis"],
                "adjusted_confidence": 0.63,
                "validation_score": 0.75
            })
        elif "synth" in role_hint:
            return json.dumps({
                "summary": "Agents generally agree on a moderate edge, with the skeptic raising valid concerns about market pricing.",
                "key_insights": ["Clear form advantage", "Market may be pricing correctly", "Risk is manageable"],
                "agent_agreement_level": 0.68,
                "conflicts": ["Analyst and Skeptic disagree on market efficiency"],
                "final_probability": 0.60,
                "narrative": "The weight of evidence suggests a genuine but modest edge."
            })
        else:
            return json.dumps({
                "composite_score": 0.63,
                "edge": 0.10,
                "decision": "WATCH",
                "confidence": 0.63,
                "risk_level": 0.45
            })


# Singleton LLM client
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


# ─────────────────────────────────────────────────────────────────────────────
# OASIS Base Agent
# ─────────────────────────────────────────────────────────────────────────────

class OASISBaseAgent(ABC):
    """
    Base class for all OASIS-compatible decision agents.

    Implements the OASIS agent contract:
      - observe(environment) → perceive shared context
      - act(observation) → produce structured output
      - step(context) → observe + act + return output

    Each subclass MUST implement:
      - ROLE: AgentRole
      - AGENT_NAME: str
      - SYSTEM_PROMPT: str
      - _parse_response(raw: str) → dict
    """

    ROLE: AgentRole = NotImplemented
    AGENT_NAME: str = NotImplemented
    SYSTEM_PROMPT: str = NotImplemented
    TEMPERATURE: float = None  # Uses settings.AGENT_TEMPERATURE if None

    def __init__(self):
        self.llm = get_llm_client()
        self._logger = structlog.get_logger(self.AGENT_NAME)

    # ── OASIS Interface ────────────────────────────────────────────────────

    def observe(self, environment: Dict[str, Any]) -> str:
        """
        OASIS observe() — Extract relevant context from the shared environment.
        Converts the environment dict into a prompt-ready string.
        """
        return self._build_user_message(environment)

    async def act(self, observation: str) -> Dict[str, Any]:
        """
        OASIS act() — Reason about the observation and produce output.
        Calls the LLM and parses structured output.
        """
        raw = await self.llm.complete(
            system_prompt=self.SYSTEM_PROMPT,
            user_message=observation,
            temperature=self.TEMPERATURE,
        )
        return self._safe_parse(raw)

    async def step(self, context: Dict[str, Any]) -> AgentOutput:
        """
        OASIS step() — Full observe → act → output cycle.
        Returns a structured AgentOutput with timing and metadata.
        """
        start_ms = int(time.time() * 1000)

        try:
            self._logger.info("agent_step_start", agent=self.AGENT_NAME)
            observation = self.observe(context)
            output_dict = await self.act(observation)
            confidence = self._extract_confidence(output_dict)

            elapsed = int(time.time() * 1000) - start_ms
            self._logger.info(
                "agent_step_complete",
                agent=self.AGENT_NAME,
                elapsed_ms=elapsed,
                confidence=confidence,
            )

            return AgentOutput(
                role=self.ROLE,
                agent_name=self.AGENT_NAME,
                status="completed",
                output=output_dict,
                reasoning=output_dict.get("reasoning", output_dict.get("summary", "")),
                confidence=confidence,
                processing_time_ms=elapsed,
            )

        except Exception as e:
            elapsed = int(time.time() * 1000) - start_ms
            self._logger.error("agent_step_error", agent=self.AGENT_NAME, error=str(e))
            return AgentOutput(
                role=self.ROLE,
                agent_name=self.AGENT_NAME,
                status="error",
                output={},
                reasoning="",
                confidence=0.0,
                processing_time_ms=elapsed,
                error=str(e),
            )

    # ── Abstract Methods (subclasses implement) ────────────────────────────

    @abstractmethod
    def _build_user_message(self, context: Dict[str, Any]) -> str:
        """Convert shared context into agent-specific user message."""
        ...

    # ── Helpers ────────────────────────────────────────────────────────────

    def _safe_parse(self, raw: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("```").strip()

        # Try to find JSON object
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try the whole string
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Return raw as text output
            return {"raw_output": raw, "reasoning": raw}

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        """Extract confidence from various possible field names."""
        for key in ("confidence", "adjusted_confidence", "validation_score", "data_quality_score"):
            val = output.get(key)
            if isinstance(val, (int, float)):
                return float(max(0.0, min(1.0, val)))
        return 0.5

    @staticmethod
    def _format_context_section(title: str, data: Any) -> str:
        """Format a context section for prompt injection."""
        if isinstance(data, dict):
            content = json.dumps(data, indent=2)
        elif isinstance(data, list):
            content = "\n".join(f"  - {item}" for item in data)
        else:
            content = str(data)
        return f"\n## {title}\n{content}\n"
