"""Absicherung der Review-Funde vom 2026-11-03 (Geldrechnung, Abrechnung, Betrieb). Offline."""
import json

import pytest

from paperbot.backtest.engine import BTTrade, CostModel, run_strategy
from paperbot.config import BotConfig
from paperbot.data.base import DataError
from paperbot.data.kalshi import parse_market
from paperbot.fees import FeeModel
from paperbot.models import Market, PricePoint
from paperbot.strategies import FavoriteStrategy
from paperbot.view import MarketInfo, MarketView

DAY = 86_400
HOUR = 3_600
T0 = 1_780_000_000


def _m(**kw):
    base = dict(source="kalshi", market_id="m", question="q", category="politics",
                created_ts=T0, end_ts=T0 + 5 * DAY, end_known_in_advance=True,
                closed=True, outcome=0, resolved_ts=T0 + 5 * DAY, event_id="E")
    base.update(kw)
    return Market(**base)


# ── Briefkurs 1,00 = kein Angebot ────────────────────────────────────────

def test_no_side_without_bid_is_not_tradable():
    # YES-Geld 0 → NO-Brief 1,00: niemand verkauft NO. Früher als Kauf zu 0,99 verbucht.
    hist = [PricePoint(T0 + h * HOUR, 0.025, 0.0, 0.05) for h in range(120)]
    assert run_strategy([(_m(), hist)], FavoriteStrategy(0.90, 0.98), max_spread=0.10) == []


def test_tradable_again_once_a_bid_appears():
    hist = ([PricePoint(T0 + h * HOUR, 0.025, 0.0, 0.05) for h in range(30)]
            + [PricePoint(T0 + h * HOUR, 0.04, 0.03, 0.05) for h in range(30, 120)])
    trades = run_strategy([(_m(), hist)], FavoriteStrategy(0.90, 0.98), max_spread=0.10)
    assert len(trades) == 1 and trades[0].quoted_cost == pytest.approx(0.97)
    assert trades[0].entry_ts >= T0 + 30 * HOUR


def test_quoted_cost_is_not_capped():
    t = BTTrade("s", "m", "q", "", 0, DAY, "YES", 0.98, None, 1, quoted_cost=0.99)
    won = t.ret(CostModel(0.01, slippage=0.02))
    assert won < 0                     # 1,01 bezahlt, 1,00 zurück: ehrlich negativ
    # ohne echten Kurs bleibt der alte Deckel (max_price) bestehen
    plain = BTTrade("s", "m", "q", "", 0, DAY, "YES", 0.985, None, 1)
    assert plain.ret(CostModel(0.01)) == pytest.approx((1 - 0.99) / 0.99)


def test_kalshi_fee_on_quoted_cost():
    t = BTTrade("s", "m", "q", "", 0, DAY, "NO", 0.9, None, 0, quoted_cost=0.92)
    c = 0.92 + 0.07 * 0.92 * 0.08
    assert t.ret(CostModel(0.01, fee=FeeModel("kalshi"))) == pytest.approx((1 - c) / c)


# ── Veraltete Kurse ──────────────────────────────────────────────────────

def test_stale_quote_blocks_entry_but_not_without_rule():
    # Stundenkerzen, dann 20 h ohne gültigen Kurs: Entscheidung bei 24 h sähe einen 20 h alten Kurs.
    hist = [PricePoint(T0 + h * HOUR, 0.05, 0.04, 0.06) for h in range(0, 5)]
    hist += [PricePoint(T0 + h * HOUR, 0.05, 0.04, 0.06) for h in range(30, 120)]
    strat = FavoriteStrategy(0.90, 0.98)
    stale = run_strategy([(_m(), hist)], strat, max_spread=0.1, max_quote_periods=2)
    loose = run_strategy([(_m(), hist)], strat, max_spread=0.1)
    assert loose[0].entry_ts == T0 + 24 * HOUR
    assert stale[0].entry_ts == T0 + 48 * HOUR      # erst wieder mit frischem Kurs


# ── Abrechnung annullierter Kalshi-Märkte ────────────────────────────────

def _raw(**kw):
    base = {"ticker": "T", "event_ticker": "KXHIGHNY-26AUG26", "market_type": "binary",
            "status": "finalized", "result": "void", "open_time": "2026-08-25T14:00:00Z",
            "close_time": "2026-08-27T05:00:00Z", "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42"}
    base.update(kw)
    return base


def test_void_is_closed_without_outcome_and_unknown_result_waits():
    void = parse_market(_raw())
    assert void.closed and void.outcome is None
    odd = parse_market(_raw(result="scalar_42"))
    assert not odd.closed and odd.outcome is None
    live = parse_market(_raw(status="active", result=""))
    assert (live.yes_bid, live.yes_ask) == (0.40, 0.42)


