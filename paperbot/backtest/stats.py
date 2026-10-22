"""Statistik gegen Zufallstreffer: PSR, Deflated Sharpe, Bootstrap, PBO.

Referenzen (Formeln, nicht von mir erfunden):
* Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier" — Probabilistic Sharpe Ratio.
* Bailey & López de Prado (2014), "The Deflated Sharpe Ratio" — Mehrfachtest-Korrektur.
* Bailey, Borwein, López de Prado, Zhu (2017), "The Probability of Backtest Overfitting" — CSCV/PBO.
* Politis & Romano (1994), "The Stationary Bootstrap".
Alle Sharpe-Werte hier sind **pro Periode (Tag)**, nicht annualisiert, sofern nicht anders genannt.
Kopiert aus Quant-Lab/qlab/stats.py (2026-10-22), Annualisierung parametrisiert.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as sps

EULER_GAMMA = 0.5772156649015329


def psr(sr: float, sr_ref: float, n: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio: P(wahre SR > sr_ref). kurt = NICHT-excess Kurtosis."""
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2
    if n < 3 or denom <= 0 or not np.isfinite(sr):
        return float("nan")
    return float(sps.norm.cdf((sr - sr_ref) * np.sqrt(n - 1) / np.sqrt(denom)))


def expected_max_sr(n_trials: int, var_sr: float) -> float:
    """Erwartetes Maximum der Sharpe-Werte von n_trials unabhängigen Versuchen ohne echtes Können."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    z1 = sps.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = sps.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(var_sr) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe(ret: pd.Series, n_trials: int, var_sr_trials: float, rf: pd.Series | None = None,
                    periods_per_year: float = 252.0) -> dict:
    """DSR: PSR gegen die Schwelle, die der beste von n_trials Zufallsversuchen erreichen würde.

    periods_per_year betrifft nur die annualisierten Felder (sr_annual, sr0_annual);
    dsr und psr_vs_zero bleiben pro Periode.
    """
    r = ret.dropna()
    ex = r - (rf.reindex(r.index).fillna(0.0) if rf is not None else 0.0)
    sr = float(ex.mean() / ex.std(ddof=1))
    sr0 = expected_max_sr(n_trials, var_sr_trials)
    ann = np.sqrt(periods_per_year)
    return {
        "sr_daily": sr, "sr_annual": sr * ann, "sr0_daily": sr0, "sr0_annual": sr0 * ann,
        "dsr": psr(sr, sr0, len(r), float(r.skew()), float(r.kurt() + 3.0)),
        "psr_vs_zero": psr(sr, 0.0, len(r), float(r.skew()), float(r.kurt() + 3.0)),
        "n_trials": n_trials,
    }


def _stationary_idx(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    jumps = rng.random(n) < 1.0 / mean_block
    jumps[0] = True
    first_t = np.flatnonzero(jumps)
    seg_id = np.cumsum(jumps) - 1
    starts = rng.integers(0, n, size=len(first_t))
    return (starts[seg_id] + (np.arange(n) - first_t[seg_id])) % n


def bootstrap_sharpe_diff(ret: pd.Series, bench: pd.Series, rf: pd.Series | None = None,
                          n_boot: int = 2000, mean_block: float = 21.0, seed: int = 0) -> dict:
    """Stationärer Bootstrap für die annualisierte Sharpe-Differenz Strategie − Benchmark."""
    df = pd.concat([ret, bench], axis=1, join="inner").dropna()
    if rf is not None:
        df = df.sub(rf.reindex(df.index).fillna(0.0), axis=0)
    a, b = df.iloc[:, 0].to_numpy(), df.iloc[:, 1].to_numpy()
    n = len(a)
    rng = np.random.default_rng(seed)
    ppy = n / max((df.index[-1] - df.index[0]).days / 365.25, 1e-9)

    def sr(x):
        s = x.std(ddof=1)
        return x.mean() / s * np.sqrt(ppy) if s > 0 else 0.0

    obs = sr(a) - sr(b)
    d = np.empty(n_boot)
    for k in range(n_boot):
        ix = _stationary_idx(n, mean_block, rng)
        d[k] = sr(a[ix]) - sr(b[ix])
    centered = d - d.mean()
    p_one_sided = float((centered >= obs).mean())  # H0: Differenz <= 0
    lo, hi = np.percentile(d, [5, 95])
    return {"sharpe_diff": float(obs), "ci90": (float(lo), float(hi)), "p_value": p_one_sided, "n": n}


def pbo_cscv(returns: pd.DataFrame, n_slices: int = 16) -> dict:
    """Probability of Backtest Overfitting (CSCV). Spalten = Strategien/Varianten, Zeilen = Tage.

    Misst, wie oft die in der Auswahlhälfte beste Variante in der Testhälfte unter dem Median landet.
    PBO nahe 0 = Auswahl trägt; nahe 0,5 oder darüber = Auswahl ist Zufall.
    """
    R = returns.dropna(how="any")
    T, N = R.shape
    if N < 3 or T < n_slices * 10:
        return {"pbo": float("nan"), "n_strategies": N, "note": "zu wenig Daten/Varianten"}
    S = n_slices - (n_slices % 2)
    edges = np.linspace(0, T, S + 1, dtype=int)
    blocks = [R.to_numpy()[edges[i]:edges[i + 1]] for i in range(S)]
    cnt = np.array([len(b) for b in blocks], float)
    sm = np.array([b.sum(axis=0) for b in blocks])
    sq = np.array([(b ** 2).sum(axis=0) for b in blocks])

    def sharpe_from(ix):
        n = cnt[list(ix)].sum()
        m = sm[list(ix)].sum(axis=0) / n
        v = sq[list(ix)].sum(axis=0) / n - m ** 2
        return np.where(v > 0, m / np.sqrt(np.maximum(v, 1e-18)), -np.inf)

    logits = []
    for ins in combinations(range(S), S // 2):
        oos = tuple(sorted(set(range(S)) - set(ins)))
        s_in, s_out = sharpe_from(ins), sharpe_from(oos)
        best = int(np.argmax(s_in))
        rank = (s_out < s_out[best]).sum() + 1  # 1..N, N = bester
        w = rank / (N + 1.0)
        logits.append(np.log(w / (1 - w)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "n_strategies": N, "n_splits": len(logits),
            "median_logit": float(np.median(logits))}
