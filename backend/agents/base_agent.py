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
    """Direct Anthropic/OpenAI client — used when camel-ai is not installed."""

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
                pass

    async def complete(self, system_prompt: str, user_message: str,
                       temperature: float = None, max_tokens: int = 4096) -> str:
        temp = temperature if temperature is not None else settings.AGENT_TEMPERATURE
        if settings.DEMO_MODE:
            return _demo_response(system_prompt)
        if self._anthropic:
            return await self._do_anthropic(system_prompt, user_message, temp, max_tokens)
        if self._openai:
            return await self._do_openai(system_prompt, user_message, temp, max_tokens)
        logger.warning("no_llm_client_available", fallback="demo_mode")
        return _demo_response(system_prompt)

    async def _do_anthropic(self, sys, usr, temp, max_tokens):
        import anthropic as _ant
        client = self._anthropic
        resp = await client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temp,
            system=sys,
            messages=[{"role": "user", "content": usr}],
        )
        return resp.content[0].text

    async def _do_openai(self, sys, usr, temp, max_tokens):
        resp = await self._openai.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temp,
            messages=[{"role": "system", "content": sys},
                      {"role": "user",   "content": usr}],
        )
        return resp.choices[0].message.content


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
            return _demo_response(system_prompt)

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
    """Return a camel-ai client if available, else fallback."""
    if CAMEL_AVAILABLE and not settings.DEMO_MODE:
        return _CamelLLMClient(system_prompt, temperature)
    return _FallbackLLMClient()


# ─────────────────────────────────────────────────────────────────────────────
# Demo response generator
# ─────────────────────────────────────────────────────────────────────────────

