from __future__ import annotations

import gzip
import json
from typing import Any, Callable, Dict, List, Optional

import pytest

from paperbot.data.base import DataError
from paperbot.data.manifold import ManifoldClient, bets_to_history, parse_market
from paperbot.models import Market, PricePoint


class FakeHttp:
    """Zeichnet (path, params) auf und liefert Antworten aus einer Handler-Funktion."""

    def __init__(self, handler: Callable[[str, dict], Any]) -> None:
        self.handler = handler
        self.calls: List[tuple] = []

    def get_json(self, path: str, params: Optional[dict] = None) -> Any:
        params = dict(params or {})
        self.calls.append((path, params))
        return self.handler(path, params)


def pages_handler(pages: List[Any]) -> Callable[[str, dict], Any]:
    """Liefert für jeden Aufruf der Reihe nach `pages`, danach leere Listen."""
    it = iter(pages)
    return lambda path, params: next(it, [])


def raw_market(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": "m1",
        "question": "Will X happen?",
        "slug": "will-x",
        "creatorUsername": "alice",
        "createdTime": 1_700_000_000_000,
        "closeTime": 1_710_000_000_000,
        "probability": 0.62,
        "totalLiquidity": 500.0,
        "outcomeType": "BINARY",
        "mechanism": "cpmm-1",
        "volume": 2500.0,
        "isResolved": False,
        "uniqueBettorCount": 40,
        "groupSlugs": ["politics"],
    }
    base.update(over)
    return base


def resolved_raw(mid: str, created_ms: int, resolution: str = "YES",
                 bettors: int = 50, volume: float = 2000.0) -> Dict[str, Any]:
    return raw_market(
        id=mid,
        createdTime=created_ms,
        resolution=resolution,
        isResolved=True,
        resolutionTime=created_ms + 1000,
        uniqueBettorCount=bettors,
        volume=volume,
    )


def bet(bid: str, created_ms: int, prob_after: Optional[float],
        prob_before: Optional[float] = None, cancelled: bool = False) -> Dict[str, Any]:
    b: Dict[str, Any] = {
        "id": bid,
        "contractId": "c1",
        "createdTime": created_ms,
        "probAfter": prob_after,
        "isCancelled": cancelled,
        "isRedemption": False,
        "isFilled": True,
        "amount": 10.0,
        "outcome": "YES",
    }
    if prob_before is not None:
        b["probBefore"] = prob_before
    return b


def make_bets(start: int, n: int) -> List[Dict[str, Any]]:
    return [bet(f"b{i}", 1_000_000 + i, 0.5, 0.5) for i in range(start, start + n)]


def make_market(market_id: str = "m1", last_price: Optional[float] = None) -> Market:
    return Market(source="manifold", market_id=market_id, question="Q?", last_price=last_price)


def client(pages: Optional[List[Any]] = None, **kw: Any) -> ManifoldClient:
    return ManifoldClient(http=FakeHttp(pages_handler(pages or [])), **kw)


# ── parse_market ──────────────────────────────────────────────────────────

def test_parse_open_market_fields():
    m = parse_market(raw_market())
    assert m is not None
    assert m.source == "manifold"
    assert m.market_id == "m1"
    assert m.question == "Will X happen?"
    assert m.slug == "will-x"
    assert m.url == "https://manifold.markets/alice/will-x"
    assert m.created_ts == 1_700_000_000
    assert m.end_ts == 1_710_000_000
    assert m.end_known_in_advance is False
    assert m.volume == 2500.0
    assert m.liquidity == 500.0
    assert m.category == "politics"
    assert m.closed is False
    assert m.outcome is None
    assert m.resolved_ts is None
    assert m.last_price == pytest.approx(0.62)


@pytest.mark.parametrize(
    "resolution, outcome",
    [("YES", 1), ("NO", 0), ("MKT", None), ("CANCEL", None)],
)
def test_parse_resolution_mapping(resolution, outcome):
    m = parse_market(raw_market(isResolved=True, resolution=resolution,
                                resolutionTime=1_711_000_000_000))
    assert m is not None
    assert m.closed is True
    assert m.outcome == outcome
    assert m.resolved_ts == 1_711_000_000


def test_parse_non_binary_returns_none():
    assert parse_market(raw_market(outcomeType="MULTIPLE_CHOICE")) is None


def test_parse_url_fallback_and_explicit_url():
    no_url = parse_market(raw_market())
    assert no_url is not None and no_url.url == "https://manifold.markets/alice/will-x"
    with_url = parse_market(raw_market(url="https://manifold.markets/custom"))
    assert with_url is not None and with_url.url == "https://manifold.markets/custom"


