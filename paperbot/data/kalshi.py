"""
Kalshi-Datenquelle (öffentliche Marktdaten-API, nur lesend, ohne Login).

- Märkte: /markets (laufend und kürzlich abgerechnet), /historical/markets
  (vor dem Archiv-Stichtag abgerechnet). Beide werden abgefragt.
- Preise: Kerzen mit Geld- und Briefkurs je Periode (/markets/candlesticks,
  mehrere Märkte pro Abruf). Ein Preispunkt liegt am ENDE der Periode.
- Orderbuch: /markets/{ticker}/orderbook. Kalshi führt nur Kaufgebote für YES
  und NO; wer YES kauft, nimmt ein NO-Gebot zum Preis 1 − p (und umgekehrt).

Keine Orders, keine Schlüssel, keine Konto-Endpunkte.
"""
from __future__ import annotations

import hashlib
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from paperbot.data.base import DataError
from paperbot.models import Book, BookLevel, Market, PricePoint

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

DAY = 86_400
HOURLY_MAX_DAYS = 14            # bis 14 Tage Laufzeit Stundenkerzen, sonst Tageskerzen
MAX_CANDLES_PER_CALL = 5_000    # Grenze der API je Abruf
MAX_VALID_SPREAD = 0.5          # breiter = kein echter Kurs (z. B. 0 Geld / 1 Brief)
# "closed" heißt nur: Handel beendet, Ergebnis noch offen. Abgerechnet wird erst danach.
CLOSED_STATUSES = {"determined", "settled", "finalized"}

# Spezialisierung: Tageshöchsttemperatur (siehe docs/HYPOTHESEN.md, H8)
WEATHER_SERIES: Tuple[str, ...] = ("KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHLAX",
                                   "KXHIGHAUS", "KXHIGHDEN", "KXHIGHPHIL")
WEATHER_START = date(2022, 6, 1)

# Breite Stichprobe für H5–H7 (Regeln in docs/HYPOTHESEN.md, Kalshi-Runde)
BROAD_CATEGORIES: Tuple[str, ...] = (
    "Politics", "Elections", "Economics", "Financials", "Crypto", "Climate and Weather",
    "Sports", "Entertainment", "Commodities", "Companies", "Science and Technology",
    "World", "Mentions",
)
BROAD_PER_SERIES = 20
BROAD_PER_CATEGORY = 400
BROAD_MAX_SERIES = 150
BROAD_MIN_VOLUME = 1_000.0
BROAD_MIN_DAYS = 2.0


# ── Parsen ───────────────────────────────────────────────────────────────────

def _dollars(raw: dict, key: str) -> Optional[float]:
    """Preis in Dollar aus `<key>_dollars` (String) oder älterem `<key>` (int = Cent)."""
    v = raw.get(f"{key}_dollars")
    if v not in (None, ""):
        return float(v)
    v = raw.get(key)
    if v in (None, ""):
        return None
    if isinstance(v, int) and not isinstance(v, bool):
        return v / 100.0
    return float(v)


def _number(raw: dict, *keys: str) -> float:
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return float(v)
    return 0.0


