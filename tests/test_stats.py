import numpy as np
import pandas as pd
import pytest

from paperbot.backtest import stats


def test_psr_monotone_and_half_at_reference():
    assert stats.psr(0.05, 0.05, 1000, 0.0, 3.0) == pytest.approx(0.5)
    assert stats.psr(0.08, 0.0, 1000, 0.0, 3.0) > stats.psr(0.03, 0.0, 1000, 0.0, 3.0)


def test_expected_max_sr_grows_with_trials():
    a = stats.expected_max_sr(10, 0.0001)
    b = stats.expected_max_sr(1000, 0.0001)
    assert 0 < a < b
    assert stats.expected_max_sr(1, 0.0001) == 0.0


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0006, 0.01, 2500), index=pd.bdate_range("2010", periods=2500))
    one = stats.deflated_sharpe(r, 1, 1e-4)
    many = stats.deflated_sharpe(r, 500, 1e-4)
    assert one["dsr"] == pytest.approx(one["psr_vs_zero"])
    assert many["dsr"] < one["dsr"]


def test_deflated_sharpe_periods_per_year_scales_annual_only():
    rng = np.random.default_rng(4)
    r = pd.Series(rng.normal(0.0005, 0.01, 1000), index=pd.bdate_range("2010", periods=1000))
    d252 = stats.deflated_sharpe(r, 10, 1e-4)
    d365 = stats.deflated_sharpe(r, 10, 1e-4, periods_per_year=365)
    assert d365["sr_annual"] != pytest.approx(d252["sr_annual"])
    assert d365["sr_annual"] / d252["sr_annual"] == pytest.approx(np.sqrt(365 / 252))
    assert d365["sr0_annual"] / d252["sr0_annual"] == pytest.approx(np.sqrt(365 / 252))
    assert d365["sr_daily"] == d252["sr_daily"]
    assert d365["dsr"] == pytest.approx(d252["dsr"])


def test_bootstrap_identical_series_is_not_significant():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0003, 0.01, 2000), index=pd.bdate_range("2012", periods=2000))
    out = stats.bootstrap_sharpe_diff(r, r, n_boot=300)
    assert abs(out["sharpe_diff"]) < 1e-9
    assert out["p_value"] > 0.2


def test_bootstrap_detects_real_difference():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2005", periods=3000)
    bench = pd.Series(rng.normal(0.0002, 0.01, 3000), index=idx)
    strat = bench + 0.0008 + rng.normal(0, 0.001, 3000)  # klar besser
    out = stats.bootstrap_sharpe_diff(strat, bench, n_boot=300)
    assert out["sharpe_diff"] > 0.5 and out["p_value"] < 0.05


def test_pbo_noise_is_near_half_and_skill_is_low():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2000", periods=4000)
    noise = pd.DataFrame(rng.normal(0, 0.01, (4000, 30)), index=idx)
    p_noise = stats.pbo_cscv(noise)["pbo"]
    assert 0.25 < p_noise < 0.75
    skill = noise.copy()
    skill[0] = skill[0] + 0.001  # eine Variante hat dauerhaft Vorsprung
    assert stats.pbo_cscv(skill)["pbo"] < 0.1
