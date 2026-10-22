"""
Positionsgröße und Notbremse.

- Ohne kalibrierte Wahrscheinlichkeit: fester Anteil der Bankroll.
- Mit kalibrierter Wahrscheinlichkeit: Viertel-Kelly. Liegt der Kelly-Einsatz
  unter der Mindestgröße, wird NICHT aufgerundet, sondern ausgelassen.
- Harte Deckel: pro Markt, gesamt, je Kategorie, Anzahl offener Positionen.
- Notbremse misst den Rückgang gegen das Hoch der letzten N Tage (rollierend)
  und setzt sich nach der Pause neu auf. So kann sich der Bot nicht selbst
  dauerhaft aussperren (Lehre aus NEMI).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from paperbot.config import BotConfig
from paperbot.models import Position, Signal

DAY = 86_400


@dataclass(frozen=True)
class SizingDecision:
    stake: float
    reason: str = ""


def kelly_fraction_binary(prob: float, cost_per_share: float) -> float:
    """Kelly-Anteil für einen Anteil, der `cost_per_share` kostet und 1 auszahlt.

    Quote b = (1 − c) / c, f* = (b·p − (1 − p)) / b = (p − c) / (1 − c).
    """
    c = cost_per_share
    if not 0.0 < c < 1.0 or not 0.0 <= prob <= 1.0:
        return 0.0
    return (prob - c) / (1.0 - c)


def size_position(signal: Signal, cost_per_share: float, *, equity: float, cash: float,
                  open_positions: Sequence[Position], category: str, cfg: BotConfig,
                  paused: bool = False) -> SizingDecision:
    if paused:
        return SizingDecision(0.0, "Notbremse aktiv")
    if len(open_positions) >= cfg.max_open_positions:
        return SizingDecision(0.0, "maximale Anzahl offener Positionen")
    if equity <= 0:
        return SizingDecision(0.0, "kein Kapital")

    cap = cfg.max_stake_frac * equity
    min_notional = cfg.min_order_shares * cost_per_share

    if signal.prob is not None:
        f = kelly_fraction_binary(signal.prob, cost_per_share)
        if f <= 0:
            return SizingDecision(0.0, "kein Vorteil nach Kosten")
        stake = min(cfg.kelly_fraction * f * equity, cap)
        if stake < min_notional:
            return SizingDecision(0.0, "Kelly-Einsatz unter Mindestgröße")
    else:
        stake = min(cfg.stake_frac * equity, cap)
        if stake < min_notional:
            if min_notional > cap:
                return SizingDecision(0.0, "Mindestgröße über Obergrenze pro Markt")
            stake = min_notional

    invested = sum(p.cost for p in open_positions)
    if invested + stake > cfg.max_exposure_frac * equity:
        return SizingDecision(0.0, "Gesamt-Einsatz-Grenze erreicht")
    cat = (category or "unbekannt").lower()
    in_cat = sum(p.cost for p in open_positions if (p.category or "unbekannt").lower() == cat)
    if in_cat + stake > cfg.max_category_frac * equity:
        return SizingDecision(0.0, f"Kategorie-Grenze erreicht ({cat})")
    if stake > cash + 1e-9:
        return SizingDecision(0.0, "zu wenig Bargeld")
    return SizingDecision(stake)


def kill_switch(equity_history: Iterable[Tuple[int, float]], now_ts: int, cfg: BotConfig,
                reset_ts: Optional[int] = None) -> bool:
    """True, wenn die Equity mehr als kill_drawdown_frac unter dem rollierenden Hoch liegt.

    Berücksichtigt nur Schnappschüsse seit max(now − Fenster, reset_ts).
    """
    since = now_ts - cfg.kill_window_days * DAY
    if reset_ts is not None:
        since = max(since, reset_ts)
    window: List[float] = [eq for ts, eq in equity_history if since <= ts <= now_ts]
    if len(window) < 2:
        return False
    peak = max(window)
    return peak > 0 and window[-1] < (1.0 - cfg.kill_drawdown_frac) * peak