def _demo_response(system_prompt: str) -> str:
    """Deterministic demo responses so the UI works without any API key."""
    sp = system_prompt.lower()
    if "scanner" in sp:
        return json.dumps({"event_type": "sports", "sport": "football",
            "teams": ["Team A", "Team B"], "outcome_description": "Team A wins",
            "timeframe": "upcoming match", "market_type": "match_result",
            "implied_probability": 0.55, "scan_confidence": 0.75,
            "reasoning": "Demo: identified football match between two teams."})
    if "parser" in sp or "input_parser" in sp:
        return json.dumps({"canonical_query": "Will Team A beat Team B?",
            "event_type": "sports", "sport": "football", "primary_entity": "Team A",
            "secondary_entity": "Team B", "prediction_target": "Team A wins",
            "timeframe_description": "next scheduled match", "market_type": "match_result",
            "implied_probability": 0.55, "data_requirements": ["recent form", "H2H record"],
            "parsing_issues": [], "confidence": 0.80,
            "reasoning": "Demo: parsed match winner market."})
    if "research" in sp:
        return json.dumps({"key_facts": ["Team A: 4W-1D in last 5", "Strong home record",
            "Opponent missing key striker"], "recent_news": ["Team A in excellent form",
            "No injury concerns reported"], "statistics": {"recent_form": "4W-1D",
            "head_to_head": "Team A leads 6-2-2", "home_away_splits": "W75% at home"},
            "market_signals": {"odds_movement": "Slight drift toward Team A",
            "sharp_money_indicators": "Line movement suggests professional backing"},
            "data_quality_score": 0.70, "missing_information": ["Lineup confirmation"],
            "summary": "Team A holds a meaningful form and H2H advantage.",
            "confidence": 0.70, "reasoning": "Demo: good quality data available."})
    if "predict" in sp:
        return json.dumps({"predicted_probability": 0.62,
            "uncertainty_range": {"low": 0.54, "high": 0.70},
            "implied_market_probability": 0.55, "estimated_edge": 0.07,
            "key_factors": ["Recent form", "H2H dominance", "Home advantage"],
            "upside_factors": ["Opponent missing players"],
            "downside_factors": ["High-pressure fixture"],
            "base_rate": "Home favorites win ~58% of matches in this league.",
            "reasoning": "Demo: 62% estimated based on form and H2H.",
            "confidence": 0.65})
    if "analyst" in sp or "bull" in sp:
        return json.dumps({"bull_case": "Team A's 4-match winning run, combined with their exceptional home record and an injury-hampered opponent, makes this a strong value opportunity. The H2H record of 6 wins in 10 suggests systematic dominance.",
            "bull_factors": [{"factor": "Current form", "strength": "high", "evidence": "4W-1D last 5"},
                {"factor": "H2H dominance", "strength": "high", "evidence": "6-2-2 record"},
                {"factor": "Opponent weaknesses", "strength": "medium", "evidence": "Missing striker"}],
            "argument_strength": 0.72, "supporting_evidence": ["4W-1D run", "6-2-2 H2H"],
            "why_skeptics_are_wrong": "The form advantage is recent and consistent, not a small sample.",
            "hidden_edges": ["Market may be slow to price in injury news"],
            "key_risk_to_bull_case": "Tactical surprise from underdog manager",
            "confidence": 0.72, "reasoning": "Demo: solid bull case."})
    if "skeptic" in sp or "bear" in sp:
        return json.dumps({"bear_case": "At odds implying 55% probability, the market may already be fair. Favorites in this league underperform against motivated underdogs. The 7% edge is smaller than the vig in most books.",
            "bear_factors": [{"factor": "Market efficiency", "severity": "medium", "evidence": "Line movement modest"},
                {"factor": "Underdog motivation", "severity": "medium", "evidence": "Relegation battle"},
                {"factor": "Short odds value", "severity": "high", "evidence": "7% edge pre-vig"}],
            "counter_argument_strength": 0.55,
            "flaws_in_analysis": ["Small sample size (5 games)", "Recency bias possible"],
            "risks": ["Tactical adjustment", "Set-piece vulnerability"],
            "market_efficiency_concern": "7% edge is thin after accounting for variance.",
            "cognitive_biases_detected": ["Recency bias", "Home team bias"],
            "upset_probability": 0.38,
            "key_question_unanswered": "Is the squad depth sufficient for rotation?",
            "confidence": 0.55, "reasoning": "Demo: fair counter-arguments found."})
    if "scenario" in sp:
        return json.dumps({"scenarios": [
            {"name": "Comfortable Win", "description": "Team A controls from kick-off", "probability": 0.32, "outcome": "WIN", "impact": "Strong return", "trigger_conditions": ["Early goal", "Opponent low energy"]},
            {"name": "Narrow Win", "description": "Tight game, edges it late", "probability": 0.30, "outcome": "WIN", "impact": "As expected", "trigger_conditions": ["Set piece goal"]},
            {"name": "Draw", "description": "Both teams cancel out", "probability": 0.22, "outcome": "DRAW", "impact": "Loss on win bet", "trigger_conditions": ["Defensive discipline from underdog"]},
            {"name": "Upset Loss", "description": "Underdog takes all three points", "probability": 0.16, "outcome": "LOSS", "impact": "Full stake lost", "trigger_conditions": ["Counter-attack goals", "Goalkeeper heroics"]}],
            "probability_check": "0.32+0.30+0.22+0.16=1.00 ✓",
            "most_likely_scenario": "Narrow Win", "tail_risk": "Upset loss at 16%",
            "variance_assessment": "Medium variance — no dominant scenario above 35%.",
            "scenario_count": 4, "confidence": 0.68, "reasoning": "Demo: reasonable distribution."})
    if "valid" in sp:
        return json.dumps({"is_consistent": True,
            "consistency_issues": [],
            "logical_issues": ["Small sample size (5 games) limits confidence"],
            "data_quality_flags": ["Lineup not yet confirmed"],
            "cognitive_biases_detected": [{"bias": "Recency bias", "description": "Overweighting last 5 matches", "severity": "medium"},
                {"bias": "Home team bias", "description": "Home advantage may be overstated", "severity": "low"}],
            "unfounded_assumptions": ["Opponent will maintain current tactics"],
            "missing_critical_information": ["Official starting lineups", "Weather conditions"],
            "inter_agent_conflicts": ["Analyst and Skeptic disagree on market efficiency"],
            "adjusted_confidence": 0.60, "validation_score": 0.72,
            "reliability_assessment": "Moderate reliability — data is reasonable but thin.",
            "confidence": 0.72, "reasoning": "Demo: validation found minor issues."})
    if "synth" in sp:
        return json.dumps({"summary": "The analysis shows a modest but genuine edge for Team A. The Analyst's strong bull case is partially offset by the Skeptic's valid concerns about market efficiency and the 16% upset probability.",
            "key_insights": ["Form advantage is real but small sample", "Market may be fair-priced", "16% upset risk is non-trivial", "Missing lineup confirmation adds uncertainty"],
            "agent_agreement_level": 0.65,
            "conflicts": [{"agents": ["AnalystAgent", "SkepticAgent"], "conflict": "Disagreement on whether 7% edge survives vig", "resolution": "Reduced final probability slightly"}],
            "final_probability": 0.60, "probability_adjustment": "Reduced from 0.62 to 0.60 after skeptic's market efficiency argument.",
            "confidence_adjustment": "Validation reduced confidence by 5% for missing lineup info.",
            "narrative": "Team A is the rightful favorite based on form and H2H data. However, the Skeptic correctly notes that the edge is thin. This is a WATCH candidate unless odds improve or lineup confirms key players.",
            "action_relevance": "Edge is real but marginal — monitor for better entry.",
            "key_uncertainties": ["Starting lineup", "Tactical setup"],
            "agent_weight_rationale": "Gave higher weight to Validator and Skeptic due to data quality flags.",
            "confidence": 0.65, "reasoning": "Demo: balanced synthesis."})
    # scoring default
    return json.dumps({"scores": {"predicted_probability": 0.60, "confidence_score": 0.62,
        "data_quality": 0.70, "argument_strength": 0.72, "counter_argument_impact": 0.45,
        "validation_score": 0.72, "market_signal": 0.0},
        "composite_score": 0.63, "edge": 0.05, "risk_level": 0.42,
        "risk_category": "medium", "decision": "WATCH",
        "decision_explanation": "Edge is present but below the BET threshold. Monitor.",
        "risk_warnings": ["7% edge is thin after vig", "16% upset probability"],
        "max_exposure_guidance": "0.5-1% of bankroll if betting",
        "confidence": 0.63, "reasoning": "Demo: WATCH recommendation."})


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
        """Robust JSON extraction — handles markdown fences and partial JSON."""
        if not raw:
            return {"raw_output": "", "reasoning": "Empty response"}

        # Strip markdown fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        cleaned = cleaned.rstrip("`").strip()

        # Try full string
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find first JSON object
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass

        # Last resort: wrap as raw
        return {"raw_output": raw[:1000], "reasoning": raw[:500]}

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
