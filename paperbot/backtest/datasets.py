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
    rows = [{"market": asdict(m), "history": [[p.t, p.p] for p in h]} for m, h in ds]
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
        hist = [PricePoint(int(t), float(p)) for t, p in r["history"]]
        out.append((Market(**r["market"]), downsample(hist, bucket_s) if bucket_s else hist))
    return out


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
    elif source == "synthetic":
        from paperbot.backtest.synthetic import make_dataset
        ds = make_dataset(limit, bias=0.0)
    else:
        raise ValueError(f"unbekannte Quelle: {source}")
    save_dataset(ds, path)
    return ds
