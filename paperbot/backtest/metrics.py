"""
Metriken für Kalibrierung, Rendite und Signifikanz im Backtest.

Konventionen:
- probs: Wahrscheinlichkeiten für YES im Bereich 0..1.
- outcomes: Ergebnisse 0 (NO) oder 1 (YES).
- Ungültige Eingaben lösen ValueError aus, nie stilles Raten.
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

ArrayLike = Union[Sequence[float], np.ndarray, pd.Series]


def _probs_and_outcomes(probs: ArrayLike, outcomes: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(probs, dtype=float).ravel()
    y = np.asarray(outcomes, dtype=float).ravel()
    if p.size == 0:
        raise ValueError("leere Eingabe")
    if p.size != y.size:
        raise ValueError(f"Längen passen nicht: {p.size} probs vs. {y.size} outcomes")
    if not np.all((p >= 0.0) & (p <= 1.0)):
        raise ValueError("probs müssen im Bereich [0, 1] liegen")
    if not np.all((y == 0.0) | (y == 1.0)):
        raise ValueError("outcomes müssen 0 oder 1 sein")
    return p, y


def brier(probs: ArrayLike, outcomes: ArrayLike) -> float:
    """Brier-Score: mittlere quadratische Abweichung (0 = perfekt)."""
    p, y = _probs_and_outcomes(probs, outcomes)
    return float(np.mean((p - y) ** 2))


def log_loss(probs: ArrayLike, outcomes: ArrayLike, eps: float = 1e-6) -> float:
    """Log-Loss mit Wahrscheinlichkeiten, die auf [eps, 1-eps] geklippt werden."""
    p, y = _probs_and_outcomes(probs, outcomes)
    pc = np.clip(p, eps, 1.0 - eps)
    return float(np.mean(-(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc))))


def brier_skill(probs: ArrayLike, base_probs: ArrayLike, outcomes: ArrayLike) -> float:
    """Skill gegen eine Referenz: 1 - brier(probs) / brier(base_probs). NaN, wenn Referenz-Brier 0."""
    base = brier(base_probs, outcomes)
    if base == 0.0:
        return float("nan")
    return 1.0 - brier(probs, outcomes) / base


def reliability_table(probs: ArrayLike, outcomes: ArrayLike, bins: int = 10) -> pd.DataFrame:
    """Kalibrierungstabelle mit gleich breiten Bins auf [0, 1]; p = 1.0 landet im letzten Bin."""
    if bins < 1:
        raise ValueError("bins muss >= 1 sein")
    p, y = _probs_and_outcomes(probs, outcomes)
    edges = np.arange(bins + 1) / bins
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)

    rows = []
    for b in range(bins):
        mask = idx == b
        n = int(mask.sum())
        rows.append(
            {
                "bin_lo": float(edges[b]),
                "bin_hi": float(edges[b + 1]),
                "n": n,
                "mean_prob": float(p[mask].mean()) if n else float("nan"),
                "hit_rate": float(y[mask].mean()) if n else float("nan"),
            }
        )
    df = pd.DataFrame(rows, columns=["bin_lo", "bin_hi", "n", "mean_prob", "hit_rate"])
    df["n"] = df["n"].astype("int64")
    return df


def roi_stats(
    returns: ArrayLike,
    n_boot: int = 5000,
    seed: int = 0,
    alpha: float = 0.05,
    clusters: Optional[Sequence[str]] = None,
) -> dict:
    """Rendite-Kennzahlen mit Bootstrap-CI des Mittelwerts und einseitigem p-Wert (H0: mean <= 0).

    clusters: Gruppen-Schlüssel je Rendite (z. B. Kalshi-Event). Dann werden ganze
    Gruppen gezogen, nicht einzelne Trades; zusammenhängende Märkte zählen so nicht
    als unabhängige Beobachtungen und das Intervall wird ehrlich breiter."""
    r = np.asarray(returns, dtype=float).ravel()
    if not np.all(np.isfinite(r)):
        raise ValueError("returns enthalten NaN oder Inf")
    n = int(r.size)
    if clusters is not None and len(clusters) != n:
        raise ValueError(f"Längen passen nicht: {n} returns vs. {len(clusters)} clusters")
    keys = ("mean", "median", "hit_rate", "total", "worst", "best", "ci_lo", "ci_hi", "p_value")
    if n == 0:
        out: dict = {"n": 0}
        out.update({k: float("nan") for k in keys})
        return out
    if n_boot < 1:
        raise ValueError("n_boot muss >= 1 sein")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha muss zwischen 0 und 1 liegen")

    mean = float(r.mean())
    out = {
        "n": n,
        "mean": mean,
        "median": float(np.median(r)),
        "hit_rate": float(np.mean(r > 0)),
        "total": float(r.sum()),
        "worst": float(r.min()),
        "best": float(r.max()),
    }

    rng = np.random.default_rng(seed)
    if clusters is None:
        idx = rng.integers(0, n, size=(n_boot, n))
        boot_means = r[idx].mean(axis=1)
    else:
        # Summe und Anzahl je Gruppe; Mittel der Stichprobe = Σ Summen / Σ Anzahlen
        _, inv = np.unique(np.asarray(clusters, dtype=object).astype(str), return_inverse=True)
        sums = np.bincount(inv, weights=r)
        counts = np.bincount(inv).astype(float)
        g = sums.size
        idx = rng.integers(0, g, size=(n_boot, g))
        boot_means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
        out["n_clusters"] = int(g)
    out["ci_lo"] = float(np.percentile(boot_means, 100.0 * alpha / 2.0))
    out["ci_hi"] = float(np.percentile(boot_means, 100.0 * (1.0 - alpha / 2.0)))
    out["p_value"] = float((np.sum(boot_means <= 0.0) + 1) / (n_boot + 1))
    return out


def max_drawdown(equity: ArrayLike) -> float:
    """Größter Rückgang vom laufenden Hoch als positiver Anteil des Hochs (0.0 bei steigender Kurve)."""
    e = np.asarray(equity, dtype=float).ravel()
    if e.size == 0:
        raise ValueError("leere Equity-Kurve")
    if not np.all(np.isfinite(e)):
        raise ValueError("Equity enthält NaN oder Inf")
    peak = np.maximum.accumulate(e)
    if np.any(peak <= 0.0):
        raise ValueError("Drawdown ist nur bei positivem laufendem Hoch definiert")
    return float(np.max((peak - e) / peak))


def bonferroni(p_values: Mapping[str, float], alpha: float = 0.05) -> Dict[str, bool]:
    """Bonferroni-Korrektur: signifikant, wenn p <= alpha / Anzahl Tests. NaN gilt als nicht signifikant."""
    m = len(p_values)
    if m == 0:
        return {}
    threshold = alpha / m
    result: Dict[str, bool] = {}
    for name, p in p_values.items():
        p = float(p)
        result[name] = False if math.isnan(p) else bool(p <= threshold)
    return result
