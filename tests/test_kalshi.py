"""Tests für die Kalshi-Quelle, echte Briefkurse im Backtest, Kalshi-Gebühr und Event-Bootstrap.
Offline: die HTTP-Schicht ist durch eine Attrappe ersetzt."""
import math

import numpy as np
import pytest

from paperbot.backtest import metrics
from paperbot.backtest.datasets import load_dataset, save_dataset
from paperbot.backtest.engine import BTTrade, CostModel, run_strategy
from paperbot.backtest.experiment import evaluate
from paperbot.broker import simulate_buy
from paperbot.data.base import DataError
from paperbot.data.http import NotFoundError
from paperbot.data.kalshi import (KalshiClient, event_date, parse_candles, parse_market,
                                  parse_orderbook, quote_mid)
from paperbot.fees import FeeModel, fee_model_for, kalshi_fee_per_share
from paperbot.models import Book, BookLevel, Market, PricePoint
from paperbot.strategies import FavoriteStrategy

DAY = 86_400
T0 = 1_780_000_000


def _raw(**kw):
    base = {"ticker": "KXHIGHNY-26AUG26-B80.5", "event_ticker": "KXHIGHNY-26AUG26",
            "market_type": "binary", "status": "finalized", "result": "yes",
            "open_time": "2026-08-25T14:00:00Z", "close_time": "2026-08-27T05:00:00Z",
            "settlement_ts": "2026-08-27T11:10:25.7Z", "can_close_early": True,
            "volume_fp": "33703.75", "open_interest_fp": "1200", "last_price_dollars": "0.9900",
            "yes_bid_dollars": "0.9800", "yes_ask_dollars": "0.9900", "title": "High NYC",
            "yes_sub_title": "80° to 81°", "strike_type": "between", "floor_strike": 80, "cap_strike": 81}
    base.update(kw)
    return base


# ── Parsen ───────────────────────────────────────────────────────────────

def test_parse_settled_market():
    m = parse_market(_raw(), "Climate and Weather", "KXHIGHNY")
    assert m.source == "kalshi" and m.closed and m.outcome == 1
    assert m.event_id == "KXHIGHNY-26AUG26" and m.series == "KXHIGHNY"
    assert (m.strike_type, m.floor_strike, m.cap_strike) == ("between", 80.0, 81.0)
    assert m.last_price == pytest.approx(0.985)            # Mitte aus Geld/Brief
    assert m.end_known_in_advance is False                 # can_close_early
    assert m.resolved_ts > m.end_ts > m.created_ts
    assert m.category == "climate and weather"


def test_closed_without_result_is_not_settled():
    m = parse_market(_raw(status="closed", result=""))
    assert not m.closed and m.outcome is None and not m.active


def test_parse_rejects_non_binary_and_garbage():
    assert parse_market(_raw(market_type="scalar")) is None
    assert parse_market({"nonsense": 1}) is None


def test_event_date():
    assert event_date("KXHIGHNY-26AUG26").isoformat() == "2026-08-26"
    assert event_date("HIGHNY-21AUG06").isoformat() == "2021-08-06"
    assert event_date("KXFED") is None


def test_candles_use_period_end_and_skip_fake_quotes():
    rows = [
        {"end_period_ts": T0 + 7200, "yes_bid": {"close_dollars": "0.40"}, "yes_ask": {"close_dollars": "0.44"}},
        {"end_period_ts": T0 + 3600, "yes_bid": {"close": "0.30"}, "yes_ask": {"close": "0.32"}},
        {"end_period_ts": T0 + 10800, "yes_bid": {"close": 0}, "yes_ask": {"close": 100}},     # alte Cent-Werte, kein Kurs
        {"end_period_ts": T0 + 14400, "yes_bid": {"close": 45}, "yes_ask": {"close": 47}},     # alte Cent-Werte
    ]
    pts = parse_candles(rows)
    assert [p.t for p in pts] == [T0 + 3600, T0 + 7200, T0 + 14400]
    assert pts[0] == PricePoint(T0 + 3600, pytest.approx(0.31), 0.30, 0.32)
    assert pts[2].bid == pytest.approx(0.45) and pts[2].ask == pytest.approx(0.47)
    with pytest.raises(DataError):
        parse_candles([{"yes_bid": {}}])


def test_quote_mid_rules():
    assert quote_mid(0.0, 0.01) == pytest.approx(0.005)
    assert quote_mid(0.5, 0.5) is None and quote_mid(0.0, 1.0) is None and quote_mid(None, 0.4) is None


def test_orderbook_buy_side_comes_from_other_sides_bids():
    raw = {"orderbook_fp": {"yes_dollars": [["0.05", "100"], ["0.04", "50"]],
                            "no_dollars": [["0.94", "30"], ["0.93", "500"]]}}
    yes = parse_orderbook(raw, "T", "YES")
    no = parse_orderbook(raw, "T", "NO")
    assert yes.best_ask == pytest.approx(0.06) and yes.asks[0].size == 30   # 1 − bestes NO-Gebot
    assert yes.best_bid == pytest.approx(0.05)
    assert no.best_ask == pytest.approx(0.95) and no.best_bid == pytest.approx(0.94)
    old = parse_orderbook({"orderbook": {"yes": [[5, 10]], "no": [[94, 10]]}}, "T", "YES")
    assert old.best_ask == pytest.approx(0.06)


