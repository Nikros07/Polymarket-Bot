"""
OASIS-Compatible Base Agent Framework
======================================
Uses camel-ai's ChatAgent as the LLM backend when available,
with a direct Anthropic/OpenAI fallback for robustness.

OASIS / camel-ai integration:
  - Each agent is a camel-ai ChatAgent with a distinct role
  - Shared context is the OASIS "environment"
  - observe() → act() → step() mirrors OASIS agent lifecycle
  - Agents communicate via BaseMessage when camel-ai is present
"""
import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar
from datetime import datetime

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import settings
from backend.api.models import AgentOutput, AgentRole

logger = structlog.get_logger(__name__)
T = TypeVar("T")

# ─────────────────────────────────────────────────────────────────────────────
# camel-ai detection — graceful import
# ─────────────────────────────────────────────────────────────────────────────
CAMEL_AVAILABLE = False
try:
    from camel.agents import ChatAgent as CamelChatAgent
    from camel.messages import BaseMessage
    from camel.types import RoleType
    CAMEL_AVAILABLE = True
    logger.info("camel_ai_available", status="using_camel_ai")
except ImportError:
    logger.info("camel_ai_not_installed", status="using_fallback_client",
                hint="pip install camel-ai to enable native OASIS support")


# ─────────────────────────────────────────────────────────────────────────────
# LLM Client (fallback when camel-ai is not present)
# ─────────────────────────────────────────────────────────────────────────────

class _FallbackLLMClient:
    """Direct Anthropic/OpenAI/OpenRouter client — used when camel-ai is not installed."""

    def __init__(self):
        self._anthropic = None
        self._openai = None
        self._init()

    def _init(self):
        if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            try:
                import anthropic as _ant
                self._anthropic = _ant.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                pass
        elif settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                self._openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            except ImportError:
                logger.warning("openai package not available")
        elif settings.LLM_PROVIDER == "openrouter" and settings.OPENROUTER_API_KEY:
            try:
                from openai import AsyncOpenAI
                self._openai = AsyncOpenAI(
                    api_key=settings.OPENROUTER_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                    default_headers={
                        "HTTP-Referer": "https://github.com/Nikros07/Polymarket-Bot",
                        "X-Title": "OASIS AI Decision System",
                    },
                )
                logger.info("openrouter_client_initialized", model=settings.LLM_MODEL)
            except ImportError:
                logger.warning("openai package not available — needed for OpenRouter")

    async def complete(self, system_prompt: str, user_message: str,
                       temperature: float = None, max_tokens: int = 4096) -> str:
        temp = temperature if temperature is not None else settings.AGENT_TEMPERATURE
        if settings.DEMO_MODE:
            return self._demo_response(system_prompt, user_message)

        try:
            if self._anthropic:
                return await self._anthropic_complete(
                    system_prompt, user_message, temp, max_tokens
                )
            elif self._openai:
                return await self._openai_complete(
                    system_prompt, user_message, temp, max_tokens
                )
            else:
                logger.warning("no_llm_client_configured_using_demo_fallback",
                               provider=settings.LLM_PROVIDER)
                return self._demo_response(system_prompt, user_message)
        except Exception as e:
            logger.warning(
                "llm_call_failed_fallback_to_demo",
                error=str(e),
                provider=settings.LLM_PROVIDER,
                model=settings.LLM_MODEL,
            )
            return self._demo_response(system_prompt, user_message)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
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
        elif "debate" in role_hint or "moderator" in role_hint:
            return json.dumps({
                "analyst_rebuttal": "The Analyst acknowledges the market risk concern but argues the form data strongly supports the prediction.",
                "skeptic_counter": "The Skeptic concedes the form data is solid but maintains that the implied probability already reflects it.",
                "key_disagreements": [
                    {
                        "topic": "Market efficiency",
                        "analyst_position": "Market has not fully priced in recent form improvement",
                        "skeptic_position": "Odds already incorporate the form advantage",
                        "resolution": "Partial — Analyst has stronger recent data"
                    }
                ],
                "analyst_concessions": ["Short odds leave limited upside", "Opponent not as weak as initial research suggested"],
                "skeptic_concessions": ["Recent form is genuinely strong", "Home advantage is real and significant"],
                "debate_winner": "analyst",
                "debate_summary": "Analyst's bull case holds up under scrutiny. The key debate was around market efficiency — Analyst produced more recent evidence supporting their position. Skeptic's main concern (limited value in tight odds) is valid but not sufficient to override the edge.",
                "consensus": "There is a genuine edge, but it is modest. Both sides agree the outcome is likely but not certain.",
                "post_debate_probability_range": {
                    "analyst_revised": 0.64,
                    "skeptic_revised": 0.58,
                    "midpoint": 0.61
                },
                "unresolved_conflicts": ["Exact size of home advantage in this specific context"],
                "confidence": 0.68,
                "reasoning": "The debate refined the initial estimate downward slightly, reflecting valid skeptic concerns about market efficiency."
            })
        elif "synth" in role_hint:
            return json.dumps({
                "summary": "Agents generally agree on a moderate edge, with the skeptic raising valid concerns about market pricing. The debate produced a refined estimate of ~60% probability.",
                "key_insights": ["Clear form advantage", "Market may be pricing correctly", "Risk is manageable", "Debate confirmed bull case holds under scrutiny"],
                "agent_agreement_level": 0.68,
                "conflicts": [{"agents": ["analyst", "skeptic"], "conflict": "Market efficiency — has the form improvement been priced in?", "resolution": "Analyst's more recent data tilts the debate in their favor"}],
                "final_probability": 0.62,
                "probability_adjustment": "Reduced by 2% from initial prediction due to valid skeptic concerns about market pricing",
                "confidence_adjustment": "Maintained at moderate level — debate confirmed edge but also confirmed uncertainty",
                "narrative": "The weight of evidence suggests a genuine but modest edge. Team A's recent form (4W-1D in last 5) provides a solid foundation. The market odds imply a 55% probability, and our multi-agent analysis suggests 62%, yielding a ~7% edge. The skeptic's concerns about luck vs. skill are partially valid but do not override the consistent statistical signal. This qualifies as a watchable opportunity.",
                "action_relevance": "The 7% edge exceeds the WATCH threshold. Consider if odds are available at 1.80 or better.",
                "key_uncertainties": ["Weather conditions day-of", "Potential last-minute lineup changes"],
                "agent_weight_rationale": "Predictor and Analyst weighted most heavily due to strong data quality. Skeptic weighted 15% as a bias corrector.",
                "sports_predictions": {
                    "home_win_probability": 0.55,
                    "draw_probability": 0.24,
                    "away_win_probability": 0.21,
                    "over_2_5_probability": 0.62,
                    "under_2_5_probability": 0.38,
                    "btts_yes_probability": 0.58,
                    "btts_no_probability": 0.42
                },
                "persona_probabilities": {
                    "analyst": 0.66,
                    "skeptic": 0.55,
                    "market_reader": 0.58,
                    "heuristic": 0.63,
                    "synthesizer": 0.62
                },
                "confidence": 0.68,
                "reasoning": "Synthesis weighted towards analyst and predictor, moderated by skeptic's valid market efficiency concern."
            })
        else:
            return json.dumps({
                "composite_score": 0.63,
                "edge": 0.10,
                "decision": "WATCH",
                "confidence": 0.63,
                "risk_level": 0.45
            })