def test_parse_no_groups_gives_empty_category():
    m = parse_market(raw_market(groupSlugs=[]))
    assert m is not None and m.category == ""
    m2 = parse_market(raw_market(groupSlugs=None))
    assert m2 is not None and m2.category == ""


def test_parse_problem_returns_none():
    raw = raw_market()
    del raw["id"]
    assert parse_market(raw) is None
    assert parse_market(raw_market(probability="abc")) is None


# ── bets_to_history ───────────────────────────────────────────────────────

def test_cancelled_and_missing_prob_after_are_skipped():
    bets = [
        bet("a", 10_000, 0.6, prob_before=0.5),
        bet("x", 11_000, 0.9, cancelled=True),
        bet("y", 12_000, None, prob_before=0.6),
    ]
    assert bets_to_history(bets) == [PricePoint(9, 0.5), PricePoint(10, 0.6)]


def test_sorted_by_time_with_start_point_from_first_kept_bet():
    bets = [bet("b", 20_000, 0.7), bet("a", 10_000, 0.6, prob_before=0.5)]
    assert bets_to_history(bets) == [
        PricePoint(9, 0.5),
        PricePoint(10, 0.6),
        PricePoint(20, 0.7),
    ]


def test_no_start_point_without_prob_before():
    assert bets_to_history([bet("a", 10_000, 0.6)]) == [PricePoint(10, 0.6)]


def test_same_second_keeps_last():
    bets = [bet("a", 30_100, 0.4), bet("b", 30_900, 0.45)]
    assert bets_to_history(bets) == [PricePoint(30, 0.45)]


def test_clipping_to_unit_interval():
    bets = [bet("a", 10_000, 1.2, prob_before=-0.1)]
    assert bets_to_history(bets) == [PricePoint(9, 0.0), PricePoint(10, 1.0)]


# ── fetch_bets ────────────────────────────────────────────────────────────

def test_fetch_bets_pages_with_after_cursor_and_dedupes():
    page1 = make_bets(0, 1000)
    page2 = make_bets(999, 1) + make_bets(1000, 2)  # b999 ist Duplikat
    http = FakeHttp(pages_handler([page1, page2]))
    bets = ManifoldClient(http=http).fetch_bets("c1")

    assert [b["id"] for b in bets] == [f"b{i}" for i in range(1002)]
    assert http.calls[0] == ("bets", {"contractId": "c1", "limit": 1000, "order": "asc"})
    assert http.calls[1] == (
        "bets",
        {"contractId": "c1", "limit": 1000, "order": "asc", "afterTime": 1_000_000 + 999},
    )
    assert len(http.calls) == 2


def test_fetch_bets_stops_at_max_bets():
    http = FakeHttp(pages_handler([make_bets(0, 1000), make_bets(1000, 1000)]))
    bets = ManifoldClient(http=http).fetch_bets("c1", max_bets=1000)
    assert len(bets) == 1000
    assert len(http.calls) == 1


def test_fetch_bets_stops_on_page_of_only_duplicates():
    http = FakeHttp(pages_handler([make_bets(0, 1000), make_bets(0, 1000)]))
    bets = ManifoldClient(http=http).fetch_bets("c1")
    assert len(bets) == 1000
    assert len(http.calls) == 2


def test_cache_round_trip_skips_network(tmp_path):
    http = FakeHttp(pages_handler([make_bets(0, 3)]))
    first = ManifoldClient(http=http, cache_dir=tmp_path).fetch_bets("c1")

    cache_file = tmp_path / "manifold" / "c1.json.gz"
    assert cache_file.exists()
    with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
        assert json.load(fh) == first

    http2 = FakeHttp(pages_handler([]))
    second = ManifoldClient(http=http2, cache_dir=tmp_path).fetch_bets("c1")
    assert second == first
    assert http2.calls == []


# ── price_history ─────────────────────────────────────────────────────────

def test_price_history_window_includes_prior_start_point():
    bets = [
        bet("a", 100_000, 0.1),
        bet("b", 200_000, 0.2),
        bet("c", 300_000, 0.3),
        bet("d", 400_000, 0.4),
    ]
    http = FakeHttp(pages_handler([bets]))
    pts = ManifoldClient(http=http).price_history(make_market("c1"), 250, 350)
    assert pts == [PricePoint(200, 0.2), PricePoint(300, 0.3)]
    assert http.calls[0][1]["contractId"] == "c1"


def test_price_history_without_prior_point_in_range():
    bets = [bet("a", 100_000, 0.1), bet("b", 200_000, 0.2)]
    http = FakeHttp(pages_handler([bets]))
    pts = ManifoldClient(http=http).price_history(make_market("c1"), 50, 150)
    assert pts == [PricePoint(100, 0.1)]


