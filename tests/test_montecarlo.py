"""
Monte Carlo und Robustheit (§35, §38, §39).

Eine Backtest-Equity-Kurve ist EIN gezogener Pfad. Sie sagt wenig darüber, wie
schlimm es hätte kommen können — genau diese Lücke schließt das Modul, und
genau darauf zielen die Tests.
"""
from __future__ import annotations

import numpy as np
import pytest

from paperbot.backtest.montecarlo import (
    analyse,
    longest_losing_streaks,
    max_drawdowns,
    parameter_sensitivity,
    resample_trades,
    risk_of_ruin,
    simulate_equity,
    summary,
)


def r_series(win_rate: float, n: int = 300, seed: int = 11,
             win: float = 2.0, loss: float = -1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < win_rate, win, loss)


# ─── Reproduzierbarkeit (§45) ────────────────────────────────────────────────

def test_same_seed_gives_identical_paths():
    r = r_series(0.5)
    a = resample_trades(r, n_paths=50, seed=42)
    b = resample_trades(r, n_paths=50, seed=42)
    np.testing.assert_array_equal(a, b)


def test_different_seed_gives_different_paths():
    r = r_series(0.5)
    a = resample_trades(r, n_paths=50, seed=1)
    b = resample_trades(r, n_paths=50, seed=2)
    assert not np.array_equal(a, b)


def test_analyse_is_reproducible():
    r = r_series(0.45)
    assert analyse(r, n_paths=200, seed=5).final_median == \
           analyse(r, n_paths=200, seed=5).final_median


# ─── Resampling ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["bootstrap", "block", "shuffle"])
def test_resampling_preserves_mean_roughly(method):
    r = r_series(0.4, n=500)
    paths = resample_trades(r, n_paths=400, method=method, seed=3, block_size=10)
    assert paths.mean() == pytest.approx(r.mean(), abs=0.15)


def test_shuffle_keeps_the_exact_multiset():
    """Permutation ohne Zurücklegen: gleiche Trades, andere Reihenfolge."""
    r = r_series(0.5, n=60)
    paths = resample_trades(r, n_paths=5, method="shuffle", seed=9)
    for row in paths:
        np.testing.assert_array_equal(np.sort(row), np.sort(r))


def test_resample_shape():
    r = r_series(0.5, n=100)
    assert resample_trades(r, n_paths=17, path_length=33, seed=1).shape == (17, 33)


# ─── Equity-Simulation ───────────────────────────────────────────────────────

def test_capital_never_goes_negative():
    """
    Multiplikativ gerechnet kann das Kapital gegen null gehen, aber nie darunter
    — ein additives Modell würde hier negative Depots erzeugen.
    """
    r = np.full((20, 200), -1.0)
    eq = simulate_equity(r, starting_capital=1000.0, risk_per_trade=0.05)
    assert (eq > 0).all()


def test_positive_expectancy_grows_capital():
    eq = simulate_equity(resample_trades(r_series(0.5), 300, seed=4),
                         starting_capital=1000.0, risk_per_trade=0.01)
    assert np.median(eq[:, -1]) > 1000.0


def test_negative_expectancy_shrinks_capital():
    eq = simulate_equity(resample_trades(r_series(0.2), 300, seed=4),
                         starting_capital=1000.0, risk_per_trade=0.01)
    assert np.median(eq[:, -1]) < 1000.0


def test_higher_risk_widens_the_distribution():
    paths = resample_trades(r_series(0.45), 400, seed=6)
    low = simulate_equity(paths, 1000.0, 0.005)
    high = simulate_equity(paths, 1000.0, 0.04)
    assert high[:, -1].std() > low[:, -1].std()
    assert np.median(max_drawdowns(high)) > np.median(max_drawdowns(low))


# ─── Kennzahlen der Verteilung ───────────────────────────────────────────────

def test_drawdown_is_bounded():
    dd = max_drawdowns(simulate_equity(resample_trades(r_series(0.4), 200, seed=8),
                                       1000.0, 0.01))
    assert (dd >= 0).all() and (dd <= 1).all()


