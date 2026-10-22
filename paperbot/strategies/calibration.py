"""
H4: Kalibrierungs-Korrektur.

Eine isotonische Kurve lernt aus aufgelösten Märkten, wie oft ein Preis p
tatsächlich gewinnt. Weil die Kurve an den Rändern mit wenigen Daten
überanpasst, wird sie zur Diagonalen hin geschrumpft: w = n / (n + shrink).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

from paperbot.models import Signal
from paperbot.strategies.base import make_signal
from paperbot.view import MarketView


@dataclass
class IsotonicCalibrator:
    x: List[float] = field(default_factory=list)
    y: List[float] = field(default_factory=list)
    n: int = 0
    shrink: float = 500.0

    @classmethod
    def fit(cls, prices: Sequence[float], outcomes: Sequence[int], shrink: float = 500.0) -> "IsotonicCalibrator":
        from sklearn.isotonic import IsotonicRegression

        p = np.asarray(prices, dtype=float)
        y = np.asarray(outcomes, dtype=float)
        if p.size < 50:
            raise ValueError(f"zu wenige Punkte zum Kalibrieren: {p.size}")
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        iso.fit(p, y)
        return cls(x=[float(v) for v in iso.X_thresholds_], y=[float(v) for v in iso.y_thresholds_],
                   n=int(p.size), shrink=shrink)

    def predict(self, p: float) -> float:
        if not self.x:
            return p
        q = float(np.interp(p, self.x, self.y))
        w = self.n / (self.n + self.shrink)
        return w * q + (1.0 - w) * p

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "n": self.n, "shrink": self.shrink}

    @classmethod
    def from_dict(cls, d: dict) -> "IsotonicCalibrator":
        return cls(x=list(d["x"]), y=list(d["y"]), n=int(d["n"]), shrink=float(d.get("shrink", 500.0)))

    def save(self, path: Path, **meta) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**self.to_dict(), "meta": meta}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["IsotonicCalibrator"]:
        if not path.exists():
            return None
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class CalibrationStrategy:
    calibrator: Optional[IsotonicCalibrator] = None
    min_edge: float = 0.02
    cost: float = 0.01          # geschätzte Kosten pro Anteil (halber Spread + Gebühr)
    max_price: float = 0.97
    name: str = "calibration"
    needs_history: bool = False
    live_only: bool = False

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        if self.calibrator is None:       # nicht gelernt → kein Handel
            return None
        p = view.price()
        if p is None:
            return None
        q = self.calibrator.predict(p)
        best = None
        for side, prob, price in (("YES", q, p), ("NO", 1.0 - q, 1.0 - p)):
            buy = price + self.cost
            edge = prob - buy
            if buy <= self.max_price and edge >= self.min_edge and (best is None or edge > best[2]):
                best = (side, prob, edge)
        if best is None:
            return None
        side, prob, edge = best
        price = p if side == "YES" else 1.0 - p
        return make_signal(self.name, view, side, prob,
                           f"kalibriert {prob:.3f} vs. Preis {price:.3f} (Edge {edge:+.3f})")
