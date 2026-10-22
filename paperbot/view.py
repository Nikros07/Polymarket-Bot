"""
MarketView — was eine Strategie zum Zeitpunkt `now_ts` sehen darf.

Die Sperre gegen Zukunftsdaten ist hier eingebaut, nicht nur Konvention
(Lehre aus Quant-Lab und Fly-of-Wallstreet):
- Die Preishistorie wird beim Erzeugen physisch auf Punkte <= now_ts gekürzt.
- Ergebnis, Auflösungszeit und Endvolumen sind gar nicht erst enthalten.
- Das geplante Ende ist nur sichtbar, wenn es vorher feststand.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from paperbot.models import Market, PricePoint

DAY = 86_400


class LookaheadError(RuntimeError):
    """Eine Strategie hat nach Daten aus der Zukunft gefragt."""


@dataclass(frozen=True)
class MarketInfo:
    """Metadaten, die zur Entscheidungszeit bekannt sind."""
    source: str
    market_id: str
    question: str
    category: str
    created_ts: Optional[int]
    end_ts: Optional[int]          # None, wenn das Ende nicht vorher feststand

    @classmethod
    def from_market(cls, m: Market, live: bool = False) -> "MarketInfo":
        """live=True: das aktuell veröffentlichte Ende ist jetzt bekannt und darf genutzt werden."""
        return cls(
            source=m.source,
            market_id=m.market_id,
            question=m.question,
            category=m.category,
            created_ts=m.created_ts,
            end_ts=m.end_ts if (live or m.end_known_in_advance) else None,
        )


class MarketView:
    def __init__(self, info: MarketInfo, history: Sequence[PricePoint], now_ts: int):
        pts = sorted(history, key=lambda x: x.t)
        self._init(info, pts, [x.t for x in pts], now_ts)

    @classmethod
    def from_sorted(cls, info: MarketInfo, pts: Sequence[PricePoint], ts: Sequence[int],
                    now_ts: int) -> "MarketView":
        """Schneller Weg für den Backtest: `pts` aufsteigend, `ts` die passenden Zeiten."""
        view = cls.__new__(cls)
        view._init(info, pts, ts, now_ts)
        return view

    def _init(self, info: MarketInfo, pts: Sequence[PricePoint], ts: Sequence[int], now_ts: int) -> None:
        # Kein Kopieren: Die Sicht merkt sich nur die Schnittstelle `_cut`. Alle Zugriffe
        # unten lesen ausschließlich Punkte mit Index < _cut, also Zeit <= now_ts.
        self.info = info
        self.now_ts = int(now_ts)
        self._pts = pts
        self._ts = ts
        self._cut = bisect.bisect_right(ts, self.now_ts)

    # ── Preise ────────────────────────────────────────────────────────────

    def price(self) -> Optional[float]:
        """Letzter bekannter YES-Preis zur Entscheidungszeit."""
        return self._pts[self._cut - 1].p if self._cut else None

    def price_at(self, ts: int) -> Optional[float]:
        """YES-Preis zum Zeitpunkt ts (letzter Punkt <= ts)."""
        if ts > self.now_ts:
            raise LookaheadError(f"price_at({ts}) liegt nach now_ts={self.now_ts}")
        i = bisect.bisect_right(self._ts, ts, 0, self._cut)
        return self._pts[i - 1].p if i > 0 else None

    def price_days_ago(self, days: float) -> Optional[float]:
        return self.price_at(self.now_ts - int(days * DAY))

    def history(self) -> Tuple[PricePoint, ...]:
        return tuple(self._pts[:self._cut])

    # ── Zeit ──────────────────────────────────────────────────────────────

    def age_days(self) -> Optional[float]:
        start = self.info.created_ts if self.info.created_ts is not None else (
            self._pts[0].t if self._cut else None)
        return None if start is None else (self.now_ts - start) / DAY

    def days_to_end(self) -> Optional[float]:
        """Tage bis zum geplanten Ende, None wenn es nicht vorher bekannt war."""
        if self.info.end_ts is None:
            return None
        return (self.info.end_ts - self.now_ts) / DAY
