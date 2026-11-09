"""Kompletter Papier-Zyklus für Kalshi-Wetter, offline (kein Netzwerk).

Geprüft wird das Zusammenspiel aus run_cycle, Kalshi-Gebühr (ganze Cent je Order),
Vorhersage-Sperre (ForecastBook/available_from) und Abrechnung nach Auflösung.
"""
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from paperbot.config import BotConfig
from paperbot.data.kalshi import parse_orderbook
from paperbot.engine import run_cycle
from paperbot.ledger import LedgerStore
from paperbot.models import Market
from paperbot.weather import ForecastBook, TempModel, WeatherStrategy, available_from

DAY = 86_400
TICKER = "KXHIGHNY-25JUL10-B80.5"
OPEN_TS = int(datetime(2025, 7, 9, 14, 0, tzinfo=timezone.utc).timestamp())
NOW_BUY = int(datetime(2025, 7, 9, 20, 0, tzinfo=timezone.utc).timestamp())
NOW_SETTLE = OPEN_TS + 2 * DAY


def _market(**kw):
    base = dict(source="kalshi", market_id=TICKER, question="High NYC — 80° to 81°",
                category="climate and weather", created_ts=OPEN_TS,
                end_ts=OPEN_TS + 39 * 3600, end_known_in_advance=False,
                volume=20_000, liquidity=20_000, active=True, accepting_orders=True,
                event_id="KXHIGHNY-25JUL10", series="KXHIGHNY", strike_type="between",
                floor_strike=80.0, cap_strike=81.0, last_price=0.30)
    base.update(kw)
    return Market(**base)


class FakeKalshiClient:
    """Speicher-Quelle für Kalshi: Märkte, Orderbuch aus parse_orderbook, keine Historie."""
    source = "kalshi"

    def __init__(self, markets):
        self.markets = {m.market_id: m for m in markets}
        self.calls = []

    def set_market(self, market_id, **changes):
        self.markets[market_id] = replace(self.markets[market_id], **changes)

    def list_open_markets(self, limit=200):
        self.calls.append("list")
        return [m for m in self.markets.values() if not m.closed][:limit]

    def get_market(self, market_id):
        self.calls.append(f"get:{market_id}")
        return self.markets.get(market_id)

    def price_history(self, market, start_ts, end_ts):
        return []

    def book(self, market, side):
        self.calls.append(f"book:{market.market_id}:{side}")
        raw = {"orderbook_fp": {"yes_dollars": [["0.29", "500"]], "no_dollars": [["0.69", "500"]]}}
        return parse_orderbook(raw, market.market_id, side)


def _cfg(tmp_path):
    return BotConfig(state_dir=tmp_path, report_dir=tmp_path, arb_scan=False)


def _weather(forecasts):
    return WeatherStrategy(TempModel(0.0, 1.5), forecasts, min_edge=0.05)


def _forecast_80_5():
    return ForecastBook({("KXHIGHNY", "2025-07-10"): 80.5})


def _weather_ledger(tmp_path):
    return LedgerStore(tmp_path).load(["weather"], 50.0)["weather"]


def test_weather_cycle_opens_paper_position_with_kalshi_fee(tmp_path):
    # Vorhersage ist ab D−1 06:00 Ortszeit (10:00 UTC) bekannt; 20:00 UTC liegt danach.
    assert NOW_BUY >= available_from("KXHIGHNY", date(2025, 7, 10))
    client = FakeKalshiClient([_market()])
    cfg = _cfg(tmp_path)

    report = run_cycle(client, cfg, now_ts=NOW_BUY, strategies=[_weather(_forecast_80_5())])

    assert len(report.opened) == 1
    assert ":YES@" in report.opened[0]

    led = _weather_ledger(tmp_path)
    assert len(led.open_positions()) == 1
    pos = led.open_positions()[0]

    # Kalshi rundet die Gebühr je Order auf ganze Cent auf
    cents = pos.fee * 100
    assert abs(cents - round(cents)) < 1e-6
    assert pos.fee > 0

    assert pos.cost <= cfg.bankroll
    # Bargeld um genau die Kosten der Position gesunken
    assert led.cash == pytest.approx(cfg.bankroll - pos.cost)


def test_no_forecast_means_no_trade(tmp_path):
    client = FakeKalshiClient([_market()])

    report = run_cycle(client, _cfg(tmp_path), now_ts=NOW_BUY, strategies=[_weather(ForecastBook())])

    assert report.opened == []
    assert report.signals == 0


def test_settles_when_market_resolves(tmp_path):
    client = FakeKalshiClient([_market()])
    cfg = _cfg(tmp_path)
    strategies = [_weather(_forecast_80_5())]

    run_cycle(client, cfg, now_ts=NOW_BUY, strategies=strategies)
    led_before = _weather_ledger(tmp_path)
    assert len(led_before.open_positions()) == 1
    shares = led_before.open_positions()[0].shares
    cash_before = led_before.cash

    # Markt wird aufgelöst: YES gewinnt, nicht mehr offen
    client.set_market(TICKER, closed=True, outcome=1, active=False, last_price=1.0)

    report = run_cycle(client, cfg, now_ts=NOW_SETTLE, strategies=strategies)

    assert f"weather:{TICKER}" in report.settled
    led_after = _weather_ledger(tmp_path)
    assert not led_after.open_positions()
    assert led_after.cash == pytest.approx(cash_before + shares * 1.0)