# ── book ──────────────────────────────────────────────────────────────────

def test_synthetic_book_for_yes_and_no():
    c = client()
    m = make_market("m1", last_price=0.6)

    yes = c.book(m, "YES")
    assert yes.token_id == "m1:YES"
    assert yes.synthetic is True
    assert yes.best_bid == pytest.approx(0.59)
    assert yes.best_ask == pytest.approx(0.61)

    no = c.book(m, "NO")
    assert no.token_id == "m1:NO"
    assert no.best_bid == pytest.approx(0.39)
    assert no.best_ask == pytest.approx(0.41)


def test_synthetic_book_clips_to_bounds():
    c = client()
    low = c.book(make_market("m1", last_price=0.005), "YES")
    assert low.best_bid == pytest.approx(0.01)
    assert low.best_ask == pytest.approx(0.015)
    high = c.book(make_market("m1", last_price=0.995), "YES")
    assert high.best_bid == pytest.approx(0.985)
    assert high.best_ask == pytest.approx(0.99)


def test_book_without_price_raises():
    with pytest.raises(DataError):
        client().book(make_market("m1", last_price=None), "YES")


# ── list / get ────────────────────────────────────────────────────────────

def test_list_open_markets_params_and_drops_non_binary():
    handler_pages = [[raw_market(id="a"), raw_market(id="b", outcomeType="MULTIPLE_CHOICE")]]
    http = FakeHttp(pages_handler(handler_pages))
    markets = ManifoldClient(http=http).list_open_markets(limit=5000)
    assert [m.market_id for m in markets] == ["a"]
    path, params = http.calls[0]
    assert path == "search-markets"
    assert params == {
        "term": "",
        "filter": "open",
        "contractType": "BINARY",
        "sort": "24-hour-vol",
        "limit": 1000,
    }


def test_get_market_parses_single_market():
    http = FakeHttp(lambda path, params: raw_market(id="m9"))
    m = ManifoldClient(http=http).get_market("m9")
    assert m is not None and m.market_id == "m9"
    assert http.calls[0][0] == "market/m9"


# ── resolved_markets ──────────────────────────────────────────────────────

def bets_for(n: int, t0_s: int) -> List[Dict[str, Any]]:
    return [bet(f"{t0_s}-{i}", (t0_s + i) * 1000, 0.5 + i * 0.01) for i in range(n)]


def scripted_handler(search_pages: List[Any], bets_by_contract: Dict[str, List[Any]]):
    it = iter(search_pages)

    def handler(path: str, params: dict) -> Any:
        if path == "search-markets":
            return next(it, [])
        if path == "bets":
            return bets_by_contract.get(params["contractId"], [])
        raise AssertionError(f"unerwarteter Pfad: {path}")

    return handler


def test_resolved_markets_filters_and_pages_with_before_time():
    page1 = [
        resolved_raw("A", 5_000_000, "YES", bettors=50, volume=2000),  # behalten
        resolved_raw("B", 4_900_000, "NO", bettors=10, volume=2000),   # zu wenig Trader
        resolved_raw("C", 4_800_000, "MKT", bettors=50, volume=2000),  # nicht YES/NO
        resolved_raw("D", 4_700_000, "YES", bettors=50, volume=500),   # zu wenig Volumen
        resolved_raw("E", 4_000_000, "NO", bettors=50, volume=2000),   # behalten, aber 4 Punkte
    ]
    page2 = [resolved_raw("F", 3_000_000, "YES")]
    bets = {"A": bets_for(5, 1000), "E": bets_for(4, 1000), "F": bets_for(5, 1000)}

    http = FakeHttp(scripted_handler([page1, page2], bets))
    result = ManifoldClient(http=http).resolved_markets(limit=3)

    assert [m.market_id for m, _ in result] == ["A", "F"]
    assert result[0][0].outcome == 1
    assert all(len(h) >= 5 for _, h in result)

    searches = [params for path, params in http.calls if path == "search-markets"]
    assert len(searches) == 2
    assert "beforeTime" not in searches[0]
    assert searches[0]["filter"] == "resolved"
    assert searches[0]["sort"] == "newest"
    assert searches[1]["beforeTime"] == 4_000_000


def test_resolved_markets_before_ms_sets_first_cursor():
    http = FakeHttp(scripted_handler([], {}))
    result = ManifoldClient(http=http).resolved_markets(limit=5, before_ms=9_999)
    assert result == []
    assert http.calls[0][1]["beforeTime"] == 9_999