# ─────────────────────────────────────────────────────────────────────────────
# camel-ai ChatAgent wrapper (sync → async bridge)
# ─────────────────────────────────────────────────────────────────────────────

class _CamelLLMClient:
    """
    Wraps camel-ai's ChatAgent to provide an async `.complete()` interface.
    Enables native OASIS/camel-ai message passing under the hood.
    """

    def __init__(self, system_prompt: str, temperature: float = None):
        self._system_prompt = system_prompt
        self._temperature   = temperature or settings.AGENT_TEMPERATURE
        self._agent         = None
        self._init_agent()

    def _init_agent(self):
        if not CAMEL_AVAILABLE:
            return
        try:
            # Build camel model config
            model_kwargs = {"temperature": self._temperature}
            model = self._build_model(model_kwargs)

            sys_msg = BaseMessage.make_assistant_message(
                role_name="Decision Agent",
                content=self._system_prompt,
            )
            self._agent = CamelChatAgent(system_message=sys_msg, model=model,
                                         message_window_size=4)
        except Exception as e:
            logger.warning("camel_agent_init_failed", error=str(e))
            self._agent = None

    @staticmethod
    def _build_model(model_kwargs: dict):
        """Try to build a camel model; fall back gracefully."""
        try:
            from camel.models import ModelFactory
            from camel.types import ModelPlatformType, ModelType
            platform_map = {
                "anthropic": ModelPlatformType.ANTHROPIC,
                "openai":    ModelPlatformType.OPENAI,
            }
            platform = platform_map.get(settings.LLM_PROVIDER, ModelPlatformType.ANTHROPIC)
            model_id = settings.LLM_MODEL
            return ModelFactory.create(
                model_platform=platform,
                model_type=model_id,
                model_config_dict=model_kwargs,
            )
        except Exception:
            # Older camel-ai versions have different API
            try:
                from camel.models import OpenAIModel
                from camel.types import ModelType
                return OpenAIModel(model_type=ModelType.GPT_4O,
                                   model_config_dict=model_kwargs)
            except Exception:
                return None

    async def complete(self, system_prompt: str, user_message: str,
                       temperature: float = None, max_tokens: int = 4096) -> str:
        if settings.DEMO_MODE:
            fb = _FallbackLLMClient()
            return fb._demo_response(system_prompt, user_message)

        if self._agent is None:
            # camel agent failed to init — use fallback
            fb = _FallbackLLMClient()
            return await fb.complete(system_prompt, user_message, temperature, max_tokens)

        try:
            # camel-ai is synchronous — run in executor to stay async
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._call_camel, user_message
            )
            return result
        except Exception as e:
            logger.error("camel_step_failed", error=str(e))
            fb = _FallbackLLMClient()
            return await fb.complete(system_prompt, user_message, temperature, max_tokens)

    def _call_camel(self, user_message: str) -> str:
        user_msg = BaseMessage.make_user_message(
            role_name="User", content=user_message
        )
        response = self._agent.step(user_msg)
        return response.msg.content


