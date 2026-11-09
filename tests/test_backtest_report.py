"""Tests für paperbot/backtest/report.py: Markdown-Bericht und PNG-Diagramme aus einem Fake-Summary."""
from __future__ import annotations

from paperbot.backtest.report import write_backtest_report

NAN = float("nan")
SOURCE = "synthetic"

SECTIONS = [
    "# Backtest: synthetic",
    "## Ergebnis auf ungesehenen Daten (Out-of-Sample)",
    "## Kontrollen (gleiche Einstiegszeitpunkte)",
    "## Kosten-Sensitivität",
    "## 50 € Papiergeld nachgespielt",
    "## Kalibrierung der Marktpreise",
    "## Auswahl im In-Sample",
    "## Grenzen dieses Tests",
]

BULLETS = [
    "Die Märkte wurden nach Endvolumen bzw. Teilnehmerzahl ausgewählt. Das ist Wissen vom Marktende (leichte Auswahlverzerrung).",
    "Preise aus der Historie sind Mittel- oder Letztkurse. Der echte Kaufpreis liegt um den halben Spread höher; das ist als Kosten angesetzt, Markttiefe aber nicht.",
    # Manifold-Satz steht nur bei Quelle "manifold" (siehe test_manifold_* unten)
    "Ein bestätigtes Ergebnis heißt nur: auf diesen Daten nicht durch Zufall erklärbar. Es garantiert keine Gewinne in der Zukunft.",
    "Die LLM-Strategie ist hier nicht enthalten, weil ein Sprachmodell vergangene Ergebnisse kennen kann.",
]


def _ev(name, n, mean, ci_lo, ci_hi, p, hit, worst, price, by_cost, **extra):
    d = {
        "name": name, "n": n, "mean": mean, "ci_lo": ci_lo, "ci_hi": ci_hi, "p_value": p,
        "hit_rate": hit, "worst": worst, "mean_price": price, "mean_hold_days": 4.0,
        "ret_per_capital_day": mean / 4.0 if mean == mean else NAN,
        "brier_strategy": None, "brier_market": 0.21, "by_cost": by_cost,
    }
    d.update(extra)
    return d


def _fake_summary() -> dict:
    h1_oos = _ev("favorite_80_95", 58, 0.012, -0.011, 0.031, 0.21, 0.93, -1.0, 0.87,
                 {"0.00": 0.012, "0.01": 0.002, "0.02": -0.008, "0.03": -0.018})
    h1_controls = [
        _ev("zufall@favorite_80_95", 58, -0.004, -0.03, 0.02, 0.62, 0.86, -1.0, 0.87,
            {"0.00": -0.004, "0.01": -0.014, "0.02": -0.024, "0.03": -0.034}),
        _ev("immer_yes@favorite_80_95", 58, 0.003, -0.02, 0.025, 0.48, 0.91, -1.0, 0.87,
            {"0.00": 0.003, "0.01": -0.007, "0.02": -0.017, "0.03": -0.027}),
    ]
    h1_in = [
        _ev("favorite_80_95", 90, 0.010, -0.01, 0.03, 0.2, 0.92, -1.0, 0.86, {}),
        _ev("favorite_85_97", 41, NAN, NAN, NAN, NAN, NAN, NAN, NAN, {}),
        _ev("favorite_90_98", 12, 0.021, -0.05, 0.09, 0.3, 0.95, -1.0, 0.91, {}),
    ]
    # H2: keine Variante mit genug Trades In-Sample, daher kein Out-of-Sample-Ergebnis
    h2_in = [
        _ev("momentum_10_3d", 5, 0.03, -0.1, 0.12, 0.4, 0.6, -1.0, 0.5, {}),
        _ev("momentum_20_3d", 3, NAN, NAN, NAN, NAN, NAN, NAN, NAN, {}),
    ]
    h3_oos = _ev("reversion_15_1d", 44, 0.035, 0.008, 0.061, 0.001, 0.61, -1.0, 0.42,
                 {"0.00": 0.035, "0.01": 0.025, "0.02": 0.015, "0.03": 0.005})
    h3_controls = [
        _ev("zufall@reversion_15_1d", 44, -0.002, -0.04, 0.03, 0.55, 0.5, -1.0, 0.42,
            {"0.00": -0.002, "0.01": -0.012, "0.02": -0.022, "0.03": -0.032}),
    ]
    h4_oos = _ev("calibration_04", 37, -0.006, -0.05, 0.04, 0.7, 0.49, -1.0, 0.55,
                 {"0.00": -0.006, "0.01": NAN, "0.02": -0.026, "0.03": None})
    h4_controls = [
        _ev("zufall@calibration_04", 37, NAN, NAN, NAN, NAN, NAN, NAN, NAN, {}),
    ]

    reliability = []
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        if i in (0, 9):
            reliability.append({"bin_lo": lo, "bin_hi": hi, "n": 0, "mean_prob": NAN, "hit_rate": NAN})
        else:
            reliability.append({"bin_lo": lo, "bin_hi": hi, "n": 20 + 7 * i,
                                "mean_prob": (lo + hi) / 2 + 0.01, "hit_rate": (lo + hi) / 2 - 0.02})

    return {
        "source": SOURCE,
        "n_markets": 240,
        "n_train": 144,
        "n_test": 96,
        "cost": {"half_spread": 0.01, "fee": "polymarket"},
        "hypotheses": {
            "H1": {"chosen": "favorite_80_95", "verdict": "verworfen", "in_sample": h1_in,
                   "out_of_sample": h1_oos, "controls": h1_controls},
            "H2": {"chosen": None, "verdict": "zu wenige Trades In-Sample", "in_sample": h2_in},
            "H3": {"chosen": "reversion_15_1d", "verdict": "bestätigt", "in_sample": [],
                   "out_of_sample": h3_oos, "controls": h3_controls},
            "H4": {"in_sample": [], "chosen": "calibration_04", "verdict": "verworfen",
                   "calibration_curve": {"x": [0.1, 0.5, 0.9], "y": [0.12, 0.5, 0.88]},
                   "out_of_sample": h4_oos, "controls": h4_controls},
        },
        "market_reliability": reliability,
        "market_brier_test": 0.2131,
        "bankroll": {
            "favorite_80_95": {
                "final_equity": 49.1, "max_drawdown": 0.12, "taken": 40, "skipped": 3,
                "start": 50.0, "mc_ok": True, "mc_reason": None, "mc_prob_ruin": 0.05,
                "mc_final_median": 51.0, "mc_final_p5": 40.0, "mc_final_p95": 66.0,
                "mc_profitable_rate": 0.55,
            },
            "reversion_15_1d": {
                "final_equity": NAN, "max_drawdown": NAN, "taken": 0, "skipped": 0,
                "start": 50.0, "mc_ok": False, "mc_reason": "zu wenige Trades",
                "mc_prob_ruin": NAN, "mc_final_median": NAN, "mc_final_p5": NAN,
                "mc_final_p95": NAN, "mc_profitable_rate": NAN,
            },
        },
        "bonferroni_threshold": 0.05 / 9,
        "bonferroni": {"H1": False, "H2": False, "H3": True, "H4": False},
        "log": ["  In-Sample favorite_80_95: n=90, Ø=+0.0100"],
    }


