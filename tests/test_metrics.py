"""Tests für paperbot.backtest.metrics. Offline, ohne Netzwerk."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from paperbot.backtest.metrics import (
    bonferroni,
    brier,
    brier_skill,
    log_loss,
    max_drawdown,
    reliability_table,
    roi_stats,
)


# ── Brier / Log-Loss / Skill ──────────────────────────────────────────────────

def test_brier_hand_computed():
    # (0.8-1)^2 = 0.04, (0.2-0)^2 = 0.04 -> Mittel 0.04
    assert brier([0.8, 0.2], [1, 0]) == pytest.approx(0.04)
    # (0.5-1)^2 + (0.5-0)^2 + (0.5-1)^2 = 0.75 -> Mittel 0.25
    assert brier(np.array([0.5, 0.5, 0.5]), [1, 0, 1]) == pytest.approx(0.25)


def test_brier_perfect_and_worst():
    assert brier([1.0, 0.0], [1, 0]) == 0.0
    assert brier([0.0, 1.0], [1, 0]) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "probs, outcomes",
    [
        ([], []),
        ([0.5, 0.5], [1]),
        ([1.2, 0.3], [1, 0]),
        ([-0.1, 0.3], [1, 0]),
    ],
)
def test_brier_rejects_invalid_input(probs, outcomes):
    with pytest.raises(ValueError):
        brier(probs, outcomes)


def test_log_loss_hand_computed():
    # -(ln 0.8 + ln 0.8)/2 = -ln 0.8
    assert log_loss([0.8, 0.2], [1, 0]) == pytest.approx(-math.log(0.8))


def test_log_loss_clips_extremes():
    # p = 1.0 bei Ergebnis 0 wird auf 1 - eps geklippt -> -ln(eps)
    assert log_loss([1.0], [0], eps=1e-6) == pytest.approx(-math.log(1e-6))
    assert log_loss([0.0], [1], eps=1e-6) == pytest.approx(-math.log(1e-6))


def test_brier_skill_hand_computed():
    # base: brier 0.25, Modell: brier 0.04 -> 1 - 0.04/0.25 = 0.84
    assert brier_skill([0.8, 0.2], [0.5, 0.5], [1, 0]) == pytest.approx(0.84)


def test_brier_skill_nan_when_base_perfect():
    assert math.isnan(brier_skill([0.5, 0.5], [1.0, 0.0], [1, 0]))


# ── Reliability ───────────────────────────────────────────────────────────────

def test_reliability_table_bins_and_edges():
    probs = [0.05, 0.05, 0.95, 1.0]
    outcomes = [0, 1, 1, 1]
    df = reliability_table(probs, outcomes, bins=10)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["bin_lo", "bin_hi", "n", "mean_prob", "hit_rate"]
    assert len(df) == 10
    assert df["n"].sum() == 4

    first = df.iloc[0]
    assert first["bin_lo"] == pytest.approx(0.0)
    assert first["bin_hi"] == pytest.approx(0.1)
    assert first["n"] == 2
    assert first["mean_prob"] == pytest.approx(0.05)
    assert first["hit_rate"] == pytest.approx(0.5)

    # 0.95 und 1.0 landen beide im letzten Bin [0.9, 1.0]
    last = df.iloc[-1]
    assert last["bin_hi"] == pytest.approx(1.0)
    assert last["n"] == 2
    assert last["mean_prob"] == pytest.approx(0.975)
    assert last["hit_rate"] == pytest.approx(1.0)


def test_reliability_table_keeps_empty_bins():
    df = reliability_table([0.05, 0.95], [0, 1], bins=10)
    empty = df[df["n"] == 0]
    assert len(empty) == 8
    assert empty["mean_prob"].isna().all()
    assert empty["hit_rate"].isna().all()
    assert df["n"].dtype.kind == "i"


def test_reliability_table_bin_boundary_goes_up():
    # 0.5 gehört zu [0.5, 0.6), nicht zu [0.4, 0.5)
    df = reliability_table([0.5], [1], bins=10)
    assert df.iloc[5]["n"] == 1
    assert df.iloc[4]["n"] == 0


# ── ROI-Statistik ─────────────────────────────────────────────────────────────

KNOWN = np.array([1.0, -1.0, 2.0, 0.0, 3.0])


def test_roi_stats_known_array_exact_values():
    s = roi_stats(KNOWN, n_boot=2000, seed=0)
    assert s["n"] == 5
    assert s["mean"] == pytest.approx(1.0)
    assert s["median"] == pytest.approx(1.0)
    assert s["hit_rate"] == pytest.approx(0.6)  # 1, 2, 3 > 0
    assert s["total"] == pytest.approx(5.0)
    assert s["worst"] == pytest.approx(-1.0)
    assert s["best"] == pytest.approx(3.0)


def test_roi_stats_ci_contains_mean():
    s = roi_stats(KNOWN, n_boot=2000, seed=0)
    assert s["ci_lo"] <= s["mean"] <= s["ci_hi"]


def test_roi_stats_p_value_clearly_positive_is_small():
    rng = np.random.default_rng(123)
    returns = rng.normal(1.0, 0.1, 100)
    s = roi_stats(returns, n_boot=2000, seed=0)
    assert s["p_value"] < 0.01
    assert s["ci_lo"] > 0


def test_roi_stats_p_value_clearly_negative_is_near_one():
    rng = np.random.default_rng(456)
    returns = rng.normal(-1.0, 0.1, 100)
    s = roi_stats(returns, n_boot=2000, seed=0)
    assert s["p_value"] > 0.99


def test_roi_stats_p_value_formula_bounds():
    s = roi_stats(KNOWN, n_boot=999, seed=0)
    assert 1 / (999 + 1) <= s["p_value"] <= 1.0


def test_roi_stats_deterministic_with_same_seed():
    a = roi_stats(KNOWN, n_boot=500, seed=42)
    b = roi_stats(KNOWN, n_boot=500, seed=42)
    assert a == b


def test_roi_stats_empty():
    s = roi_stats([])
    assert s["n"] == 0
    for key in ("mean", "median", "hit_rate", "total", "worst", "best", "ci_lo", "ci_hi", "p_value"):
        assert math.isnan(s[key])


def test_roi_stats_single_value_ci_equals_value():
    s = roi_stats([0.4], n_boot=1000, seed=0)
    assert s["n"] == 1
    assert s["mean"] == pytest.approx(0.4)
    assert s["ci_lo"] == pytest.approx(0.4)
    assert s["ci_hi"] == pytest.approx(0.4)
    assert s["hit_rate"] == pytest.approx(1.0)
    # Mittelwert > 0 -> nur 1 von n_boot + 1 Bootstrap-Resamples erfüllt <= 0 nicht
    assert s["p_value"] == pytest.approx(1 / 1001)


# ── Max-Drawdown ──────────────────────────────────────────────────────────────

def test_max_drawdown_hand_computed():
    # Hochs: 100, 120, 120, 130, 130; größter Rückgang 130 -> 65 = 0.5
    assert max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(0.5)


def test_max_drawdown_monotone_increasing_is_zero():
    assert max_drawdown([1, 2, 3, 4]) == 0.0


def test_max_drawdown_accepts_series_and_array():
    s = pd.Series([100.0, 50.0, 75.0])
    assert max_drawdown(s) == pytest.approx(0.5)
    assert max_drawdown(np.array([100.0, 50.0, 75.0])) == pytest.approx(0.5)


def test_max_drawdown_empty_raises():
    with pytest.raises(ValueError):
        max_drawdown([])


# ── Bonferroni ────────────────────────────────────────────────────────────────

def test_bonferroni_three_p_values():
    # Schwelle 0.05 / 3 = 0.01667
    res = bonferroni({"a": 0.01, "b": 0.02, "c": 0.5}, alpha=0.05)
    assert res == {"a": True, "b": False, "c": False}


def test_bonferroni_threshold_inclusive_and_nan():
    res = bonferroni({"x": 0.05 / 2, "y": float("nan")}, alpha=0.05)
    assert res == {"x": True, "y": False}


def test_bonferroni_empty():
    assert bonferroni({}) == {}
