"""
Freigabe-Prüfung: Wäre eine Strategie reif für mehr als Papiergeld?

Das Ergebnis ist nur eine Auskunft. Es gibt im Code keinen Echtgeld-Modus,
und auch ein "bestanden" schaltet nichts frei. Die Entscheidung, ob und wie
echtes Geld eingesetzt wird, liegt beim Menschen, ebenso die Klärung der
Rechtslage in Deutschland.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from paperbot.backtest import metrics
from paperbot.ledger import Ledger

MIN_RESOLVED = 100

DISCLAIMER = ("Auskunft, keine Freigabe: Echtgeld ist im Code nicht vorgesehen. "
              "Rechtslage in Deutschland (GGL) und Steuern vorher klären.")


@dataclass
class GateVerdict:
    strategy: str
    passed: bool
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)


def _live_returns(led: Ledger) -> np.ndarray:
    closed = [p for p in led.closed_positions() if p.outcome is not None and p.cost > 0]
    return np.array([p.pnl / p.cost for p in closed], dtype=float)


def evaluate_gate(led: Ledger, control: Optional[Ledger] = None,
                  backtest_verdict: Optional[str] = None) -> GateVerdict:
    checks: List[Tuple[str, bool, str]] = []
    rets = _live_returns(led)
    n = int(rets.size)
    checks.append(("mind. 100 aufgelöste Papier-Trades", n >= MIN_RESOLVED, f"{n} aufgelöst"))

    if n:
        st = metrics.roi_stats(rets, seed=0)
        checks.append(("Papier-Ertrag sicher positiv (95 %-Untergrenze > 0)",
                       bool(st["ci_lo"] > 0), f"Ø {st['mean']:+.2%}, Untergrenze {st['ci_lo']:+.2%}"))
        closed = [p for p in led.closed_positions() if p.outcome is not None]
        won = np.array([1 if p.payout and p.payout > 0 else 0 for p in closed])
        market = np.array([p.signal_price for p in closed])
        if any(p.signal_prob is not None for p in closed):
            own = np.array([p.signal_prob if p.signal_prob is not None else p.signal_price for p in closed])
            b_own, b_mkt = metrics.brier(own, won), metrics.brier(market, won)
            checks.append(("eigene Prognose besser als Marktpreis (Brier)", b_own < b_mkt,
                           f"{b_own:.4f} vs. Markt {b_mkt:.4f}"))
    else:
        checks.append(("Papier-Ertrag sicher positiv (95 %-Untergrenze > 0)", False, "keine Daten"))

    if control is not None:
        c = _live_returns(control)
        ok = bool(n and c.size and rets.mean() > c.mean())
        detail = f"{rets.mean():+.2%} vs. Kontrolle {c.mean():+.2%}" if n and c.size else "zu wenige Daten"
        checks.append(("schlägt Zufallskontrolle", ok, detail))

    checks.append(("Backtest Out-of-Sample bestätigt", backtest_verdict == "bestätigt",
                   backtest_verdict or "kein Backtest"))
    return GateVerdict(led.strategy, all(ok for _, ok, _ in checks), checks)


def backtest_verdicts(results_dir: Path, source: str) -> Dict[str, str]:
    """Ordnet Strategie-Familien (favorite, calibration, …) ihr Backtest-Urteil zu."""
    path = results_dir / f"backtest_{source}_summary.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    family = {"H1": "favorite", "H2": "momentum", "H3": "reversion", "H4": "calibration"}
    return {family[k]: v.get("verdict", "") for k, v in data.get("hypotheses", {}).items() if k in family}
