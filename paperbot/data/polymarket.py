"""
Polymarket-Datenquelle (öffentlich, nur lesend).

Gamma-API liefert Märkte, CLOB-API liefert Preishistorie und Orderbücher.
Keine Orders, keine Signaturen, keine Schlüssel.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from paperbot.data.base import DataError
from paperbot.models import Book, BookLevel, Market, PricePoint

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

DAY = 86400
HISTORY_LOOKBACK_S = 90 * DAY   # Fallback-Startfenster, wenn createdAt und startDate fehlen
RESOLVED_HIGH = 0.99            # letzter Preis >= 0.99 nach Schließung -> YES gewonnen
RESOLVED_LOW = 0.01             # letzter Preis <= 0.01 nach Schließung -> NO gewonnen


def _as_list(value: Any) -> list:
    """Liste aus echter Liste oder aus einem JSON-kodierten String."""
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("Liste erwartet")
    return value


def _parse_ts(value: Any) -> Optional[int]:
    """ISO-8601-String (auch 'Z' oder nur Datum) -> Unix-Sekunden UTC. Leer -> None."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Zeitstempel muss ein String sein")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(math.floor(dt.timestamp()))


def _token(value: Any) -> str:
    """Token-ID als String. Große Zahlen bleiben exakt erhalten."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Token-ID ungültig")
    s = str(value).strip()
    if not s:
        raise ValueError("Token-ID leer")
    return s


def _category(raw: dict) -> str:
    cat = raw.get("category")
    events = raw.get("events")
    if (not cat and isinstance(events, list) and events
            and all(isinstance(e, dict) for e in events)):
        cat = events[0].get("category")
    return str(cat or "").lower()


def _parse(raw: dict) -> Optional[Market]:
    outcomes = [str(o).lower() for o in _as_list(raw["outcomes"])]
    if outcomes != ["yes", "no"]:
        return None

    prices = _as_list(raw["outcomePrices"])
    last = float(prices[0])
    if not (0.0 <= last <= 1.0):
        raise ValueError("Preis außerhalb 0..1")

    tokens = _as_list(raw["clobTokenIds"])
    if len(tokens) < 2:
        raise ValueError("zwei Token-IDs erwartet")
    yes_token, no_token = _token(tokens[0]), _token(tokens[1])

    if raw.get("id") in (None, ""):
        raise ValueError("id fehlt")

    slug = str(raw.get("slug") or "")
    closed = bool(raw.get("closed", False))

    outcome: Optional[int] = None
    resolved_ts: Optional[int] = None
    if closed:
        if last >= RESOLVED_HIGH:
            outcome = 1
        elif last <= RESOLVED_LOW:
            outcome = 0
        resolved_ts = _parse_ts(raw.get("closedTime"))

    return Market(
        source="polymarket",
        market_id=str(raw["id"]),
        question=str(raw.get("question") or ""),
        slug=slug,
        category=_category(raw),
        url="https://polymarket.com/event/" + slug,
        created_ts=_parse_ts(raw.get("createdAt") or raw.get("startDate")),
        end_ts=_parse_ts(raw.get("endDate")),
        end_known_in_advance=True,
        volume=float(raw.get("volumeNum") or raw.get("volume") or 0),
        liquidity=float(raw.get("liquidityNum") or raw.get("liquidity") or 0),
        yes_token_id=yes_token,
        no_token_id=no_token,
        active=bool(raw.get("active", True)),
        accepting_orders=bool(raw.get("acceptingOrders", True)),
        closed=closed,
        outcome=outcome,
        resolved_ts=resolved_ts,
        last_price=last,
    )


def parse_market(raw: dict) -> Optional[Market]:
    """Rohen Gamma-Markt in Market wandeln. Nicht binär oder defekt -> None (wirft nie)."""
    try:
        return _parse(raw)
    except Exception:
        return None


def _levels(rows: Any) -> List[BookLevel]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise DataError("Orderbuch-Stufen müssen eine Liste sein")
    out = []
    for row in rows:
        try:
            out.append(BookLevel(float(row["price"]), float(row["size"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError(f"ungültige Orderbuch-Stufe: {row!r}") from exc
    return out


class PolymarketClient:
    source = "polymarket"

    def __init__(self, gamma: Any = None, clob: Any = None) -> None:
        if gamma is None or clob is None:
            from paperbot.data.http import HttpClient  # lazy: Tests injizieren Fakes
        if gamma is None:
            gamma = HttpClient(GAMMA_URL)
        if clob is None:
            clob = HttpClient(CLOB_URL, min_interval_s=0.7)
        self.gamma = gamma
        self.clob = clob
        self.skipped = 0

    @staticmethod
    def _rows(resp: Any) -> list:
        if not isinstance(resp, list):
            raise DataError("Liste erwartet")
        return resp

    def _parse_or_skip(self, raw: Any) -> Optional[Market]:
        m = parse_market(raw)
        if m is None:
            self.skipped += 1
        return m

    def list_open_markets(self, limit: int = 200) -> List[Market]:
        out: List[Market] = []
        offset = 0
        while len(out) < limit:
            page = min(100, limit - len(out))
            rows = self._rows(self.gamma.get_json("markets", params={
                "active": True,
                "closed": False,
                "limit": page,
                "offset": offset,
                "order": "volume24hr",
                "ascending": False,
            }))
            for raw in rows:
                m = self._parse_or_skip(raw)
                if m is None:
                    continue
                if m.active and m.accepting_orders and not m.closed:
                    out.append(m)
                    if len(out) >= limit:
                        break
            if len(rows) < page:
                break
            offset += page
        return out

    def get_market(self, market_id: str) -> Optional[Market]:
        raw = self.gamma.get_json(f"markets/{market_id}")
        if not isinstance(raw, dict):
            raise DataError("Objekt erwartet")
        return self._parse_or_skip(raw)

    def price_history(self, market: Market, start_ts: int, end_ts: int,
                      fidelity: int = 60) -> List[PricePoint]:
        if not market.yes_token_id:
            raise DataError(f"kein YES-Token für Markt {market.market_id}")
        resp = self.clob.get_json("prices-history", params={
            "market": market.yes_token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "fidelity": fidelity,
        })
        if not isinstance(resp, dict) or not isinstance(resp.get("history", []), list):
            raise DataError("prices-history: unerwartete Antwort")
        points: List[PricePoint] = []
        for item in resp.get("history", []):
            try:
                t, p = int(item["t"]), float(item["p"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DataError(f"ungültiger Preispunkt: {item!r}") from exc
            if 0.0 <= p <= 1.0:
                points.append(PricePoint(t, p))
        points.sort(key=lambda pt: pt.t)
        return points

    def book(self, market: Market, side: str) -> Optional[Book]:
        token = market.token_for(side)
        if not token:
            return None
        raw = self.clob.get_json("book", params={"token_id": token})
        if not isinstance(raw, dict):
            raise DataError("book: Objekt erwartet")
        bids = sorted(_levels(raw.get("bids")), key=lambda lv: lv.price, reverse=True)
        asks = sorted(_levels(raw.get("asks")), key=lambda lv: lv.price)
        ts_raw = raw.get("timestamp")
        ts: Optional[int] = None
        if ts_raw not in (None, ""):
            try:
                ts = int(ts_raw) // 1000
            except (TypeError, ValueError) as exc:
                raise DataError(f"ungültiger Zeitstempel: {ts_raw!r}") from exc
        return Book(token_id=token, bids=tuple(bids), asks=tuple(asks), ts=ts)

    def resolved_markets(self, limit: int, min_volume: float = 10_000.0,
                         page_size: int = 100,
                         fidelity: int = 720) -> List[Tuple[Market, List[PricePoint]]]:
        if page_size < 1:
            raise ValueError("page_size muss >= 1 sein")
        out: List[Tuple[Market, List[PricePoint]]] = []
        offset = 0
        while len(out) < limit:
            rows = self._rows(self.gamma.get_json("markets", params={
                "closed": True,
                "limit": page_size,
                "offset": offset,
                "order": "id",
                "ascending": False,
            }))
            for raw in rows:
                m = self._parse_or_skip(raw)
                if m is None or m.outcome not in (0, 1) or m.volume < min_volume:
                    continue
                start = m.created_ts
                if start is None and m.end_ts is not None:
                    start = m.end_ts - HISTORY_LOOKBACK_S
                base_end = m.resolved_ts if m.resolved_ts is not None else m.end_ts
                if start is None or base_end is None:
                    self.skipped += 1
                    continue
                try:
                    hist = self.price_history(m, start, base_end + DAY, fidelity=fidelity)
                except DataError:
                    self.skipped += 1
                    continue
                if len(hist) < 3:
                    self.skipped += 1
                    continue
                out.append((m, hist))
                if len(out) % 25 == 0:
                    print(f"[polymarket] {len(out)}/{limit} aufgelöste Märkte geladen",
                          file=sys.stderr)
                if len(out) >= limit:
                    break
            if len(rows) < page_size:
                break
            offset += page_size
        return out
