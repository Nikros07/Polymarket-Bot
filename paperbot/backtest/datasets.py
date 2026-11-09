"""
Historische Datensätze laden und als gzip-JSON zwischenspeichern.

Ein Datensatz ist eine Liste (Market, [PricePoint, …]) aufgelöster Märkte.
Der Zwischenspeicher liegt in data/paperbot/datasets/ (nicht im Git).
"""
from __future__ import annotations

import gzip
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Tuple

from paperbot.models import Market, PricePoint

Dataset = List[Tuple[Market, List[PricePoint]]]


def save_dataset(ds: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"market": asdict(m), "history": [_point_row(p) for p in h]} for m, h in ds]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(rows, f)
    tmp.replace(path)


def load_dataset(path: Path, bucket_s: int = 3_600) -> Optional[Dataset]:
    """bucket_s > 0: pro Zeitfenster nur den LETZTEN Punkt behalten (z. B. stündlich).
    Das verkleinert Manifold-Historien mit zehntausenden Wetten stark. Weil der letzte
    Punkt eines Fensters genommen wird, kann ein Wert höchstens früher sichtbar werden,
    als er im Rohdatensatz an derselben Rasterzeit stünde — nie später."""
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = json.load(f)
    out = []
    for r in rows:
        hist = [_point(row) for row in r["history"]]
        out.append((Market(**r["market"]), downsample(hist, bucket_s) if bucket_s else hist))
    return out


def _point_row(p: PricePoint) -> list:
    """[t, p] oder [t, p, bid, ask], wenn echte Kurse bekannt sind."""
    return [p.t, p.p] if p.bid is None or p.ask is None else [p.t, p.p, p.bid, p.ask]


def _point(row: list) -> PricePoint:
    if len(row) >= 4:
        return PricePoint(int(row[0]), float(row[1]), float(row[2]), float(row[3]))
    return PricePoint(int(row[0]), float(row[1]))


def downsample(hist: List[PricePoint], bucket_s: int) -> List[PricePoint]:
    """Letzter Punkt je Fenster, mit seinem echten Zeitstempel (kein Vorziehen in die Zukunft)."""
    out: List[PricePoint] = []
    for pt in hist:
        if out and out[-1].t // bucket_s == pt.t // bucket_s:
            out[-1] = pt
        else:
            out.append(pt)
    return out


def fetch_dataset(source: str, limit: int, cache_root: Path, refresh: bool = False) -> Dataset:
    path = cache_root / "datasets" / f"{source}_{limit}.json.gz"
    if not refresh:
        ds = load_dataset(path)
        if ds is not None:
            return ds
    if source == "manifold":
        from paperbot.data.manifold import ManifoldClient
        ds = ManifoldClient(cache_dir=cache_root / "cache").resolved_markets(limit)
    elif source == "polymarket":
        from paperbot.data.polymarket import PolymarketClient
        ds = PolymarketClient().resolved_markets(limit)
    elif source in ("kalshi", "kalshi_weather"):
        from paperbot.data.kalshi import KalshiClient
        client = KalshiClient()
        ds = (client.resolved_markets(limit) if source == "kalshi"
              else client.resolved_weather_markets(limit))
        save_quality(path, dict(client.stats), ds)
    elif source == "synthetic":
        from paperbot.backtest.synthetic import make_dataset
        ds = make_dataset(limit, bias=0.0)
    else:
        raise ValueError(f"unbekannte Quelle: {source}")
    save_dataset(ds, path)
    return ds


# ── Datenqualität ─────────────────────────────────────────────────────────────
# Lehre aus dem Kalshi-Lauf vom 2026-10-27: 14.400 von 15.300 Wettermärkten fielen
# still weg, der Bericht sah trotzdem normal aus. Deshalb liegt neben jedem
# Datensatz eine Qualitätsdatei, und der Backtest bricht bei zu großem Verlust ab.

MAX_DROP_SHARE = 0.20          # mehr ohne Preise verworfen → Abbruch
MAX_FETCH_ERROR_SHARE = 0.01   # Abruffehler (nicht 404) sind nie zufällig verteilt


def quality_path(dataset_path: Path) -> Path:
    return dataset_path.with_name(dataset_path.name.replace(".json.gz", "") + ".quality.json")


def save_quality(dataset_path: Path, stats: dict, ds: Dataset) -> dict:
    ts = sorted(m.created_ts for m, _ in ds if m.created_ts is not None)
    q = {**{str(k): int(v) for k, v in stats.items()},
         "erster_markt_ts": ts[0] if ts else None, "letzter_markt_ts": ts[-1] if ts else None}
    p = quality_path(dataset_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    return q


def load_quality(dataset_path: Path) -> Optional[dict]:
    p = quality_path(dataset_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def check_quality(q: Optional[dict], name: str, max_drop: float = MAX_DROP_SHARE) -> Optional[str]:
    """None = in Ordnung, sonst Fehlermeldung. Ohne Qualitätsdatei: Meldung (unbekannt ≠ gut)."""
    if q is None:
        return f"{name}: keine Qualitätsdatei – Datensatz mit --refresh neu laden"
    chosen = int(q.get("ausgewählt", 0))
    dropped = int(q.get("ohne Preise verworfen", 0))
    if chosen == 0:
        return f"{name}: keine Märkte ausgewählt"
    share = dropped / chosen
    if share > max_drop:
        return (f"{name}: {dropped} von {chosen} Märkten ohne Preise verworfen "
                f"({share:.0%} > {max_drop:.0%}). Stichprobe wäre verzerrt.")
    failed = int(q.get("Abruffehler", 0))
    if failed > MAX_FETCH_ERROR_SHARE * chosen:
        return (f"{name}: {failed} Abruffehler bei {chosen} Märkten (Drosselung/Netz). "
                "Fehlende Märkte wären zeitlich gehäuft. Neu laden.")
    if int(q.get("Serie fehlgeschlagen", 0)):
        return (f"{name}: {q['Serie fehlgeschlagen']} Serien nicht abrufbar; die vorab "
                "festgelegte Serienauswahl wäre verschoben. Neu laden.")
    return None
