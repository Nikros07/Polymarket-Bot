"""Zuordnung der Backtest-Urteile zu Strategie-Familien (Kalshi und Manifold)."""
import json

from paperbot.gate import backtest_verdicts


def test_kalshi_hypotheses_map_to_live_strategies(tmp_path):
    summary = {"hypotheses": {
        "H5": {"verdict": "verworfen"},
        "H6": {"verdict": "zu wenige Trades In-Sample"},
        "H7": {"verdict": "verworfen"},
        "H8": {"verdict": "bestätigt"},
    }}
    (tmp_path / "backtest_kalshi_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    assert backtest_verdicts(tmp_path, "kalshi") == {"favorite": "verworfen", "weather": "bestätigt"}


def test_manifold_hypotheses_still_map_to_families(tmp_path):
    summary = {"hypotheses": {
        "H1": {"verdict": "bestätigt"},
        "H2": {"verdict": "verworfen"},
        "H3": {"verdict": "verworfen"},
        "H4": {"verdict": "zu wenige Trades In-Sample"},
    }}
    (tmp_path / "backtest_manifold_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    assert backtest_verdicts(tmp_path, "manifold") == {
        "favorite": "bestätigt",
        "momentum": "verworfen",
        "reversion": "verworfen",
        "calibration": "zu wenige Trades In-Sample",
    }
