from __future__ import annotations

import calendar
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from paperbot.data.base import DataError
from paperbot.data.polymarket import PolymarketClient, parse_market
from paperbot.models import BookLevel, PricePoint

FIX = Path(__file__).parent / "fixtures" / "polymarket"
DAY = 86400


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeHttp:
    def __init__(self, routes: Dict[str, Any]) -> None:
        self.routes = routes
        self.calls: List[tuple] = []

    def get_json(self, path: str, params: Any = None) -> Any:
        self.calls.append((path, dict(params or {})))
        route = self.routes[path]
        return route(params or {}) if callable(route) else route


def paged(rows: List[dict]):
    def handler(params: dict) -> List[dict]:
        off = params.get("offset", 0)
        return rows[off: off + params.get("limit", 100)]
    return handler


def gen_markets(n: int) -> List[dict]:
    base = load("markets_open.json")[0]
    out = []
    for i in range(n):
        m = dict(base)
        m["id"] = str(5000 + i)
        out.append(m)
    return out


def ts(*args: int) -> int:
    return calendar.timegm((*args, 0, 0, 0)[:6])


# ── parse_market ────────────────────────────────────────────────────────────

def test_string_and_list_encoded_fields_parse_identically():
    listed = load("markets_open.json")[1]
    encoded = dict(listed)
    for key in ("outcomes", "outcomePrices", "clobTokenIds"):
        encoded[key] = json.dumps(listed[key])
    m_list = parse_market(listed)
    m_str = parse_market(encoded)
    assert m_list is not None
    assert m_str == m_list


def test_string_encoded_market_fields():
    raw = load("markets_open.json")[0]
    m = parse_market(raw)
    tokens = json.loads(raw["clobTokenIds"])
    assert m is not None
    assert m.source == "polymarket"
    assert m.market_id == "1001"
    assert m.yes_token_id == tokens[0] and isinstance(m.yes_token_id, str)
    assert m.no_token_id == tokens[1]
    assert m.last_price == pytest.approx(0.52)
    assert m.url == "https://polymarket.com/event/rain-berlin-2026-12-01"
    assert m.volume == pytest.approx(125000.5)
    assert m.liquidity == pytest.approx(8000.0)
    assert m.category == "weather"
    assert m.end_known_in_advance is True
    assert m.outcome is None and m.resolved_ts is None


def test_fallbacks_for_volume_liquidity_category_and_created():
    m = parse_market(load("markets_open.json")[1])
    assert m is not None
    assert m.volume == pytest.approx(50000.0)
    assert m.liquidity == pytest.approx(1200.5)
    assert m.category == "sports"
    assert m.created_ts == ts(2024, 3, 1)
    assert m.end_ts == ts(2026, 11, 30)


def test_non_binary_market_returns_none():
    assert parse_market(load("markets_open.json")[2]) is None


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("id"),
    lambda r: r.update(outcomePrices="not json"),
    lambda r: r.update(outcomePrices=[]),
    lambda r: r.update(outcomePrices=["1.7", "0.3"]),
    lambda r: r.update(clobTokenIds=[]),
    lambda r: r.update(clobTokenIds=["123"]),
    lambda r: r.update(clobTokenIds=["", "456"]),
    lambda r: r.update(createdAt="gestern"),
    lambda r: r.pop("outcomes"),
])
def test_malformed_market_returns_none(mutate):
    raw = dict(load("markets_open.json")[0])
    mutate(raw)
    assert parse_market(raw) is None


@pytest.mark.parametrize("raw", [None, "x", 42, []])
def test_non_dict_input_returns_none(raw):
    assert parse_market(raw) is None


@pytest.mark.parametrize("closed,prices,expected", [
    (True, ["0.995", "0.005"], 1),
    (True, ["0.003", "0.997"], 0),
    (True, ["0.5", "0.5"], None),
    (True, ["0.989", "0.011"], None),
    (False, ["0.999", "0.001"], None),
])
def test_outcome_from_last_price(closed, prices, expected):
    raw = dict(load("markets_open.json")[0])
    raw.update(closed=closed, outcomePrices=json.dumps(prices))
    m = parse_market(raw)
    assert m is not None
    assert m.outcome == expected


def test_resolved_ts_from_closed_time():
    raw = dict(load("markets_open.json")[0])
    raw.update(closed=True, outcomePrices='["1", "0"]', closedTime="2026-10-01T10:00:00Z")
    m = parse_market(raw)
    assert m is not None
    assert m.outcome == 1
    assert m.resolved_ts == ts(2026, 10, 1) + 10 * 3600


def test_closed_without_closed_time_has_no_resolved_ts():
    raw = dict(load("markets_open.json")[0])
    raw.update(closed=True, outcomePrices='["0", "1"]')
    m = parse_market(raw)
    assert m is not None and m.outcome == 0 and m.resolved_ts is None


