"""
LLM-Mischprognose (nur live, nicht per Backtest prüfbar).

Mischt den Marktpreis mit der Prognose der bestehenden 10-Agenten-Pipeline:
    q = (1 − w) · Marktpreis + w · LLM,   w = 1/3 (AIA-Forecaster-Studie)
Jede Prognose landet im Prognose-Log, auch ohne Kauf, damit sie später per
Brier-Score gegen den Marktpreis bewertet werden kann.

Schutz gegen erfundene Zahlen: Die Pipeline fällt bei Fehlern still auf
Demo-Antworten zurück (backend/agents/base_agent.py, p = 0,62). Solche Läufe
werden hier erkannt und verworfen. Standardmäßig ist die Strategie AUS
(BotConfig.llm_enabled), weil jeder Lauf ~11 LLM-Aufrufe kostet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from paperbot.models import Signal
from paperbot.strategies.base import make_signal
from paperbot.view import MarketView

# Erkennungsmerkmale der Demo-Antworten in backend/agents/base_agent.py
DEMO_PROBABILITY = 0.62

Runner = Callable[[str, float], Optional[float]]


def backend_runner(question: str, market_prob: float) -> Optional[float]:
    """Ruft die bestehende Pipeline auf. None bei Fehler, Demo-Daten oder fehlenden Werten."""
    import asyncio

    from backend.api.models import BetType
    from backend.config import settings
    from backend.core.orchestrator import get_orchestrator

    if settings.DEMO_MODE:
        return None
    key = {"openrouter": settings.OPENROUTER_API_KEY, "openai": settings.OPENAI_API_KEY,
           "anthropic": settings.ANTHROPIC_API_KEY}.get(settings.LLM_PROVIDER, "")
    if not key:
        return None    # ohne Schlüssel liefert die Pipeline nur Demo-Daten
    orch = get_orchestrator()
    sid = orch.create_session(question, BetType.YES_NO)
    session = asyncio.run(orch.run_analysis(sid, question, BetType.YES_NO,
                                            implied_probability=market_prob))
    if session is None or session.final_decision is None:
        return None
    outputs = session.agent_outputs or []
    if any(getattr(o, "status", "completed") != "completed" for o in outputs):
        return None
    for o in outputs:   # Demo-Fallback antwortet für Predictor und Synthesizer mit 0,62
        out = getattr(o, "output", {}) or {}
        for k in ("predicted_probability", "final_probability"):
            v = out.get(k)
            if isinstance(v, (int, float)) and abs(float(v) - DEMO_PROBABILITY) < 1e-9:
                return None
    prob = session.final_decision.predicted_probability
    if prob is None or not 0.0 < float(prob) < 1.0:
        return None
    return float(prob)


@dataclass
class LLMBlendStrategy:
    runner: Runner = backend_runner
    weight: float = 1 / 3
    min_edge: float = 0.03
    cost: float = 0.01
    max_calls: int = 2
    name: str = "llm_blend"
    needs_history: bool = False
    live_only: bool = True
    calls: int = 0
    forecast_log: List[dict] = field(default_factory=list)

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        if self.calls >= self.max_calls:
            return None
        p = view.price()
        if p is None:
            return None
        self.calls += 1
        try:
            llm_p = self.runner(view.info.question, p)
        except Exception as exc:     # Pipeline-Fehler dürfen den Zyklus nicht stoppen
            self.forecast_log.append({"market_id": view.info.market_id, "ts": view.now_ts,
                                      "market_p": p, "error": repr(exc)[:200]})
            return None
        if llm_p is None:
            self.forecast_log.append({"market_id": view.info.market_id, "ts": view.now_ts,
                                      "market_p": p, "llm_p": None, "note": "verworfen"})
            return None
        q = (1.0 - self.weight) * p + self.weight * llm_p
        self.forecast_log.append({"market_id": view.info.market_id, "ts": view.now_ts,
                                  "question": view.info.question, "market_p": p,
                                  "llm_p": llm_p, "blend_p": q})
        for side, prob, price in (("YES", q, p), ("NO", 1.0 - q, 1.0 - p)):
            if prob - (price + self.cost) >= self.min_edge:
                return make_signal(self.name, view, side, prob,
                                   f"LLM {llm_p:.2f}, Mix {q:.2f} vs. Markt {p:.2f}")
        return None