# ─────────────────────────────────────────────────────────────────────────────
# Client factory — returns the best available client for a given agent
# ─────────────────────────────────────────────────────────────────────────────

def make_llm_client(system_prompt: str, temperature: float = None):
    """Return best available LLM client.

    camel-ai is skipped for OpenRouter because it has no native OpenRouter
    support — the fallback client handles it via the OpenAI SDK with a
    custom base_url, which OpenRouter fully supports.
    """
    if CAMEL_AVAILABLE and not settings.DEMO_MODE and settings.LLM_PROVIDER != "openrouter":
        return _CamelLLMClient(system_prompt, temperature)
    return _FallbackLLMClient()


# ─────────────────────────────────────────────────────────────────────────────
# OASIS Base Agent
# ─────────────────────────────────────────────────────────────────────────────

class OASISBaseAgent(ABC):
    """
    OASIS-compatible decision agent.

    When camel-ai is installed, uses CamelChatAgent as the LLM backend.
    When not available, uses direct Anthropic/OpenAI client.

    OASIS interface:
      observe(environment) → user message string
      act(observation)     → parsed output dict
      step(context)        → AgentOutput (observe + act + metadata)
    """

    ROLE: AgentRole = NotImplemented
    AGENT_NAME: str = NotImplemented
    SYSTEM_PROMPT: str = NotImplemented
    TEMPERATURE: float = None

    def __init__(self):
        temp = self.TEMPERATURE if self.TEMPERATURE is not None else settings.AGENT_TEMPERATURE
        self.llm = make_llm_client(self.SYSTEM_PROMPT, temp)
        self._logger = structlog.get_logger(self.AGENT_NAME)

    # ── OASIS Interface ─────────────────────────────────────────────────────

    def observe(self, environment: Dict[str, Any]) -> str:
        """Extract and format relevant context from the shared environment."""
        return self._build_user_message(environment)

    async def act(self, observation: str) -> Dict[str, Any]:
        """Reason about the observation and produce structured output."""
        raw = await self.llm.complete(
            system_prompt=self.SYSTEM_PROMPT,
            user_message=observation,
            temperature=self.TEMPERATURE,
        )
        return self._safe_parse(raw)

    async def step(self, context: Dict[str, Any]) -> AgentOutput:
        """Full OASIS step: observe → act → return AgentOutput."""
        t0 = int(time.time() * 1000)
        try:
            self._logger.info("step_start")
            observation = self.observe(context)
            output      = await self.act(observation)
            confidence  = self._extract_confidence(output)
            elapsed     = int(time.time() * 1000) - t0
            self._logger.info("step_done", elapsed_ms=elapsed, conf=confidence)
            return AgentOutput(
                role=self.ROLE, agent_name=self.AGENT_NAME, status="completed",
                output=output,
                reasoning=str(output.get("reasoning", output.get("summary", "")))[:500],
                confidence=confidence, processing_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int(time.time() * 1000) - t0
            self._logger.error("step_error", error=str(exc))
            return AgentOutput(
                role=self.ROLE, agent_name=self.AGENT_NAME, status="error",
                output={}, reasoning="", confidence=0.0,
                processing_time_ms=elapsed, error=str(exc),
            )

    # ── Subclass contract ───────────────────────────────────────────────────

    @abstractmethod
    def _build_user_message(self, context: Dict[str, Any]) -> str: ...

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _safe_parse(self, raw: str) -> Dict[str, Any]:
        """Parse JSON from LLM response using multi-strategy extraction.

        Strategy 1 — Direct parse (ideal case: clean JSON string).
        Strategy 2 — Bracket counting (robust for nested JSON with surrounding text).
        Strategy 3 — Non-greedy regex (last resort).
        """
        # Strip markdown code fences and surrounding whitespace
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

        # Strategy 1: parse the whole cleaned string directly
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Strategy 2: bracket-count to locate the outermost { … } block
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(cleaned[start:], start=start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except json.JSONDecodeError:
                            break  # malformed even after correct boundary; fall through

        # Strategy 3: non-greedy regex fallback
        m = re.search(r"\{.*?\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass

        # Final fallback: return raw text so downstream agents don't KeyError
        return {"raw_output": raw, "reasoning": raw}

    def _extract_confidence(self, output: Dict[str, Any]) -> float:
        for key in ("confidence", "adjusted_confidence", "validation_score",
                    "data_quality_score", "scan_confidence", "argument_strength"):
            v = output.get(key)
            if isinstance(v, (int, float)):
                return float(max(0.0, min(1.0, v)))
        return 0.5

    @staticmethod
    def _fmt(title: str, data: Any) -> str:
        if isinstance(data, (dict, list)):
            return f"\n## {title}\n{json.dumps(data, indent=2)}\n"
        return f"\n## {title}\n{data}\n"