@pytest.mark.parametrize("value,expected", [
    ("2024-01-01T00:00:00Z", ts(2024, 1, 1)),
    ("2024-01-01T02:00:00+02:00", ts(2024, 1, 1)),
    ("2024-01-01T12:30:00.500Z", ts(2024, 1, 1) + 45000),
    ("2024-03-31", ts(2024, 3, 31)),
])
def test_iso_timestamp_parsing(value, expected):
    raw = dict(load("markets_open.json")[0])
    raw["endDate"] = value
    m = parse_market(raw)
    assert m is not None
    assert m.end_ts == expected


def test_missing_end_date_is_none_but_market_parses():
    raw = dict(load("markets_open.json")[0])
    del raw["endDate"]
    m = parse_market(raw)
    assert m is not None
    assert m.end_ts is None and m.end_known_in_advance is True


def test_created_falls_back_to_start_date():
    raw = dict(load("markets_open.json")[0])
    del raw["createdAt"]
    raw["startDate"] = "2023-06-15T00:00:00Z"
    m = parse_market(raw)
    assert m is not None
    assert m.created_ts == ts(2023, 6, 15)


# ── PolymarketClient: markets ──────────────────────────────────────────────

def test_list_open_markets_filters_and_counts_skipped():
    gamma = FakeHttp({"markets": paged(load("markets_open.json"))})
    client = PolymarketClient(gamma=gamma, clob=FakeHttp({}))
    markets = client.list_open_markets(limit=200)
    assert [m.market_id for m in markets] == ["1001", "1002"]
    assert client.skipped == 3  # 1003 nicht binär, 1007 Preis defekt, 1008 ohne Tokens
    assert len(gamma.calls) == 1  # 8 Zeilen < angefragte 100 -> Stop


def test_list_open_markets_request_params():
    gamma = FakeHttp({"markets": paged(gen_markets(3))})
    PolymarketClient(gamma=gamma, clob=FakeHttp({})).list_open_markets(limit=3)
    path, params = gamma.calls[0]
    assert path == "markets"
    assert params == {"active": True, "closed": False, "limit": 3, "offset": 0,
                      "order": "volume24hr", "ascending": False}


def test_list_open_markets_pages_until_limit():
    gamma = FakeHttp({"markets": paged(gen_markets(250))})
    markets = PolymarketClient(gamma=gamma, clob=FakeHttp({})).list_open_markets(limit=250)
    assert len(markets) == 250
    assert [(p["offset"], p["limit"]) for _, p in gamma.calls] == [(0, 100), (100, 100), (200, 50)]


def test_list_open_markets_stops_at_limit_mid_page():
    gamma = FakeHttp({"markets": paged(gen_markets(250))})
    markets = PolymarketClient(gamma=gamma, clob=FakeHttp({})).list_open_markets(limit=3)
    assert len(markets) == 3
    assert len(gamma.calls) == 1


def test_list_open_markets_stops_on_short_page():
    rows = gen_markets(150)
    gamma = FakeHttp({"markets": paged(rows[:100] + [])})  # erste Seite voll, zweite leer
    markets = PolymarketClient(gamma=gamma, clob=FakeHttp({})).list_open_markets(limit=200)
    assert len(markets) == 100
    assert len(gamma.calls) == 2


def test_list_open_markets_zero_limit_makes_no_calls():
    gamma = FakeHttp({"markets": paged([])})
    assert PolymarketClient(gamma=gamma, clob=FakeHttp({})).list_open_markets(limit=0) == []
    assert gamma.calls == []


def test_get_market():
    gamma = FakeHttp({"markets/1001": load("market_single.json")})
    m = PolymarketClient(gamma=gamma, clob=FakeHttp({})).get_market("1001")
    assert m is not None and m.market_id == "1001"
    assert gamma.calls == [("markets/1001", {})]


# ── PolymarketClient: book ─────────────────────────────────────────────────

def _client_with_book(raw_book: Any):
    clob = FakeHttp({"book": raw_book})
    return PolymarketClient(gamma=FakeHttp({}), clob=clob), clob


def test_book_sorting_and_timestamp():
    m = parse_market(load("markets_open.json")[0])
    client, clob = _client_with_book(load("book.json"))
    b = client.book(m, "NO")
    assert clob.calls == [("book", {"token_id": m.no_token_id})]
    assert b is not None and b.token_id == m.no_token_id
    assert [lv.price for lv in b.bids] == [0.52, 0.51, 0.50]
    assert [lv.price for lv in b.asks] == [0.53, 0.55]
    assert b.bids[0] == BookLevel(0.52, 120.5)
    assert b.ts == 1729600000
    assert b.best_bid == 0.52 and b.best_ask == 0.53