def _parse_ts(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(math.floor(dt.timestamp()))


def _strike(v: Any) -> Optional[float]:
    return None if v in (None, "") else float(v)


def quote_mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """Mitte aus Geld/Brief, nur wenn beides ein echter Kurs ist."""
    if bid is None or ask is None:
        return None
    if not (0.0 <= bid < ask <= 1.0) or ask - bid > MAX_VALID_SPREAD:
        return None
    return (bid + ask) / 2.0


def series_of(event_ticker: str) -> str:
    return event_ticker.split("-")[0]


def event_date(event_ticker: str) -> Optional[date]:
    """Datum aus Event-Tickern wie KXHIGHNY-26AUG26 oder HIGHNY-21AUG06. Sonst None."""
    parts = event_ticker.split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None


def _parse(raw: dict, category: str, series: str) -> Optional[Market]:
    if raw.get("market_type", "binary") != "binary":
        return None
    ticker = str(raw["ticker"])
    event = str(raw.get("event_ticker") or "")
    status = str(raw.get("status") or "").lower()
    closed = status in CLOSED_STATUSES
    result = str(raw.get("result") or "").lower()
    outcome = {"yes": 1, "no": 0}.get(result) if closed else None
    bid, ask = _dollars(raw, "yes_bid"), _dollars(raw, "yes_ask")
    last = quote_mid(bid, ask)
    if last is None:
        last = _dollars(raw, "last_price")
    title = str(raw.get("title") or "")
    sub = str(raw.get("yes_sub_title") or "")
    created = _parse_ts(raw.get("open_time") or raw.get("created_time"))
    close = _parse_ts(raw.get("close_time"))
    settled = _parse_ts(raw.get("settlement_ts")) if closed else None
    series = series or series_of(event)
    oi = _number(raw, "open_interest_fp", "open_interest")
    return Market(
        source="kalshi",
        market_id=ticker,
        question=f"{title} — {sub}" if sub else title,
        slug=ticker,
        category=category.lower(),
        url=f"https://kalshi.com/markets/{series.lower()}",
        created_ts=created,
        end_ts=close,
        # Märkte mit vorzeitigem Schluss: close_time im Archiv kann der echte Schluss sein.
        end_known_in_advance=not bool(raw.get("can_close_early", False)),
        volume=_number(raw, "volume_fp", "volume"),
        # Kalshi liefert keine Liquiditätszahl mehr; offene Kontrakte (je 1 $ Nennwert) als Ersatz.
        liquidity=_number(raw, "liquidity_dollars") or oi,
        yes_token_id=ticker,
        no_token_id=ticker,
        active=status in ("active", "open"),
        accepting_orders=status in ("active", "open"),
        event_id=event,
        series=series,
        strike_type=str(raw.get("strike_type") or ""),
        floor_strike=_strike(raw.get("floor_strike")),
        cap_strike=_strike(raw.get("cap_strike")),
        closed=closed,
        outcome=outcome,
        resolved_ts=(settled or close) if closed else None,
        last_price=last,
    )


def parse_market(raw: dict, category: str = "", series: str = "") -> Optional[Market]:
    """Rohen Kalshi-Markt in Market wandeln. Nicht binär oder defekt -> None (wirft nie)."""
    try:
        return _parse(raw, category, series)
    except Exception:
        return None


def parse_candles(rows: Any) -> List[PricePoint]:
    """Kerzen -> Preispunkte (Mitte aus Geld/Brief am Periodenende). Ohne echten Kurs: weg."""
    if not isinstance(rows, list):
        raise DataError("Kerzen: Liste erwartet")
    out: List[PricePoint] = []
    for c in rows:
        try:
            t = int(c["end_period_ts"])
            bid = _dollars(c.get("yes_bid") or {}, "close")
            ask = _dollars(c.get("yes_ask") or {}, "close")
        except (KeyError, TypeError, ValueError) as exc:
            raise DataError(f"ungültige Kerze: {c!r}"[:200]) from exc
        mid = quote_mid(bid, ask)
        if mid is not None:
            out.append(PricePoint(t, mid, bid, ask))
    out.sort(key=lambda p: p.t)
    return out


def _book_levels(rows: Any) -> List[Tuple[float, float]]:
    """[[preis, menge], …] in Dollar (neues Format) oder Cent (altes Format)."""
    out = []
    for row in rows or []:
        try:
            price, size = row[0], float(row[1])
            price = price / 100.0 if isinstance(price, int) else float(price)
        except (IndexError, TypeError, ValueError) as exc:
            raise DataError(f"ungültige Orderbuch-Stufe: {row!r}") from exc
        if 0.0 < price < 1.0 and size > 0:
            out.append((price, size))
    return out


def parse_orderbook(raw: Any, ticker: str, side: str) -> Book:
    if not isinstance(raw, dict):
        raise DataError("orderbook: Objekt erwartet")
    ob = raw.get("orderbook_fp") or raw.get("orderbook") or {}
    yes = _book_levels(ob.get("yes_dollars") if "yes_dollars" in ob else ob.get("yes"))
    no = _book_levels(ob.get("no_dollars") if "no_dollars" in ob else ob.get("no"))
    own, other = (yes, no) if side == "YES" else (no, yes)
    bids = sorted((BookLevel(p, s) for p, s in own), key=lambda lv: lv.price, reverse=True)
    asks = sorted((BookLevel(round(1.0 - p, 6), s) for p, s in other), key=lambda lv: lv.price)
    return Book(token_id=f"{ticker}:{side}", bids=tuple(bids), asks=tuple(asks))


def _stable_order(items: Iterable[str]) -> List[str]:
    """Feste, vorher festgelegte Reihenfolge (SHA-256), unabhängig von Ergebnissen."""
    return sorted(items, key=lambda s: hashlib.sha256(s.encode()).hexdigest())


# ── Client ───────────────────────────────────────────────────────────────────

class KalshiClient:
    source = "kalshi"

    def __init__(self, http: Any = None, series: Sequence[str] = WEATHER_SERIES) -> None:
        if http is None:
            from paperbot.data.http import HttpClient
            http = HttpClient(BASE_URL, min_interval_s=0.08, timeout_s=30.0, retries=6)
        self.http = http
        self.series = tuple(series)       # Serien für den Live-Betrieb (Spezialisierung)
        self.skipped = 0
        self._categories: Optional[Dict[str, str]] = None

    # ── Serien ───────────────────────────────────────────────────────────

    def categories(self) -> Dict[str, str]:
        """Serien-Ticker -> Kategorie (ein Abruf, im Speicher gehalten)."""
        if self._categories is None:
            resp = self.http.get_json("series")
            rows = resp.get("series") if isinstance(resp, dict) else None
            if not isinstance(rows, list):
                raise DataError("series: Liste erwartet")
            self._categories = {str(s.get("ticker")): str(s.get("category") or "") for s in rows}
        return self._categories

    def _category(self, series: str) -> str:
        try:
            return self.categories().get(series, "")
        except DataError:
            return ""

    # ── Live-Schnittstelle (MarketDataClient) ────────────────────────────

    def list_open_markets(self, limit: int = 200) -> List[Market]:
        out: List[Market] = []
        for s in self.series:
            resp = self.http.get_json("markets", params={"series_ticker": s, "status": "open",
                                                         "limit": 200})
            for raw in _rows(resp, "markets"):
                m = parse_market(raw, self._category(s), s)
                if m is None:
                    self.skipped += 1
                elif m.active and not m.closed:
                    out.append(m)
        out.sort(key=lambda m: m.volume, reverse=True)
        return out[:limit]

    def get_market(self, market_id: str) -> Optional[Market]:
        from paperbot.data.http import NotFoundError
        try:
            resp = self.http.get_json(f"markets/{market_id}")
        except NotFoundError:
            resp = self.http.get_json(f"historical/markets/{market_id}")
        raw = resp.get("market") if isinstance(resp, dict) else None
        if not isinstance(raw, dict):
            raise DataError("market: Objekt erwartet")
        s = series_of(str(raw.get("event_ticker") or market_id))
        m = parse_market(raw, self._category(s))
        if m is None:
            self.skipped += 1
        return m

    def price_history(self, market: Market, start_ts: int, end_ts: int) -> List[PricePoint]:
        got = self.candles([market.market_id], start_ts, end_ts, 60)
        return got.get(market.market_id, [])

    def book(self, market: Market, side: str) -> Optional[Book]:
        raw = self.http.get_json(f"markets/{market.market_id}/orderbook")
        return parse_orderbook(raw, market.market_id, side)

    # ── Kerzen ───────────────────────────────────────────────────────────

    def candles(self, tickers: Sequence[str], start_ts: int, end_ts: int,
                period_min: int) -> Dict[str, List[PricePoint]]:
        """Kerzen für mehrere Märkte mit gemeinsamem Zeitfenster (Batch-Endpunkt)."""
        per_market = max(1, (end_ts - start_ts) // (period_min * 60) + 1)
        if per_market > MAX_CANDLES_PER_CALL:
            raise DataError(f"Zeitfenster zu lang für Periode {period_min} min")
        chunk = max(1, min(50, MAX_CANDLES_PER_CALL // per_market))
        out: Dict[str, List[PricePoint]] = {}
        for i in range(0, len(tickers), chunk):
            part = list(tickers[i:i + chunk])
            resp = self.http.get_json("markets/candlesticks", params={
                "market_tickers": ",".join(part), "start_ts": int(start_ts),
                "end_ts": int(end_ts), "period_interval": int(period_min)})
            for row in _rows(resp, "markets"):
                tk = str(row.get("market_ticker") or "")
                if tk:
                    out[tk] = parse_candles(row.get("candlesticks") or [])
        return out

    def archived_candles(self, ticker: str, start_ts: int, end_ts: int,
                         period_min: int) -> List[PricePoint]:
        """Kerzen eines archivierten Marktes (/historical/markets/{ticker}/candlesticks).
        Unbekannt oder defekt -> leere Liste (der Markt fällt dann weg)."""
        try:
            resp = self.http.get_json(f"historical/markets/{ticker}/candlesticks", params={
                "start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": int(period_min)})
            return parse_candles(_rows(resp, "candlesticks"))
        except DataError:
            return []

    # ── Historische Märkte ───────────────────────────────────────────────

    def settled_in_series(self, series: str, max_markets: int,
                          page_size: int = 200) -> List[dict]:
        """Abgerechnete Märkte einer Serie, neueste zuerst: erst laufende API, dann Archiv."""
        rows: List[dict] = []
        for path, extra in (("markets", {"status": "settled"}), ("historical/markets", {})):
            cursor = None
            while len(rows) < max_markets:
                params = {"series_ticker": series, "limit": page_size, **extra}
                if cursor:
                    params["cursor"] = cursor
                resp = self.http.get_json(path, params=params)
                page = _rows(resp, "markets")
                rows.extend(page)
                cursor = resp.get("cursor") if isinstance(resp, dict) else None
                if not cursor or not page:
                    break
        seen, uniq = set(), []
        for r in rows:
            tk = r.get("ticker")
            if tk and tk not in seen:
                seen.add(tk)
                uniq.append(r)
        return uniq[:max_markets]

    def _with_history(self, markets: List[Market]) -> List[Tuple[Market, List[PricePoint]]]:
        """Kerzen je Event holen (gemeinsames Fenster), Märkte ohne Preise fallen weg."""
        by_event: Dict[Tuple[str, int], List[Market]] = defaultdict(list)
        for m in markets:
            days = ((m.end_ts or 0) - (m.created_ts or 0)) / DAY
            period = 60 if days <= HOURLY_MAX_DAYS else 1440
            by_event[(m.event_id or m.market_id, period)].append(m)
        out: List[Tuple[Market, List[PricePoint]]] = []
        for k, ((_, period), group) in enumerate(sorted(by_event.items())):
            start = min(m.created_ts for m in group)
            end = max(m.resolved_ts or m.end_ts for m in group) + period * 60
            try:
                hist = self.candles([m.market_id for m in group], start, end, period)
            except DataError as exc:
                print(f"[kalshi] Kerzen fehlgeschlagen für {group[0].event_id}: {exc}", file=sys.stderr)
                self.skipped += len(group)
                continue
            for m in group:
                h = hist.get(m.market_id) or []
                if len(h) < 2:
                    # Der Batch-Endpunkt kennt nur Märkte nach dem Archiv-Stichtag.
                    # Ältere Märkte einzeln aus dem Archiv holen (Lauf 2026-10-27 fehlte das:
                    # nur 924 von ~15.300 Wettermärkten hatten Kerzen).
                    h = self.archived_candles(m.market_id, start, end, period)
                if len(h) >= 2:
                    out.append((m, h))
                else:
                    self.skipped += 1
            if (k + 1) % 100 == 0:
                print(f"[kalshi] Kerzen für {k + 1}/{len(by_event)} Events, {len(out)} Märkte",
                      file=sys.stderr)
        return out

    def resolved_markets(self, limit: int = 5_000) -> List[Tuple[Market, List[PricePoint]]]:
        """Breite Stichprobe für H5–H7 nach der vorab festgelegten Regel."""
        cats = self.categories()
        by_cat: Dict[str, List[str]] = defaultdict(list)
        for s, c in cats.items():
            by_cat[c].append(s)
        chosen: List[Market] = []
        for cat in BROAD_CATEGORIES:
            got: List[Market] = []
            for s in _stable_order(by_cat.get(cat, []))[:BROAD_MAX_SERIES]:
                if len(got) >= BROAD_PER_CATEGORY:
                    break
                try:
                    rows = self.settled_in_series(s, max_markets=200)
                except DataError as exc:
                    print(f"[kalshi] Serie {s}: {exc}", file=sys.stderr)
                    continue
                keep = []
                for raw in rows:
                    m = parse_market(raw, cat, s)
                    if (m is None or m.outcome not in (0, 1) or m.volume < BROAD_MIN_VOLUME
                            or m.created_ts is None or m.end_ts is None
                            or (m.end_ts - m.created_ts) / DAY < BROAD_MIN_DAYS):
                        continue
                    keep.append(m)
                got.extend(_spread_pick(keep, BROAD_PER_SERIES)[:BROAD_PER_CATEGORY - len(got)])
            print(f"[kalshi] {cat}: {len(got)} Märkte", file=sys.stderr)
            chosen.extend(got)
        return self._with_history(chosen[:limit])

    def resolved_weather_markets(self, limit: int = 30_000,
                                 start: date = WEATHER_START) -> List[Tuple[Market, List[PricePoint]]]:
        """H8: Temperatur-Märkte ab `start`, nur Tage mit Tag-im-Jahr durch 3 teilbar."""
        chosen: List[Market] = []
        for s in WEATHER_SERIES:
            rows = self.settled_in_series(s, max_markets=50_000, page_size=1000)
            n = 0
            for raw in rows:
                d = event_date(str(raw.get("event_ticker") or ""))
                if d is None or d < start or d.timetuple().tm_yday % 3 != 0:
                    continue
                m = parse_market(raw, "Climate and Weather", s)
                if m is None or m.outcome not in (0, 1) or m.created_ts is None or m.end_ts is None:
                    continue
                chosen.append(m)
                n += 1
            print(f"[kalshi] {s}: {n} Märkte ausgewählt", file=sys.stderr)
        return self._with_history(chosen[:limit])


def _rows(resp: Any, key: str) -> list:
    rows = resp.get(key) if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        raise DataError(f"{key}: Liste erwartet")
    return rows


def _spread_pick(items: List[Market], k: int) -> List[Market]:
    """Höchstens k Märkte, gleichmäßig über die (zeitlich sortierte) Liste verteilt."""
    if len(items) <= k:
        return items
    items = sorted(items, key=lambda m: (m.created_ts or 0, m.market_id))
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]