def test_void_kalshi_market_refunds_paper_stake(tmp_path):
    from paperbot.engine import run_cycle
    from paperbot.ledger import LedgerStore
    from paperbot.models import Fill, Signal

    cfg = BotConfig(state_dir=tmp_path, report_dir=tmp_path, arb_scan=False)
    store = LedgerStore(tmp_path)
    leds = store.load(["favorite"], cfg.bankroll)
    sig = Signal("favorite", "T", "YES", 0.4, None, "", T0)
    pos = leds["favorite"].open(sig, Fill("T", "YES", 10, 0.42, 0.02, T0))
    store.save(leds)

    class Client:
        source = "kalshi"
        def list_open_markets(self, limit=200): return []
        def get_market(self, mid): return parse_market(_raw(ticker=mid))
        def price_history(self, *a): return []
        def book(self, *a): return None

    report = run_cycle(Client(), cfg, now_ts=T0 + DAY, strategies=[FavoriteStrategy(name="favorite")])
    assert report.settled == ["favorite:T"]
    led = LedgerStore(tmp_path).load(["favorite"], cfg.bankroll)["favorite"]
    assert led.cash == pytest.approx(cfg.bankroll)            # voller Einsatz zurück
    assert led.closed_positions()[0].payout == pytest.approx(pos.cost)


# ── Live: Vorteil gegen den echten Briefkurs ─────────────────────────────

def test_weather_live_edge_uses_real_ask():
    from datetime import date
    from paperbot.weather import ForecastBook, TempModel, WeatherStrategy, available_from
    d = date(2025, 7, 10)
    now = available_from("KXHIGHNY", d) + HOUR
    m = _m(market_id="KXHIGHNY-25JUL10-B80.5", event_id="KXHIGHNY-25JUL10", series="KXHIGHNY",
           strike_type="between", floor_strike=80.0, cap_strike=81.0, closed=False, outcome=None,
           yes_bid=0.48, yes_ask=0.52)
    book = ForecastBook({("KXHIGHNY", d.isoformat()): 80.5})
    model = TempModel(0.0, 1.15)                     # q ≈ 0,61 für die Spanne 79,5–81,5
    q = model.prob_yes(80.5, 79.5, 81.5)
    real_cost = 0.52 + 0.07 * 0.52 * 0.48            # echter Brief + Gebühr
    mid_cost = 0.51 + 0.07 * 0.51 * 0.49             # Mitte + 1 Cent + Gebühr (alter Live-Weg)
    min_edge = q - (real_cost + mid_cost) / 2        # genau in die Lücke aus dem Review
    assert q - real_cost < min_edge <= q - mid_cost
    strat = WeatherStrategy(model, book, min_edge=min_edge)
    info = MarketInfo.from_market(m, live=True)
    with_quote = strat.evaluate(MarketView(info, [PricePoint(now, 0.50, m.yes_bid, m.yes_ask)], now))
    without = strat.evaluate(MarketView(info, [PricePoint(now, 0.50)], now))
    assert with_quote is None and without is not None


# ── Betrieb: Warnungen und /health ───────────────────────────────────────

def test_kalshi_strategies_report_missing_model_and_forecast(monkeypatch, tmp_path):
    import paperbot.weather as weather
    from paperbot.engine import _kalshi_strategies

    def boom(*a, **k):
        raise DataError("Netz weg")
    monkeypatch.setattr(weather, "fetch_forecasts", boom)
    cfg = BotConfig(state_dir=tmp_path)
    w = [s for s in _kalshi_strategies(cfg) if s.name == "weather"][0]
    text = " | ".join(w.warnings)
    assert "kein Wettermodell" in text and "Vorhersage-Abruf fehlgeschlagen" in text

    (tmp_path / "weather_model_kalshi.json").write_text(json.dumps(
        {"bias": 0.0, "sigma": 2.8, "n": 900, "meta": {"min_edge": 0.1, "verdict": "verworfen"}}),
        encoding="utf-8")
    w = [s for s in _kalshi_strategies(cfg) if s.name == "weather"][0]
    assert w.model is not None and any("verworfen" in x for x in w.warnings)


def test_health_turns_red_when_cycles_see_nothing(tmp_path):
    from paperbot.serve import _State
    st = _State("kalshi", 1800, tmp_path / "x.md")
    st.record({"scanned": 12, "errors": [], "enabled": True})
    assert st.health()["ok"]
    st.record({"scanned": 0, "errors": ["Marktabruf fehlgeschlagen: TLS"], "enabled": True})
    assert st.health()["ok"]                          # ein Ausreißer ist erlaubt
    st.record({"scanned": 0, "errors": [], "enabled": True})
    h = st.health()
    assert not h["ok"] and h["bad_cycles_in_row"] == 2 and h["last_error"] == "0 Märkte gescannt"
    st.record({"scanned": 5, "errors": [], "enabled": True, "warnings": ["weather: kein Wettermodell"]})
    h = st.health()
    assert h["ok"] and h["warnings"] == ["weather: kein Wettermodell"]


def test_serve_stops_after_max_attempts_even_if_all_fail(monkeypatch, tmp_path):
    import paperbot.serve as serve
    monkeypatch.setenv("PAPERBOT_REPORT_DIR", str(tmp_path))

    def fail(src):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(serve, "run_one", fail)
    assert serve.serve("kalshi", interval_min=0.001, port=0, max_cycles=2) == 0