def test_book_missing_sides_and_timestamp():
    m = parse_market(load("markets_open.json")[0])
    client, _ = _client_with_book({})
    b = client.book(m, "YES")
    assert b is not None
    assert b.bids == () and b.asks == ()
    assert b.ts is None


def test_book_without_token_returns_none_and_makes_no_call():
    m = dataclasses.replace(parse_market(load("markets_open.json")[0]), no_token_id="")
    client, clob = _client_with_book(load("book.json"))
    assert client.book(m, "NO") is None
    assert clob.calls == []


def test_book_malformed_level_raises_data_error():
    m = parse_market(load("markets_open.json")[0])
    client, _ = _client_with_book({"bids": [{"price": "x", "size": "1"}]})
    with pytest.raises(DataError):
        client.book(m, "YES")


# ── PolymarketClient: price history ────────────────────────────────────────

def test_price_history_filters_and_sorts():
    m = parse_market(load("markets_open.json")[0])
    clob = FakeHttp({"prices-history": load("prices_history.json")})
    client = PolymarketClient(gamma=FakeHttp({}), clob=clob)
    pts = client.price_history(m, 1, 2, fidelity=60)
    assert pts == [
        PricePoint(1697875200, 0.52),
        PricePoint(1697875260, 0.55),
        PricePoint(1697875440, 0.0),
        PricePoint(1697875500, 1.0),
    ]
    assert clob.calls == [("prices-history", {
        "market": m.yes_token_id, "startTs": 1, "endTs": 2, "fidelity": 60})]


def test_price_history_without_yes_token_raises_data_error():
    m = dataclasses.replace(parse_market(load("markets_open.json")[0]), yes_token_id="")
    clob = FakeHttp({"prices-history": load("prices_history.json")})
    client = PolymarketClient(gamma=FakeHttp({}), clob=clob)
    with pytest.raises(DataError):
        client.price_history(m, 1, 2)
    assert clob.calls == []


# ── PolymarketClient: resolved markets ─────────────────────────────────────

def _resolved_client():
    gamma = FakeHttp({"markets": paged(load("markets_resolved.json"))})
    hist = load("prices_resolved.json")
    clob = FakeHttp({"prices-history": lambda p: hist[p["market"]]})
    return PolymarketClient(gamma=gamma, clob=clob), gamma, clob


def test_resolved_markets_filters_by_outcome_and_volume():
    client, gamma, _ = _resolved_client()
    res = client.resolved_markets(limit=10)
    assert [m.market_id for m, _ in res] == ["2001", "2002"]
    assert [m.outcome for m, _ in res] == [1, 0]
    # 2003 (void), 2004 (Volumen) gefiltert, nicht gezählt; 2005 (kurz) und 2006 (nicht binär) gezählt
    assert client.skipped == 2
    assert gamma.calls[0] == ("markets", {"closed": True, "limit": 100, "offset": 0,
                                          "order": "id", "ascending": False})


def test_resolved_markets_history_window():
    client, _, clob = _resolved_client()
    client.resolved_markets(limit=10)
    calls = {p["market"]: p for _, p in clob.calls}
    # 2001: Start = createdAt, Ende = closedTime + 1 Tag
    assert calls["2001-yes"] == {"market": "2001-yes", "startTs": ts(2024, 1, 1),
                                 "endTs": ts(2024, 3, 31) + 12 * 3600 + DAY, "fidelity": 720}
    # 2002: ohne createdAt/startDate -> Start = endDate - 90 Tage; Ende = endDate + 1 Tag
    end_2002 = ts(2024, 4, 30)
    assert calls["2002-yes"]["startTs"] == end_2002 - 90 * DAY
    assert calls["2002-yes"]["endTs"] == end_2002 + DAY


def test_resolved_markets_respects_limit():
    client, gamma, _ = _resolved_client()
    res = client.resolved_markets(limit=1)
    assert [m.market_id for m, _ in res] == ["2001"]
    assert len(gamma.calls) == 1


def test_resolved_markets_data_error_is_counted(monkeypatch):
    client, _, _ = _resolved_client()
    original = client.price_history

    def boom(market, start_ts, end_ts, fidelity=60):
        if market.market_id == "2001":
            raise DataError("kaputt")
        return original(market, start_ts, end_ts, fidelity=fidelity)

    monkeypatch.setattr(client, "price_history", boom)
    res = client.resolved_markets(limit=10)
    assert [m.market_id for m, _ in res] == ["2002"]
    assert client.skipped == 3  # 2001 DataError, 2005 kurz, 2006 nicht binär


def test_resolved_markets_rejects_bad_page_size():
    client, _, _ = _resolved_client()
    with pytest.raises(ValueError):
        client.resolved_markets(limit=1, page_size=0)
