"""
Papier-Kontobuch, eines pro Strategie ("Strategie-Turnier": jede Strategie
bekommt eigenes Spielgeld, damit man sie fair vergleichen kann).

Invarianten (getestet in tests/test_ledger.py):
- Bargeld wird nie negativ.
- Pro Strategie und Markt höchstens ein Einstieg, gehalten bis zur Auflösung.
- Auflösen ist idempotent; annullierte Märkte erstatten den Einsatz.
- Speichern ist atomar (temporäre Datei + os.replace), Ereignisse werden
  nur angehängt (events.jsonl), nie überschrieben.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from paperbot.config import BotConfig
from paperbot.models import Fill, Position, Signal, side_price, side_won
from paperbot.risk import DAY, kill_switch


class LedgerError(ValueError):
    pass


class Ledger:
    def __init__(self, strategy: str, bankroll: float):
        self.strategy = strategy
        self.start_bankroll = float(bankroll)
        self.cash = float(bankroll)
        self.positions: List[Position] = []
        self.equity_history: List[Tuple[int, float]] = []
        self.marks: Dict[str, float] = {}          # market_id → letzter YES-Preis
        self.paused_until: Optional[int] = None
        self.kill_reset_ts: Optional[int] = None
        self.events: List[dict] = []               # noch nicht gespeicherte Ereignisse

    # ── Abfragen ──────────────────────────────────────────────────────────

    def open_positions(self) -> List[Position]:
        return [p for p in self.positions if p.is_open]

    def closed_positions(self) -> List[Position]:
        return [p for p in self.positions if not p.is_open]

    def has_position(self, market_id: str) -> bool:
        return any(p.market_id == market_id for p in self.positions)

    def invested(self) -> float:
        return sum(p.cost for p in self.open_positions())

    def equity(self, mark_to_market: bool = True) -> float:
        value = self.cash
        for p in self.open_positions():
            yes = self.marks.get(p.market_id) if mark_to_market else None
            value += p.shares * side_price(yes, p.side) if yes is not None else p.cost
        return value

    def is_paused(self, now_ts: int) -> bool:
        return self.paused_until is not None and now_ts < self.paused_until

    # ── Änderungen ────────────────────────────────────────────────────────

    def open(self, signal: Signal, fill: Fill, *, question: str = "", category: str = "") -> Position:
        if signal.strategy != self.strategy:
            raise LedgerError(f"Signal von {signal.strategy} im Konto von {self.strategy}")
        if self.has_position(fill.market_id):
            raise LedgerError(f"{self.strategy}: Markt {fill.market_id} schon gehandelt")
        if fill.shares <= 0 or fill.avg_price <= 0:
            raise LedgerError("leerer Fill")
        if fill.cost > self.cash + 1e-9:
            raise LedgerError(f"Kosten {fill.cost:.2f} > Bargeld {self.cash:.2f}")
        pos = Position(
            strategy=self.strategy, market_id=fill.market_id, question=question,
            category=category, side=fill.side, shares=fill.shares,
            avg_price=fill.avg_price, fee=fill.fee, opened_ts=fill.ts,
            signal_price=signal.price, signal_prob=signal.prob, reason=signal.reason,
            extra={"synthetic_book": fill.synthetic_book},
        )
        self.cash -= pos.cost
        self.positions.append(pos)
        self._event("open", fill.ts, market_id=pos.market_id, side=pos.side,
                    shares=pos.shares, avg_price=pos.avg_price, fee=pos.fee,
                    signal_price=pos.signal_price, signal_prob=pos.signal_prob,
                    reason=pos.reason)
        return pos

    def settle(self, market_id: str, outcome: Optional[int], ts: int,
               yes_payout: Optional[float] = None) -> Optional[Position]:
        """Löst die offene Position auf.

        outcome 1/0: Gewinner-Anteile zahlen 1. outcome None mit yes_payout:
        Teil-Auflösung (z. B. 50/50), jeder YES-Anteil zahlt yes_payout, jeder
        NO-Anteil 1 − yes_payout. outcome None ohne yes_payout: annulliert,
        Einsatz zurück.
        """
        for p in self.open_positions():
            if p.market_id != market_id:
                continue
            if outcome is not None:
                payout = p.shares if side_won(outcome, p.side) else 0.0
            elif yes_payout is not None:
                payout = p.shares * side_price(min(1.0, max(0.0, yes_payout)), p.side)
            else:
                payout = p.cost
            p.closed_ts, p.outcome, p.payout = ts, outcome, payout
            self.cash += payout
            self.marks.pop(market_id, None)
            self._event("settle", ts, market_id=market_id, outcome=outcome,
                        payout=payout, pnl=p.pnl)
            return p
        return None

    def mark(self, market_id: str, yes_price: Optional[float]) -> None:
        if yes_price is not None and 0.0 <= yes_price <= 1.0:
            self.marks[market_id] = yes_price

    def snapshot(self, ts: int) -> float:
        eq = self.equity()
        if self.equity_history and self.equity_history[-1][0] == ts:
            self.equity_history[-1] = (ts, eq)     # Doppellauf ersetzt statt verdoppelt
        else:
            self.equity_history.append((ts, eq))
        return eq

    def update_kill_switch(self, now_ts: int, cfg: BotConfig) -> bool:
        if self.paused_until is not None and now_ts >= self.paused_until:
            self.paused_until = None
            self.kill_reset_ts = now_ts            # Hoch nach der Pause neu messen
            self._event("resume", now_ts)
        if self.paused_until is None and kill_switch(self.equity_history, now_ts, cfg, self.kill_reset_ts):
            self.paused_until = now_ts + cfg.pause_days * DAY
            self._event("pause", now_ts, until=self.paused_until)
        return self.is_paused(now_ts)

    def _event(self, kind: str, ts: int, **data) -> None:
        self.events.append({"ts": ts, "strategy": self.strategy, "event": kind, **data})

    # ── Speichern ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "start_bankroll": self.start_bankroll,
            "cash": self.cash,
            "positions": [asdict(p) for p in self.positions],
            "equity_history": self.equity_history,
            "marks": self.marks,
            "paused_until": self.paused_until,
            "kill_reset_ts": self.kill_reset_ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        led = cls(d["strategy"], d["start_bankroll"])
        led.cash = float(d["cash"])
        led.positions = [Position(**p) for p in d.get("positions", [])]
        led.equity_history = [(int(t), float(e)) for t, e in d.get("equity_history", [])]
        led.marks = {k: float(v) for k, v in d.get("marks", {}).items()}
        led.paused_until = d.get("paused_until")
        led.kill_reset_ts = d.get("kill_reset_ts")
        return led


class LedgerStore:
    """Alle Kontobücher in state_dir/ledgers.json, Ereignisse in events.jsonl."""

    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.path = self.dir / "ledgers.json"
        self.events_path = self.dir / "events.jsonl"

    def load(self, strategies: Iterable[str], bankroll: float) -> Dict[str, Ledger]:
        data = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        ledgers = {name: Ledger.from_dict(d) for name, d in data.get("ledgers", {}).items()}
        for name in strategies:
            ledgers.setdefault(name, Ledger(name, bankroll))
        return ledgers

    def save(self, ledgers: Dict[str, Ledger], meta: Optional[dict] = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"meta": meta or {}, "ledgers": {k: v.to_dict() for k, v in ledgers.items()}}
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=1))
        events = [e for led in ledgers.values() for e in led.events]
        if events:
            with self.events_path.open("a", encoding="utf-8") as f:
                for e in sorted(events, key=lambda e: e["ts"]):
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            for led in ledgers.values():
                led.events.clear()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
