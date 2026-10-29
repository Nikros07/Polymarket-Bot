"""
Spezialisierung H8: Kalshi-Tageshöchsttemperatur mit Vorhersagemodell.

- Vorhersage: Open-Meteo Previous-Runs-API, `temperature_2m_previous_day2`
  (Modelllauf mindestens 48 h vor der jeweiligen Stunde). Das Tagesmaximum
  für Tag D ist damit spätestens um 00:00 Ortszeit an D−1 ausgegeben. Mit
  6 h Sicherheitsabstand für Rechenzeit gilt es ab D−1 06:00 Ortszeit als
  bekannt. `ForecastBook.get` wirft LookaheadError, wenn früher gefragt wird.
- Modell: Höchstwert ~ Normal(μ + b, σ); b, σ per Maximum-Likelihood nur aus
  Trainingsmärkten.
- Spannen: „between a, c“ = [a − 0,5; c + 0,5], „greater a“ = [a + 0,5; ∞),
  „less c“ = (−∞; c − 0,5] (ganze °F, siehe yes_sub_title bei Kalshi).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np

from paperbot.data.kalshi import event_date
from paperbot.models import Signal
from paperbot.strategies.base import make_signal
from paperbot.view import LookaheadError, MarketInfo, MarketView

PREV_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1"
ISSUE_LAG = timedelta(hours=6)       # Sicherheitsabstand nach 00:00 Ortszeit D−1


@dataclass(frozen=True)
class Station:
    lat: float
    lon: float
    tz: str


# Messstationen der Kalshi-Serien (NWS-Klimastationen)
STATIONS: Dict[str, Station] = {
    "KXHIGHNY": Station(40.7789, -73.9692, "America/New_York"),     # Central Park
    "KXHIGHCHI": Station(41.7868, -87.7522, "America/Chicago"),     # Midway
    "KXHIGHMIA": Station(25.7959, -80.2870, "America/New_York"),    # Miami Intl
    "KXHIGHLAX": Station(33.9382, -118.3866, "America/Los_Angeles"),  # LAX
    "KXHIGHAUS": Station(30.1945, -97.6699, "America/Chicago"),     # Austin-Bergstrom
    "KXHIGHDEN": Station(39.8466, -104.6562, "America/Denver"),     # Denver Intl
    "KXHIGHPHIL": Station(39.8733, -75.2268, "America/New_York"),   # Philadelphia Intl
}


def available_from(series: str, day: date) -> int:
    """Unix-Zeit, ab der die Vorhersage für `day` als ausgegeben gilt (D−1 06:00 Ortszeit)."""
    tz = ZoneInfo(STATIONS[series].tz)
    local = datetime.combine(day - timedelta(days=1), datetime.min.time(), tz) + ISSUE_LAG
    return int(local.timestamp())


@dataclass
class ForecastBook:
    """Tagesmaxima (°F) je (Serie, Datum). Abfrage nur nach Ausgabezeit."""
    highs: Dict[Tuple[str, str], float] = field(default_factory=dict)

    def get(self, series: str, day: date, now_ts: int) -> Optional[float]:
        if series not in STATIONS:
            return None
        if now_ts < available_from(series, day):
            raise LookaheadError(f"Vorhersage {series} {day} erst ab {available_from(series, day)}")
        return self.highs.get((series, day.isoformat()))

    def to_json(self) -> str:
        return json.dumps({f"{s}|{d}": v for (s, d), v in self.highs.items()})

    @classmethod
    def from_json(cls, text: str) -> "ForecastBook":
        raw = json.loads(text)
        return cls({tuple(k.split("|", 1)): float(v) for k, v in raw.items()})


def daily_max(times: Sequence[str], temps: Sequence[Optional[float]]) -> Dict[str, float]:
    """Stündliche Werte (lokale Zeit 'YYYY-MM-DDTHH:MM') -> Maximum je Tag, nur volle Tage."""
    by_day: Dict[str, List[Optional[float]]] = {}
    for t, v in zip(times, temps):
        by_day.setdefault(t[:10], []).append(v)
    return {d: max(vs) for d, vs in by_day.items()  # type: ignore[type-var]
            if len(vs) >= 23 and all(v is not None for v in vs)}


def fetch_forecasts(series: Sequence[str], start: date, end: date, http=None) -> ForecastBook:
    """Archiv-Vorhersagen in Jahres-Stücken holen (ein Abruf je Stadt und Jahr)."""
    if http is None:
        from paperbot.data.http import HttpClient
        http = HttpClient(PREV_RUNS_URL, min_interval_s=0.5, timeout_s=60.0)
    book = ForecastBook()
    for s in series:
        st = STATIONS[s]
        a = start
        while a <= end:
            b = min(end, date(a.year, 12, 31))
            resp = http.get_json("forecast", params={
                "latitude": st.lat, "longitude": st.lon,
                "hourly": "temperature_2m_previous_day2", "temperature_unit": "fahrenheit",
                "timezone": st.tz, "start_date": a.isoformat(), "end_date": b.isoformat()})
            hourly = (resp or {}).get("hourly") or {}
            for d, v in daily_max(hourly.get("time") or [], hourly.get("temperature_2m_previous_day2") or []).items():
                book.highs[(s, d)] = float(v)
            a = b + timedelta(days=1)
    return book


# ── Modell ─────────────────────────────────────────────────────────────────

def bracket(info: MarketInfo) -> Optional[Tuple[float, float]]:
    """Kontinuierliches Intervall [lo, hi] der YES-Seite in °F."""
    lo, hi = info.floor_strike, info.cap_strike
    if info.strike_type == "between" and lo is not None and hi is not None:
        return lo - 0.5, hi + 0.5
    if info.strike_type == "greater" and lo is not None:
        return lo + 0.5, math.inf
    if info.strike_type == "less" and hi is not None:
        return -math.inf, hi - 0.5
    return None


def _phi(x: np.ndarray) -> np.ndarray:
    from scipy.special import ndtr
    return ndtr(x)


@dataclass
class TempModel:
    bias: float = 0.0
    sigma: float = 3.0
    n: int = 0

    def prob_yes(self, mu: float, lo: float, hi: float) -> float:
        m = mu + self.bias
        p = float(_phi(np.array([(hi - m) / self.sigma]))[0] - _phi(np.array([(lo - m) / self.sigma]))[0])
        return min(1.0, max(0.0, p))

    @classmethod
    def fit(cls, rows: Sequence[Tuple[float, float, float, int]]) -> "TempModel":
        """rows: (μ, lo, hi, Ergebnis). Gitter-Suche nach maximaler Log-Likelihood."""
        if len(rows) < 50:
            raise ValueError(f"zu wenige Märkte zum Lernen: {len(rows)}")
        a = np.asarray(rows, dtype=float)
        mu, lo, hi, y = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
        best = (-math.inf, 0.0, 3.0)
        for b in np.arange(-5.0, 5.01, 0.25):
            for s in np.arange(1.0, 8.01, 0.1):
                p = _phi((hi - mu - b) / s) - _phi((lo - mu - b) / s)
                p = np.clip(p, 1e-6, 1 - 1e-6)
                ll = float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))
                if ll > best[0]:
                    best = (ll, float(b), float(s))
        return cls(bias=round(best[1], 2), sigma=round(best[2], 2), n=len(rows))

    def save(self, path: Path, **meta) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"bias": self.bias, "sigma": self.sigma, "n": self.n,
                                    "meta": meta}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["TempModel"]:
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(bias=float(d["bias"]), sigma=float(d["sigma"]), n=int(d.get("n", 0)))


def training_rows(dataset, forecasts: ForecastBook) -> List[Tuple[float, float, float, int]]:
    """(μ, lo, hi, Ergebnis) je Markt. μ wird zur Ausgabezeit gelesen, nicht später."""
    rows = []
    for m, _ in dataset:
        d = event_date(m.event_id)
        br = bracket(MarketInfo.from_market(m))
        if d is None or br is None or m.outcome not in (0, 1) or m.series not in STATIONS:
            continue
        mu = forecasts.get(m.series, d, available_from(m.series, d))
        if mu is not None:
            rows.append((mu, br[0], br[1], int(m.outcome)))
    return rows


@dataclass
class WeatherStrategy:
    """H8: Kauf der Seite, deren Modell-Wahrscheinlichkeit den Kaufpreis um min_edge übersteigt."""
    model: Optional[TempModel]
    forecasts: ForecastBook
    min_edge: float = 0.05
    cost: float = 0.01          # Aufschlag auf den Mittelkurs, wenn kein Briefkurs bekannt ist
    max_price: float = 0.97
    name: str = "weather"
    needs_history: bool = False
    live_only: bool = False

    def evaluate(self, view: MarketView) -> Optional[Signal]:
        info = view.info
        if self.model is None or info.series not in STATIONS:
            return None
        d = event_date(info.event_id)
        br = bracket(info)
        p = view.price()
        if d is None or br is None or p is None:
            return None
        if view.now_ts < available_from(info.series, d):
            return None                       # Vorhersage noch nicht ausgegeben
        mu = self.forecasts.get(info.series, d, view.now_ts)
        if mu is None:
            return None
        q = self.model.prob_yes(mu, *br)
        last = view.last_point()
        best = None
        for side, prob in (("YES", q), ("NO", 1.0 - q)):
            ask = last.side_ask(side) if last is not None else None
            buy = ask if ask is not None else (p if side == "YES" else 1.0 - p) + self.cost
            buy += 0.07 * buy * (1.0 - buy)    # Kalshi-Taker-Gebühr
            edge = prob - buy
            if buy <= self.max_price and edge >= self.min_edge and (best is None or edge > best[2]):
                best = (side, prob, edge, buy)
        if best is None:
            return None
        side, prob, edge, buy = best
        return make_signal(self.name, view, side, prob,
                           f"Modell {prob:.2f} vs. Kauf {buy:.2f} (μ={mu:.1f}°F, Edge {edge:+.2f})")
