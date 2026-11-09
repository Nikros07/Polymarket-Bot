"""
Ein automatischer Papier-Zyklus (für Cron / GitHub Actions gedacht).

1. Offene Positionen prüfen und aufgelöste Märkte abrechnen.
2. Offene Märkte scannen und nach Regeln filtern.
3. Jede Strategie entscheidet für ihr eigenes Papierkonto. NO TRADE ist der
   Normalfall; kein Codepfad erzwingt einen Kauf (Lehre aus Apex).
4. Käufe werden gegen das Orderbuch simuliert, Risiko-Regeln greifen davor.
5. Bewerten, Schnappschuss, Notbremse, atomar speichern.

Fehler einzelner Märkte stoppen den Zyklus nicht, werden aber gezählt und
berichtet. Fehlt der Marktabruf ganz, wird nichts gekauft.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from paperbot.arbitrage import ArbOpportunity, append_opportunities, check_pair
from paperbot.broker import simulate_buy
from paperbot.config import AMBIGUOUS_KEYWORDS, BotConfig
from paperbot.data.base import DataError, MarketDataClient
from paperbot.fees import fee_model_for
from paperbot.ledger import Ledger, LedgerStore
from paperbot.models import Market, PricePoint
from paperbot.risk import size_position
from paperbot.strategies import (CalibrationStrategy, FavoriteStrategy, IsotonicCalibrator,
                                 LLMBlendStrategy, MomentumStrategy, RandomSideControl,
                                 ReversionStrategy)
from paperbot.strategies.base import Strategy
from paperbot.view import DAY, MarketInfo, MarketView

POLYMARKET_SETTLE_GRACE = 7 * DAY


@dataclass
class CycleReport:
    ts: int
    source: str
    enabled: bool = True
    scanned: int = 0
    eligible: int = 0
    signals: int = 0
    opened: List[str] = field(default_factory=list)
    settled: List[str] = field(default_factory=list)
    waiting: List[str] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)   # betriebsbereit, aber eingeschränkt
    paused: List[str] = field(default_factory=list)
    arb_checked: int = 0
    arb_found: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["skipped"] = dict(self.skipped)
        return d


def eligible(m: Market, now_ts: int, cfg: BotConfig) -> Optional[str]:
    """None = handelbar, sonst Grund für den Ausschluss."""
    if m.closed or not m.active or not m.accepting_orders:
        return "nicht handelbar"
    if m.last_price is None:
        return "kein Preis"
    if m.volume < cfg.min_volume:
        return "zu wenig Volumen"
    if m.liquidity < cfg.min_liquidity:
        return "zu wenig Liquidität"
    if m.end_ts is None:
        return "kein Enddatum"
    days = (m.end_ts - now_ts) / DAY
    if days < cfg.min_days_to_end:
        return "zu kurz vor Ende"
    if days > cfg.max_days_to_end:
        return "Ende zu weit weg"
    if cfg.skip_ambiguous:
        q = f" {m.question.lower()} "
        if any(k in q for k in AMBIGUOUS_KEYWORDS):
            return "unklare Auflösung (Stichwort)"
    return None


def build_strategies(cfg: BotConfig, source: str) -> List[Strategy]:
    if source == "kalshi":
        return _kalshi_strategies(cfg)
    cal = IsotonicCalibrator.load(cfg.state_dir / f"calibration_{source}.json")
    favorite = FavoriteStrategy(0.90, 0.98, max_days_to_end=cfg.max_days_to_end, name="favorite")
    available: Dict[str, Strategy] = {
        "favorite": favorite,
        "calibration": CalibrationStrategy(cal, min_edge=0.04, cost=cfg.default_half_spread),
        "momentum": MomentumStrategy(0.10, 3.0, name="momentum"),
        "reversion": ReversionStrategy(0.15, 1.0, name="reversion"),
        "random_control": RandomSideControl(favorite, name="random_control"),
    }
    if cfg.llm_enabled:
        available["llm_blend"] = LLMBlendStrategy(max_calls=cfg.llm_max_markets_per_cycle,
                                                  weight=cfg.llm_weight, cost=cfg.default_half_spread)
    return [available[n] for n in cfg.strategies if n in available]


def _kalshi_strategies(cfg: BotConfig) -> List[Strategy]:
    """Spezialisierung Kalshi-Wetter: Vorhersagemodell (H8), Favoriten (H5) und Zufallskontrolle.

    Ohne gelerntes Modell (erst `python -m paperbot backtest --source kalshi`) kauft
    `weather` nichts. Fehlt der Vorhersage-Abruf, ebenso: NO TRADE ist Standard."""
    from datetime import date, timedelta

    from paperbot.data.base import DataError
    from paperbot.weather import STATIONS, ForecastBook, TempModel, WeatherStrategy, fetch_forecasts
    warnings: List[str] = []
    path = cfg.state_dir / "weather_model_kalshi.json"
    model, min_edge = None, 0.10
    try:
        model = TempModel.load(path)
        meta = json.loads(path.read_text(encoding="utf-8")).get("meta", {}) if model else {}
        min_edge = float(meta.get("min_edge") or 0.10)
        verdict = meta.get("verdict")
        if model is None:
            warnings.append("weather: kein Wettermodell – erst `backtest --source kalshi` (kauft nichts)")
        elif verdict != "bestätigt":
            warnings.append(f"weather: Modell aus H8 mit Urteil „{verdict or 'unbekannt'}“ – "
                            "nur Papier-Vorwärtstest, kein belegter Vorteil")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        model = None
        warnings.append(f"weather: Wettermodell unlesbar ({exc!r})"[:200])
    today = date.today()
    try:
        forecasts = fetch_forecasts(tuple(STATIONS), today - timedelta(days=1), today + timedelta(days=2))
    except (DataError, AttributeError, TypeError, ValueError) as exc:
        forecasts = ForecastBook()
        warnings.append(f"weather: Vorhersage-Abruf fehlgeschlagen ({exc})"[:200])
    missing = [s for s in STATIONS if (s, (today + timedelta(days=1)).isoformat()) not in forecasts.highs]
    if forecasts.highs and missing:
        warnings.append(f"weather: keine Vorhersage für morgen in {', '.join(missing)}")
    favorite = FavoriteStrategy(0.90, 0.98, max_days_to_end=cfg.max_days_to_end, name="favorite")
    weather = WeatherStrategy(model, forecasts, min_edge=min_edge, cost=cfg.default_half_spread)
    weather.warnings = warnings
    available: Dict[str, Strategy] = {
        "weather": weather,
        "favorite": favorite,
        "random_control": RandomSideControl(favorite, name="random_control"),
    }
    return [available[n] for n in cfg.strategies if n in available]


def run_cycle(client: MarketDataClient, cfg: BotConfig, now_ts: Optional[int] = None,
              strategies: Optional[Sequence[Strategy]] = None) -> CycleReport:
    now = int(now_ts if now_ts is not None else time.time())
    report = CycleReport(ts=now, source=client.source, enabled=cfg.enabled)
    if not cfg.enabled:
        report.errors.append("Notaus: PAPERBOT_ENABLED=false")
        return report

    strategies = list(strategies) if strategies is not None else build_strategies(cfg, client.source)
    store = LedgerStore(cfg.state_dir)
    ledgers = store.load([s.name for s in strategies], cfg.bankroll)
    fee = fee_model_for(client.source)

    _settle(client, ledgers, now, report)

    for s in strategies:
        report.warnings.extend(getattr(s, "warnings", None) or [])
    try:
        markets = client.list_open_markets(cfg.scan_limit)
    except DataError as exc:
        report.errors.append(f"Marktabruf fehlgeschlagen: {exc}")
        markets = []
    report.errors.extend(f"Serie {e}" for e in getattr(client, "last_scan_errors", None) or [])
    report.scanned = len(markets)

    for led in ledgers.values():
        led.snapshot(now)              # Verluste aus dem Abrechnen sofort für die Notbremse sichtbar
        if led.update_kill_switch(now, cfg):
            report.paused.append(led.strategy)

    need_history = any(s.needs_history for s in strategies)
    arb_found: List[ArbOpportunity] = []
    for m in markets:
        why = eligible(m, now, cfg)
        if why:
            report.skipped[why] += 1
            continue
        report.eligible += 1
        for led in ledgers.values():
            led.mark(m.market_id, m.last_price)
        history = [PricePoint(now, float(m.last_price), m.yes_bid, m.yes_ask)]
        if need_history:
            try:
                history = client.price_history(m, now - 8 * DAY, now) + history
            except DataError as exc:
                report.errors.append(f"Historie {m.market_id}: {exc}")
        view = MarketView(MarketInfo.from_market(m, live=True), history, now)
        books: Dict[str, object] = {}
        for strat in strategies:
            led = ledgers[strat.name]
            if led.has_position(m.market_id) or led.is_paused(now):
                continue
            if strat.needs_history and len(view.history()) < 2:
                continue
            try:
                sig = strat.evaluate(view)
            except Exception as exc:   # eine kaputte Strategie darf die anderen nicht stoppen
                report.errors.append(f"{strat.name} bei {m.market_id}: {exc!r}"[:300])
                continue
            if sig is None:
                continue
            report.signals += 1
            _try_open(client, cfg, fee, led, m, sig, books, now, report)
        if cfg.arb_scan and report.arb_checked < cfg.arb_max_markets:
            _scan_arbitrage(client, cfg, fee, m, books, now, report, arb_found)

    for led in ledgers.values():
        led.snapshot(now)
    store.save(ledgers, meta={"last_cycle": report.as_dict()})
    _append_forecasts(cfg, strategies)
    append_opportunities(cfg.state_dir / "arbitrage.jsonl", arb_found)
    return report


def _get_book(client, m: Market, side: str, books: Dict[str, object], report: "CycleReport"):
    if side not in books:
        try:
            books[side] = client.book(m, side)
        except DataError as exc:
            report.errors.append(f"Orderbuch {m.market_id}: {exc}")
            books[side] = None
    return books[side]


def _scan_arbitrage(client, cfg, fee, m: Market, books, now, report, found: List[ArbOpportunity]) -> None:
    yes = _get_book(client, m, "YES", books, report)
    if yes is None or yes.synthetic:       # Spielgeld-AMM (Manifold) hat keine zwei Orderbücher
        return
    no = _get_book(client, m, "NO", books, report)
    report.arb_checked += 1
    opp = check_pair(m, yes, no, fee, now, cfg.arb_min_margin)
    if opp is not None:
        found.append(opp)
        report.arb_found.append(f"{m.market_id}: +{opp.margin:.3f} × {opp.max_pairs:.0f}")


def _settle(client: MarketDataClient, ledgers: Dict[str, Ledger], now: int, report: CycleReport) -> None:
    ids = sorted({p.market_id for led in ledgers.values() for p in led.open_positions()})
    for mid in ids:
        try:
            m = client.get_market(mid)
        except DataError as exc:
            report.errors.append(f"Abruf {mid}: {exc}")
            continue
        if m is None:
            report.errors.append(f"Markt {mid} nicht gefunden")
            continue
        for led in ledgers.values():
            led.mark(mid, m.last_price)
        if not m.closed:
            continue
        outcome, yes_payout = None, None
        if m.outcome in (0, 1):
            outcome = m.outcome
        elif m.resolution_price is not None:
            yes_payout = m.resolution_price          # Manifold MKT: Teil-Auszahlung
        elif m.source in ("manifold", "kalshi"):
            pass                                     # CANCEL / void → Einsatz zurück
        else:
            # Polymarket: geschlossen, aber kein klares Ergebnis. Erst warten (UMA-Prüfung),
            # nach der Frist zum letzten Preis abrechnen (deckt 50/50-Auflösungen ab).
            closed_at = m.resolved_ts or m.end_ts or now
            if now - closed_at < POLYMARKET_SETTLE_GRACE or m.last_price is None:
                report.waiting.append(mid)
                continue
            yes_payout = m.last_price
        for led in ledgers.values():
            if led.settle(mid, outcome, now, yes_payout=yes_payout) is not None:
                report.settled.append(f"{led.strategy}:{mid}")


def _try_open(client, cfg, fee, led: Ledger, m: Market, sig, books, now, report) -> None:
    book = _get_book(client, m, sig.side, books, report)
    if book is None or book.best_ask is None:
        report.skipped["kein Orderbuch"] += 1
        return
    if book.spread is not None and book.spread > cfg.max_spread:
        report.skipped["Spread zu groß"] += 1
        return
    ask = book.best_ask
    if ask > cfg.max_price:
        report.skipped["Preis über Höchstpreis"] += 1
        return
    cps = ask + fee.per_share(ask, m.category)
    decision = size_position(sig, cps, equity=led.equity(), cash=led.cash,
                             open_positions=led.open_positions(), category=m.category, cfg=cfg)
    if decision.stake <= 0:
        report.skipped[decision.reason] += 1
        return
    result = simulate_buy(book, decision.stake, side=sig.side, market_id=m.market_id, ts=now,
                          fee=fee, category=m.category, min_shares=cfg.min_order_shares,
                          max_price=cfg.max_price)
    if result.fill is None:
        report.skipped[result.reason.split(" (")[0]] += 1
        return
    led.open(sig, result.fill, question=m.question, category=m.category)
    report.opened.append(f"{led.strategy}:{m.market_id}:{sig.side}@{result.fill.avg_price:.3f}")


def _append_forecasts(cfg: BotConfig, strategies: Sequence[Strategy]) -> None:
    rows = []
    for s in strategies:
        log = getattr(s, "forecast_log", None)
        if log:
            rows.extend({"strategy": s.name, **r} for r in log)
            log.clear()
    if rows:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        with (cfg.state_dir / "forecasts.jsonl").open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
