"""
Konfiguration des Papier-Bots. Alle Werte lassen sich über Umgebungsvariablen
mit dem Präfix PAPERBOT_ überschreiben (z. B. PAPERBOT_BANKROLL=50).

Es gibt bewusst KEINEN Schalter für Echtgeld. Siehe paperbot/__init__.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent.parent

# Peak-Taker-Gebühr (bei Preis 0,5) je Polymarket-Kategorie, Stand Recherche
# 2026-10-22 (Quelle: Pine Analytics / Polymarket-Doku, NICHT live geprüft).
# Formel siehe paperbot/fees.py. Unbekannte Kategorien bekommen DEFAULT.
POLYMARKET_PEAK_FEE = {
    "crypto": 0.018,
    "economics": 0.015,
    "culture": 0.0125,
    "weather": 0.0125,
    "mentions": 0.0156,
    "other": 0.0125,
    "finance": 0.010,
    "politics": 0.010,
    "tech": 0.010,
    "sports": 0.0075,
    "geopolitics": 0.0,
    "world": 0.0,
}
POLYMARKET_DEFAULT_PEAK_FEE = 0.0125

# Wörter, die auf unklare oder strittige Auflösung hindeuten (UMA-Streitfälle
# wie der "Zelenskyy suit"-Markt). Grobe Heuristik, im Zweifel lieber auslassen.
AMBIGUOUS_KEYWORDS: Tuple[str, ...] = (
    " say ", " says ", " said ", "mention", "tweet", " post ", "wear",
    "suit", "outfit", "announce", "rumor", "rumour", "claim",
)


def _env(name: str, default, cast):
    raw = os.environ.get(f"PAPERBOT_{name}")
    if raw is None or raw == "":
        return default
    if cast is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on", "ja")
    if cast is tuple:
        return tuple(x.strip() for x in raw.split(",") if x.strip())
    return cast(raw)


@dataclass(frozen=True)
class BotConfig:
    # ── Konto ─────────────────────────────────────────────────────────────
    bankroll: float = 50.0             # Papiergeld pro Strategie (1 € ≈ 1 USDC)
    state_dir: Path = ROOT / "data" / "paperbot"
    report_dir: Path = ROOT / "reports"

    # ── Schalter ──────────────────────────────────────────────────────────
    enabled: bool = True               # Notaus: False → Zyklus tut nichts
    strategies: Tuple[str, ...] = ("favorite", "calibration", "momentum",
                                   "reversion", "random_control", "llm_blend")
    llm_enabled: bool = False          # LLM-Pipeline kostet API-Aufrufe → aus
    llm_max_markets_per_cycle: int = 2
    llm_weight: float = 1 / 3          # Anteil LLM im Mix mit dem Marktpreis (AIA-Studie)
    arb_scan: bool = True              # YES+NO-Lücken protokollieren (nur echte Orderbücher)
    arb_max_markets: int = 60          # Orderbuch-Abrufe begrenzen (2 pro Markt)
    arb_min_margin: float = 0.005      # Lücke nach Gebühren mind. 0,5 Cent pro Paar

    # ── Markt-Auswahl ─────────────────────────────────────────────────────
    scan_limit: int = 200
    min_volume: float = 5_000.0
    min_liquidity: float = 1_000.0
    min_days_to_end: float = 0.25      # nicht in den letzten 6 Stunden einsteigen
    max_days_to_end: float = 45.0      # Kapital nicht monatelang binden
    max_spread: float = 0.04
    skip_ambiguous: bool = True

    # ── Kosten ────────────────────────────────────────────────────────────
    default_half_spread: float = 0.01  # wenn kein echtes Orderbuch da ist
    min_order_shares: float = 5.0      # Polymarket-Mindestgröße
    max_price: float = 0.98            # nie über 98 Cent kaufen (Rest-Rendite zu klein)

    # ── Risiko ────────────────────────────────────────────────────────────
    stake_frac: float = 0.08           # fester Einsatz ohne kalibrierte Wahrscheinlichkeit
    kelly_fraction: float = 0.25       # Viertel-Kelly bei kalibrierter Wahrscheinlichkeit
    max_stake_frac: float = 0.12       # Obergrenze pro Markt
    max_open_positions: int = 10
    max_exposure_frac: float = 0.85    # mind. 15 % bleiben als Reserve
    max_category_frac: float = 0.40    # Klumpenrisiko je Kategorie
    kill_drawdown_frac: float = 0.30   # Notbremse: −30 % gegenüber Hoch der letzten Tage …
    kill_window_days: int = 30         # … rollierend (Lehre NEMI), nicht Allzeithoch
    pause_days: int = 7                # so lange keine neuen Käufe nach Notbremse

    @classmethod
    def from_env(cls, **overrides) -> "BotConfig":
        cfg = cls()
        values = {}
        for f in fields(cls):
            default = getattr(cfg, f.name)
            if isinstance(default, Path):
                raw = os.environ.get(f"PAPERBOT_{f.name.upper()}")
                values[f.name] = Path(raw) if raw else default
                continue
            cast = type(default) if not isinstance(default, tuple) else tuple
            values[f.name] = _env(f.name.upper(), default, cast)
        cfg = replace(cfg, **values)
        return replace(cfg, **overrides) if overrides else cfg


def peak_fee_for(category: str) -> float:
    key = (category or "").strip().lower()
    # Längere Namen zuerst, sonst passt "politics" auch auf "geopolitics".
    for name in sorted(POLYMARKET_PEAK_FEE, key=len, reverse=True):
        if name in key:
            return POLYMARKET_PEAK_FEE[name]
    return POLYMARKET_DEFAULT_PEAK_FEE