def test_losing_streak_of_pure_losses_is_full_length():
    assert longest_losing_streaks(np.full((3, 25), -1.0)).max() == 25


def test_percentiles_are_ordered():
    res = analyse(r_series(0.45), n_paths=400, seed=2)
    assert res.final_p5 <= res.final_p25 <= res.final_median <= res.final_p75 <= res.final_p95
    assert res.max_dd_median <= res.max_dd_p95 <= res.max_dd_worst


def test_ruin_probability_rises_with_risk():
    r = r_series(0.35)
    calm = analyse(r, n_paths=400, risk_per_trade=0.005, seed=3)
    reckless = analyse(r, n_paths=400, risk_per_trade=0.06, seed=3)
    assert reckless.prob_ruin >= calm.prob_ruin


def test_too_few_trades_is_reported_not_guessed():
    """Zu wenig Datenbasis muss als solche erscheinen, nicht als Zahl."""
    res = analyse([1.0, -1.0, 2.0], n_paths=100, seed=1)
    assert res.ok is False and res.reason


def test_summary_is_readable():
    assert isinstance(summary(analyse(r_series(0.45), n_paths=200, seed=1)), str)


def test_risk_of_ruin_between_zero_and_one():
    p = risk_of_ruin(0.4, 2.0, 1.0, 0.02, n_trades=100, n_paths=300, seed=1)
    assert 0.0 <= p <= 1.0


# ─── Parameterstabilität (§39) ───────────────────────────────────────────────

def test_plateau_is_recognised():
    """
    1.4/1.5/1.6/1.7 alle gut ist überzeugender als ein einzelner Spitzenwert —
    genau diese Unterscheidung fordert das Briefing.
    """
    plateau = {1.3: 0.80, 1.4: 0.95, 1.5: 0.98, 1.6: 0.97, 1.7: 0.94, 1.8: 0.79}
    out = parameter_sensitivity(plateau)
    assert out["verdict"] == "stable_plateau"
    assert out["plateau_points"] >= 3
    assert out["neighbour_drop"] < 0.2
    assert out["explanation"]


def test_isolated_spike_is_rejected():
    """Ein Optimum, dessen direkte Nachbarn einbrechen, ist ein Overfitting-Fund."""
    spike = {1.3: 0.10, 1.4: 0.12, 1.5: 0.98, 1.6: 0.11, 1.7: 0.09, 1.8: 0.10}
    out = parameter_sensitivity(spike)
    assert out["verdict"] == "isolated_peak"
    assert out["plateau_points"] == 1
    assert out["neighbour_drop"] > 0.5


def test_plateau_recommends_a_robust_value_not_the_peak():
    """
    Verwertbar ist die Mitte des Plateaus, nicht die Spitze — sonst optimiert
    man wieder auf einen Einzelwert.
    """
    skewed = {1.0: 0.50, 1.1: 0.90, 1.2: 0.93, 1.3: 0.99, 1.4: 0.95, 1.5: 0.52}
    out = parameter_sensitivity(skewed)
    assert out["robust_value"] is not None
    assert out["plateau_bounds"][0] <= out["robust_value"] <= out["plateau_bounds"][1]


def test_sensitivity_handles_thin_input():
    assert parameter_sensitivity({1.0: 0.5}) is not None


# ─── Binärwetten ─────────────────────────────────────────────────────────────

def test_binary_bet_at_090_ruins_below_and_not_above_breakeven():
    """
    Kauf zu 0.90: Gewinn-R = (1 - 0.90) / 0.90 = 0.111..., Verlust-R = -1.
    Bei 88% Trefferquote ist der Erwartungswert negativ, bei 95% positiv.
    """
    win_r = (1.0 - 0.9) / 0.9
    assert win_r == pytest.approx(1.0 / 9.0)
    bad = risk_of_ruin(0.88, win_r, -1.0, 0.05, n_trades=2000, n_paths=2000, seed=7)
    good = risk_of_ruin(0.95, win_r, -1.0, 0.05, n_trades=2000, n_paths=2000, seed=7)
    assert bad > 0.9
    assert good < 0.1
    assert good < bad