def _write_equity_csv(out_dir):
    path = out_dir / f"equity_{SOURCE}_favorite_80_95.csv"
    lines = ["ts,equity"]
    base = 1_700_000_000
    eq = 50.0
    for i in range(30):
        eq += (0.3 if i % 4 else -0.5)
        lines.append(f"{base + i * 86400},{eq:.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _kalshi_summary() -> dict:
    """Kleines Kalshi-Summary nach dem Muster von results/backtest_kalshi_summary.json."""
    h5_oos = _ev("kfav_90_98", 174, -0.0227, -0.0626, 0.0116, 0.889, 0.94, -1.0, 0.945,
                 {"0.00": -0.0227, "0.01": -0.0299, "0.02": -0.0357, "0.03": -0.0402})
    h5_in = [_ev("kfav_90_98", 231, -0.0496, -0.097, -0.012, 0.998, 0.92, -1.0, 0.94, {})]
    h5_controls = [_ev("zufall@kfav_90_98", 174, -0.2909, -0.4877, -0.0507, 0.989, 0.51, -1.0, 0.53, {})]
    categories = [
        {"category": "commodities", "n": 53, "mean": -0.0404, "ci_lo": -0.1212, "ci_hi": 0.0257,
         "hit_rate": 0.9245, "mean_cost": 0.9634},
        {"category": "sports", "n": 18, "mean": 0.0472, "ci_lo": 0.0367, "ci_hi": 0.0574,
         "hit_rate": 1.0, "mean_cost": 0.9554},
    ]
    return {
        "source": "kalshi",
        "n_markets": 1143,
        "n_weather": 924,
        "n_weather_train": 546,
        "n_weather_test": 370,
        "n_train": 346,
        "n_test": 458,
        "cost": {"half_spread": "echter Briefkurs", "fee": "kalshi", "max_spread": 0.1},
        "hypotheses": {
            "H5": {"chosen": "kfav_90_98", "verdict": "verworfen", "in_sample": h5_in,
                   "out_of_sample": h5_oos, "controls": h5_controls},
            "H6": {"chosen": None, "verdict": "zu wenige Trades In-Sample", "in_sample": []},
        },
        "h5_by_category": categories,
        "market_reliability": [{"bin_lo": 0.0, "bin_hi": 0.1, "n": 10, "mean_prob": 0.04, "hit_rate": 0.02}],
        "market_brier_test": 0.125,
        "bankroll": {},
        "bonferroni_threshold": 0.00625,
    }


def test_kalshi_report_uses_real_bid_wording_and_event_limits(tmp_path):
    md_path = write_backtest_report(_kalshi_summary(), tmp_path)
    text = md_path.read_text(encoding="utf-8")

    # Kosten: echter Briefkurs statt "halber Spread je Seite"
    assert "echter Briefkurs" in text
    assert "Spread über 10 ct gilt als nicht handelbar." in text
    assert "Kosten-Annahmen" not in text
    assert "(halber Spread)" not in text
    assert "zusätzlicher Schlupf auf den echten Briefkurs" in text

    # Wetter-Datensatz in der Einleitung
    assert "Wetter-Datensatz (H8): 924 Märkte, Training 546, Test 370." in text

    # Kategorie-Abschnitt nach den Kontrollen
    assert "## H5 je Kategorie (explorativ)" in text
    assert text.index("## Kontrollen") < text.index("## H5 je Kategorie (explorativ)") < text.index("## Kosten-Sensitivität")
    assert "| commodities | 53 |" in text

    # Kalshi-Grenzen: Events, Briefkurs, Kategorien; Manifold-Satz fehlt
    assert "Intervalle und p-Werte sind über Events gezogen" in text
    assert "Kaufpreis ist der echte Briefkurs der letzten Kerze vor der Entscheidung" in text
    assert "Die Kategorie-Tabelle zu H5 ist explorativ" in text
    assert "Manifold ist ein Spielgeld-Markt" not in text


def test_manifold_report_keeps_play_money_limit_and_half_spread(tmp_path):
    summary = _fake_summary()
    summary["source"] = "manifold"
    md_path = write_backtest_report(summary, tmp_path)
    text = md_path.read_text(encoding="utf-8")

    assert "Manifold ist ein Spielgeld-Markt. Ergebnisse dort sind ein Hinweis, kein Beweis für Polymarket." in text
    assert "halber Spread 1 ct je Seite" in text
    assert "echter Briefkurs" not in text
    assert "## H5 je Kategorie (explorativ)" not in text
    assert "Ø Ertrag pro € je Kostenstufe (halber Spread):" in text


def test_markdown_has_sections_verdicts_and_placeholders(tmp_path):
    _write_equity_csv(tmp_path)
    md_path = write_backtest_report(_fake_summary(), tmp_path)

    assert md_path == tmp_path / f"BACKTEST_{SOURCE}.md"
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")

    # Abschnitte in der vorgegebenen Reihenfolge
    positions = [text.index(h) for h in SECTIONS]
    assert positions == sorted(positions)

    # Einleitung und Bonferroni-Zeile
    assert "Märkte insgesamt: 240" in text
    assert "Alle Schwellen wurden vor dem Test in docs/HYPOTHESEN.md festgelegt." in text
    assert "Signifikanzschwelle nach Bonferroni: p ≤ 0.0056" in text

    # Urteile
    assert "zu wenige Trades In-Sample" in text
    assert "verworfen" in text
    assert "bestätigt" in text

    # Fehlende Zahlen (None/NaN) werden als "–" dargestellt
    assert "–" in text

    # Bild-Verweise (relative Dateinamen)
    assert f"bt_{SOURCE}_calibration.png" in text
    assert f"bt_{SOURCE}_equity.png" in text
    assert f"bt_{SOURCE}_costs.png" in text

    # Fehlende Monte-Carlo-Analyse wird begründet
    assert "zu wenige Trades" in text

    # Grenzen: Wortlaut der Stichpunkte
    for bullet in BULLETS:
        assert f"- {bullet}" in text


def test_writes_three_nonempty_pngs(tmp_path):
    _write_equity_csv(tmp_path)
    write_backtest_report(_fake_summary(), tmp_path)

    for name in (f"bt_{SOURCE}_calibration.png", f"bt_{SOURCE}_equity.png", f"bt_{SOURCE}_costs.png"):
        png = tmp_path / name
        assert png.exists(), name
        data = png.read_bytes()
        assert len(data) > 0, name
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name


def test_missing_equity_csv_and_empty_sections_still_render(tmp_path):
    summary = _fake_summary()
    summary["bankroll"] = {}
    summary["market_reliability"] = []
    summary["hypotheses"]["H1"]["controls"] = []
    md_path = write_backtest_report(summary, tmp_path)

    text = md_path.read_text(encoding="utf-8")
    for h in SECTIONS:
        assert h in text
    assert (tmp_path / f"bt_{SOURCE}_equity.png").stat().st_size > 0
    assert (tmp_path / f"bt_{SOURCE}_calibration.png").stat().st_size > 0
