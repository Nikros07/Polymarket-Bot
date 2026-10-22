"""
Manifold Markets als erreichbarer Ersatz (Spielgeld, nur lesend).

Es werden keine Orders platziert. Der Preis ist ein synthetischer AMM-Kurs.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paperbot.data.base import DataError
from paperbot.models import Book, BookLevel, Market, PricePoint, side_price

BASE_URL = "https://api.manifold.markets/v0"
HALF_SPREAD = 0.01
PAGE_SIZE = 1000
MIN_HISTORY_POINTS = 5


def _ts(ms: Any) -> Optional[int]:
    """Millisekunden -> Sekunden; None bleibt None."""
    return None if ms is None else int(ms) // 1000


def _clip(p: Any) -> float:
    return min(1.0, max(0.0, float(p)))


def parse_market(raw: Dict[str, Any]) -> Optional[Market]:
    """Rohdaten eines Manifold-Marktes in `Market`. None bei Nicht-Binär oder Parsefehler."""
    if not isinstance(raw, dict) or raw.get("outcomeType") != "BINARY":
        return None
    try:
        slug = str(raw.get("slug") or "")
        url = raw.get("url") or f"https://manifold.markets/{raw['creatorUsername']}/{slug}"
        groups = raw.get("groupSlugs") or []
        probability = raw.get("probability")
        res_prob = raw.get("resolutionProbability") if raw.get("resolution") == "MKT" else None
        return Market(
            source="manifold",
            market_id=str(raw["id"]),
            question=str(raw["question"]),
            slug=slug,
            category=str(groups[0]) if groups else "",
            url=str(url),
            created_ts=_ts(raw.get("createdTime")),
            end_ts=_ts(raw.get("closeTime")),
            end_known_in_advance=False,  # closeTime wird oft erst bei Auflösung gesetzt
            volume=float(raw.get("volume") or 0),
            liquidity=float(raw.get("totalLiquidity") or 0),
            closed=bool(raw.get("isResolved")),
            outcome={"YES": 1, "NO": 0}.get(raw.get("resolution")),
            resolved_ts=_ts(raw.get("resolutionTime")),
            last_price=float(probability) if probability is not None else None,
            resolution_price=_clip(res_prob) if res_prob is not None else None,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def bets_to_history(bets: List[Dict[str, Any]]) -> List[PricePoint]:
    """Wetten in einen YES-Preisverlauf (ein Punkt pro Sekunde, aufsteigend) umwandeln."""
    kept = sorted(
        (b for b in bets if not b.get("isCancelled") and b.get("probAfter") is not None),
        key=lambda b: b["createdTime"],
    )
    points: List[PricePoint] = []
    if kept and kept[0].get("probBefore") is not None:
        first = kept[0]
        points.append(PricePoint(first["createdTime"] // 1000 - 1, _clip(first["probBefore"])))
    for b in kept:
        points.append(PricePoint(b["createdTime"] // 1000, _clip(b["probAfter"])))

    out: List[PricePoint] = []
    for pt in points:
        if out and out[-1].t == pt.t:
            out[-1] = pt  # gleiche Sekunde: letzter Wert gewinnt
        else:
            out.append(pt)
    return out


class ManifoldClient:
    source = "manifold"

    def __init__(self, http: Any = None, cache_dir: Optional[Path] = None) -> None:
        if http is None:
            from paperbot.data.http import HttpClient  # nur ohne injizierten Client

            http = HttpClient(BASE_URL, min_interval_s=0.15)
        self._http = http
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None

    def list_open_markets(self, limit: int = 200) -> List[Market]:
        raw = self._http.get_json(
            "search-markets",
            {
                "term": "",
                "filter": "open",
                "contractType": "BINARY",
                "sort": "24-hour-vol",
                "limit": min(limit, 1000),
            },
        )
        parsed = (parse_market(r) for r in raw or [])
        return [m for m in parsed if m is not None]

    def get_market(self, market_id: str) -> Optional[Market]:
        return parse_market(self._http.get_json(f"market/{market_id}", {}))

    def fetch_bets(self, contract_id: str, max_bets: int = 20_000) -> List[Dict[str, Any]]:
        cache_file = self._cache_file(contract_id)
        if cache_file is not None and cache_file.exists():
            with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
                return json.load(fh)

        bets: List[Dict[str, Any]] = []
        seen: set = set()
        after: Optional[int] = None
        while len(bets) < max_bets:
            params: Dict[str, Any] = {"contractId": contract_id, "limit": PAGE_SIZE, "order": "asc"}
            if after is not None:
                params["afterTime"] = after
            page = self._http.get_json("bets", params) or []
            new = 0
            for b in page:
                if b.get("id") in seen:
                    continue
                seen.add(b.get("id"))
                bets.append(b)
                new += 1
            # new == 0: Schutz gegen Endlosschleife, falls die API nur Duplikate liefert
            if len(page) < PAGE_SIZE or new == 0:
                break
            after = page[-1]["createdTime"]

        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache_file, "wt", encoding="utf-8") as fh:
                json.dump(bets, fh)
        return bets

    def price_history(self, market: Market, start_ts: int, end_ts: int) -> List[PricePoint]:
        points = bets_to_history(self.fetch_bets(market.market_id))
        before = [p for p in points if p.t < start_ts]
        inside = [p for p in points if start_ts <= p.t <= end_ts]
        return ([before[-1]] if before else []) + inside

    def book(self, market: Market, side: str) -> Book:
        if market.last_price is None:
            raise DataError(f"kein letzter Preis für Markt {market.market_id}")
        s = side_price(market.last_price, side)
        return Book(
            token_id=f"{market.market_id}:{side}",
            bids=(BookLevel(max(0.01, s - HALF_SPREAD), 1e6),),
            asks=(BookLevel(min(0.99, s + HALF_SPREAD), 1e6),),
            synthetic=True,
        )

    def resolved_markets(
        self,
        limit: int,
        min_bettors: int = 30,
        min_volume: float = 1_000.0,
        before_ms: Optional[int] = None,
    ) -> List[Tuple[Market, List[PricePoint]]]:
        candidates: List[Market] = []
        cursor = before_ms
        while len(candidates) < limit:
            params: Dict[str, Any] = {
                "term": "",
                "filter": "resolved",
                "contractType": "BINARY",
                "sort": "newest",
                "limit": PAGE_SIZE,
            }
            if cursor is not None:
                params["beforeTime"] = cursor
            page = self._http.get_json("search-markets", params) or []
            if not page:
                break
            for raw in page:
                if len(candidates) >= limit:
                    break
                if (raw.get("uniqueBettorCount") or 0) < min_bettors:
                    continue
                if float(raw.get("volume") or 0) < min_volume:
                    continue
                if raw.get("resolution") not in ("YES", "NO"):
                    continue
                market = parse_market(raw)
                if market is not None:
                    candidates.append(market)
            new_cursor = page[-1].get("createdTime")
            if new_cursor is None or new_cursor == cursor:
                break
            cursor = new_cursor

        result: List[Tuple[Market, List[PricePoint]]] = []
        for i, market in enumerate(candidates, 1):
            if i % 50 == 0:
                print(f"resolved_markets: {i}/{len(candidates)}", file=sys.stderr)
            history = bets_to_history(self.fetch_bets(market.market_id))
            if len(history) < MIN_HISTORY_POINTS:
                continue
            result.append((market, history))
        return result

    def _cache_file(self, contract_id: str) -> Optional[Path]:
        if self._cache_dir is None:
            return None
        return self._cache_dir / "manifold" / f"{contract_id}.json.gz"