# ── Client mit Attrappe ──────────────────────────────────────────────────

class FakeHttp:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get_json(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        r = self.routes.get(path)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise NotFoundError(path)
        return r(params) if callable(r) else r


def test_get_market_falls_back_to_archive():
    http = FakeHttp({"series": {"series": [{"ticker": "KXHIGHNY", "category": "Climate and Weather"}]},
                     "historical/markets/X": {"market": _raw(ticker="X")}})
    m = KalshiClient(http).get_market("X")
    assert m.market_id == "X" and m.outcome == 1 and m.category == "climate and weather"
    # Wetter-Serie: Kategorie steht fest, kein /series-Abruf nötig
    assert [c[0] for c in http.calls] == ["markets/X", "historical/markets/X"]


def test_list_open_markets_only_active():
    rows = [_raw(ticker="A", status="active", result=""), _raw(ticker="B", status="closed", result="")]
    http = FakeHttp({"series": {"series": []}, "markets": {"markets": rows}})
    ms = KalshiClient(http, series=("KXHIGHNY",)).list_open_markets()
    assert [m.market_id for m in ms] == ["A"]


def test_candles_are_batched_within_api_limit():
    def resp(p):
        return {"markets": [{"market_ticker": t, "candlesticks": [
            {"end_period_ts": T0 + 3600, "yes_bid": {"close": "0.2"}, "yes_ask": {"close": "0.3"}}]}
            for t in p["market_tickers"].split(",")]}
    http = FakeHttp({"markets/candlesticks": resp})
    tickers = [f"T{i}" for i in range(120)]
    got = KalshiClient(http).candles(tickers, T0, T0 + 30 * DAY, 60)   # 721 Kerzen je Markt
    assert len(got) == 120
    for _, p in http.calls:
        n = len(p["market_tickers"].split(","))
        assert n * 721 <= 5000


# ── Gebühr und Broker ────────────────────────────────────────────────────

def test_kalshi_fee_formula_and_rounding():
    assert kalshi_fee_per_share(0.5) == pytest.approx(0.0175)
    assert kalshi_fee_per_share(0.9) == pytest.approx(0.0063)
    assert kalshi_fee_per_share(1.0) == 0.0
    f = FeeModel("kalshi")
    assert f.total(5, 0.9) == pytest.approx(0.04)          # 0,0315 → aufgerundet
    assert f.total(100, 0.5) == pytest.approx(1.75)        # genau, keine Rundung nach oben
    assert fee_model_for("kalshi") == f and fee_model_for("kalshi_weather") == f


def test_broker_kalshi_cost_never_exceeds_budget():
    book = Book("T:YES", asks=(BookLevel(0.90, 1000),))
    for budget in (4.6, 5.0, 7.33, 12.0):
        r = simulate_buy(book, budget, side="YES", market_id="T", ts=0, fee=FeeModel("kalshi"))
        assert r.fill is not None
        assert r.fill.cost <= budget + 1e-9
        assert r.fill.fee * 100 == pytest.approx(round(r.fill.fee * 100))   # ganze Cent


# ── Backtest mit echtem Briefkurs ────────────────────────────────────────

def _bt_market(**kw):
    base = dict(source="kalshi", market_id="m", question="q", category="politics",
                created_ts=T0, end_ts=T0 + 5 * DAY, end_known_in_advance=True,
                closed=True, outcome=0, resolved_ts=T0 + 5 * DAY, event_id="E1")
    base.update(kw)
    return Market(**base)


def test_quoted_ask_replaces_assumed_spread():
    t = BTTrade("s", "m", "q", "", 0, DAY, "YES", 0.90, None, 1, quoted_cost=0.93)
    assert t.ret(CostModel(0.01)) == pytest.approx((1 - 0.93) / 0.93)
    assert t.ret(CostModel(0.01, slippage=0.02)) == pytest.approx((1 - 0.95) / 0.95)
    k = CostModel(0.01, fee=FeeModel("kalshi"))
    c = 0.93 + 0.07 * 0.93 * 0.07
    assert t.ret(k) == pytest.approx((1 - c) / c)


def test_run_strategy_records_no_side_ask_and_skips_wide_spreads():
    hist = [PricePoint(T0 + h * 3600, 0.08, 0.07, 0.09) for h in range(0, 120)]
    ds = [(_bt_market(), hist)]
    trades = run_strategy(ds, FavoriteStrategy(0.90, 0.98), max_spread=0.10)
    assert len(trades) == 1 and trades[0].side == "NO"
    assert trades[0].quoted_cost == pytest.approx(0.93)        # 1 − Geld 0,07
    assert trades[0].event_id == "E1"
    wide = [PricePoint(T0 + h * 3600, 0.08, 0.0, 0.16) for h in range(0, 120)]
    assert run_strategy([(_bt_market(), wide)], FavoriteStrategy(0.90, 0.98), max_spread=0.10) == []


def test_cluster_bootstrap_is_wider_for_dependent_markets():
    rng = np.random.default_rng(1)
    ev = rng.normal(0.02, 0.3, 40)
    r = np.repeat(ev, 6)                      # 6 identische Märkte je Event
    plain = metrics.roi_stats(r)
    clus = metrics.roi_stats(r, clusters=np.repeat(np.arange(40), 6).astype(str))
    assert clus["n_clusters"] == 40
    assert clus["mean"] == pytest.approx(plain["mean"])
    assert (clus["ci_hi"] - clus["ci_lo"]) > 1.8 * (plain["ci_hi"] - plain["ci_lo"])
    with pytest.raises(ValueError):
        metrics.roi_stats([0.1, 0.2], clusters=["a"])


def test_evaluate_clustered_uses_events():
    trades = [BTTrade("s", f"m{i}", "q", "", 0, DAY, "YES", 0.9, None, 1, event_id=f"E{i // 3}")
              for i in range(60)]
    e = evaluate("x", trades, CostModel(0.0), clustered=True)
    assert e.n == 60 and e.n_clusters == 20
    assert e.by_cost["0.00"] == pytest.approx(e.by_cost["0.00"])


def test_dataset_roundtrip_keeps_quotes(tmp_path):
    m = _bt_market(series="KXHIGHNY", strike_type="less", cap_strike=60.0)
    ds = [(m, [PricePoint(T0, 0.5, 0.49, 0.51), PricePoint(T0 + 7200, 0.6)])]
    save_dataset(ds, tmp_path / "d.json.gz")
    back = load_dataset(tmp_path / "d.json.gz", bucket_s=0)
    assert back[0][0] == m
    assert back[0][1] == ds[0][1]


def test_archived_markets_fall_back_to_single_archive_candles():
    """Lauf 2026-10-27: Der Batch-Endpunkt lieferte für archivierte Märkte nichts,
    dadurch fehlten fast alle Wettermärkte vor dem Archiv-Stichtag."""
    candle = {"end_period_ts": T0 + 3600, "yes_bid": {"close": "0.2"}, "yes_ask": {"close": "0.3"}}
    candle2 = {**candle, "end_period_ts": T0 + 7200}
    http = FakeHttp({
        "markets/candlesticks": {"markets": []},                       # Batch kennt das Archiv nicht
        "historical/markets/OLD-1/candlesticks": {"candlesticks": [candle, candle2]},
        "historical/markets/OLD-2/candlesticks": NotFoundError("weg"),
    })
    ms = [_bt_market(market_id=t, event_id="OLD", created_ts=T0, end_ts=T0 + DAY, resolved_ts=T0 + DAY)
          for t in ("OLD-1", "OLD-2")]
    out = KalshiClient(http)._with_history(ms)
    assert [m.market_id for m, _ in out] == ["OLD-1"]
    assert out[0][1][0].bid == pytest.approx(0.2)


# ── Datenqualität (Lehre aus dem Lauf vom 2026-10-27) ─────────────────────

def test_history_counts_kept_and_dropped_markets():
    candle = {"end_period_ts": T0 + 3600, "yes_bid": {"close": "0.2"}, "yes_ask": {"close": "0.3"}}
    http = FakeHttp({
        "markets/candlesticks": DataError("HTTP 429 nach 7 Versuchen"),      # Batch fällt aus
        "historical/markets/A/candlesticks": {"candlesticks": [candle, {**candle, "end_period_ts": T0 + 7200}]},
        "historical/markets/B/candlesticks": {"candlesticks": []},
    })
    c = KalshiClient(http)
    ms = [_bt_market(market_id=t, event_id="E", created_ts=T0, end_ts=T0 + DAY, resolved_ts=T0 + DAY)
          for t in ("A", "B")]
    out = c._with_history(ms)
    assert [m.market_id for m, _ in out] == ["A"]          # Batch-Fehler verwirft nicht still
    assert c.stats["ausgewählt"] == 2 and c.stats["mit Preisen"] == 1
    assert c.stats["ohne Preise verworfen"] == 1 and c.stats["Batch-Fehler (Events)"] == 1


def test_quality_check_blocks_biased_samples(tmp_path):
    from paperbot.backtest.datasets import check_quality, load_quality, save_quality
    ds_path = tmp_path / "kalshi_weather_30000.json.gz"
    m = _bt_market()
    q = save_quality(ds_path, {"ausgewählt": 15300, "mit Preisen": 924, "ohne Preise verworfen": 14376},
                     [(m, [])])
    assert load_quality(ds_path) == q and q["erster_markt_ts"] == T0
    msg = check_quality(q, "kalshi_weather")
    assert msg is not None and "14376 von 15300" in msg
    assert check_quality({"ausgewählt": 100, "ohne Preise verworfen": 10}, "x") is None
    assert "keine Qualitätsdatei" in check_quality(None, "x")
