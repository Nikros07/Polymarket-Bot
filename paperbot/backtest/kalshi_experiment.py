"""
Versuchsprotokoll der Kalshi-Runde (docs/HYPOTHESEN.md, H5–H8).

Gleicher Ablauf wie experiment.py (Auswahl In-Sample, einmal Out-of-Sample,
Kontrollen, Bonferroni), aber:
- Kauf zum echten Briefkurs + Kalshi-Gebühr, Spread > 10 Cent = nicht handelbar;
- Bootstrap über Events statt über Märkte;
- H8 auf eigenem Wetter-Datensatz mit Vorhersagemodell.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from paperbot.backtest import metrics
from paperbot.backtest.engine import (BTTrade, CostModel, Dataset, market_calibration_samples,
                                      run_strategy, simulate_bankroll, trades_frame)
from paperbot.backtest.experiment import (ALPHA, MIN_TRADES, _bump_register, _json_default,
                                          evaluate, split_by_created, verdict)
from paperbot.config import BotConfig
from paperbot.strategies import (AlwaysYesControl, FavoriteStrategy, RandomSideControl,
                                 ReversionStrategy)
from paperbot.weather import ForecastBook, TempModel, WeatherStrategy, training_rows

N_VARIANTS_KALSHI = 8       # H5: 3, H6: 2, H7: 1, H8: 2
MAX_SPREAD = 0.10
WEATHER_OFFSET_H = 6
POLITICS = ("politics", "elections")


def h5_variants():
    return [FavoriteStrategy(0.70, 0.95, name="kfav_70_95"),
            FavoriteStrategy(0.80, 0.97, name="kfav_80_97"),
            FavoriteStrategy(0.90, 0.98, name="kfav_90_98")]


def h6_variants():
    return [FavoriteStrategy(0.60, 0.85, name="politik_60_85", categories=POLITICS),
            FavoriteStrategy(0.55, 0.80, name="politik_55_80", categories=POLITICS)]


def h7_variants():
    return [ReversionStrategy(0.25, 1.0, name="kreversion_25_1d")]


def run_kalshi_experiment(broad: Dataset, weather: Dataset, forecasts: ForecastBook, *,
                          cost: CostModel, cfg: BotConfig, out_dir: Path,
                          register_path: Optional[Path] = None,
                          progress: Callable[[str], None] = print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log: List[str] = []
    summary: dict = {"source": "kalshi", "n_markets": len(broad), "n_weather": len(weather),
                     "cost": {"half_spread": "echter Briefkurs", "fee": cost.fee.kind,
                              "max_spread": MAX_SPREAD},
                     "hypotheses": {}}
    all_test: Dict[str, List[BTTrade]] = {}

    def run(ds, strat, offset=24):
        return run_strategy(ds, strat, start_offset_hours=offset, max_spread=MAX_SPREAD)

    def ev(name, trades):
        return evaluate(name, trades, cost, clustered=True)

    def confirm(key, variants, train, test, offset=24, final=None):
        best, best_ev, rows = None, None, []
        for v in variants:
            e = ev(v.name, run(train, v, offset))
            rows.append(e)
            log.append(f"  {key} In-Sample {v.name}: n={e.n}, Ø={e.mean:+.4f}")
            if e.n >= MIN_TRADES and (best_ev is None or e.mean > best_ev.mean):
                best, best_ev = v, e
        entry = {"in_sample": [r.as_dict() for r in rows]}
        if best is None:
            entry.update(chosen=None, verdict="zu wenige Trades In-Sample")
            return entry, None
        chosen = final(best) if final else best
        trades = run(test, chosen, offset)
        e = ev(chosen.name, trades)
        all_test[chosen.name] = trades
        ctrls = [ev(c.name, run(test, c, offset)) for c in
                 (RandomSideControl(chosen, name=f"zufall@{chosen.name}"),
                  AlwaysYesControl(chosen, name=f"immer_yes@{chosen.name}"))]
        entry.update(chosen=chosen.name, out_of_sample=e.as_dict(),
                     verdict=verdict(e, N_VARIANTS_KALSHI), controls=[c.as_dict() for c in ctrls])
        return entry, chosen

    # ── H5–H7 auf der breiten Stichprobe ──────────────────────────────────
    train, test = split_by_created(broad)
    summary.update(n_train=len(train), n_test=len(test))
    for key, variants in (("H5", h5_variants()), ("H6", h6_variants()), ("H7", h7_variants())):
        progress(f"{key}: Auswahl auf {len(train)} Trainingsmärkten …")
        entry, chosen = confirm(key, variants, train, test)
        summary["hypotheses"][key] = entry
        if key == "H5" and chosen is not None:
            summary["h5_by_category"] = _by_category(all_test[chosen.name], cost)

    # ── H8 Wetter ─────────────────────────────────────────────────────────
    progress("H8: Wettermodell lernen …")
    w_train, w_test = split_by_created(weather)
    w_a, w_b = split_by_created(w_train, 0.5)
    summary.update(n_weather_train=len(w_train), n_weather_test=len(w_test))
    try:
        model_a = TempModel.fit(training_rows(w_a, forecasts))
        model_full = TempModel.fit(training_rows(w_train, forecasts))
        log.append(f"  H8 Modell A: b={model_a.bias}, σ={model_a.sigma}, n={model_a.n}; "
                   f"ganzes In-Sample: b={model_full.bias}, σ={model_full.sigma}, n={model_full.n}")
        variants = [WeatherStrategy(model_a, forecasts, min_edge=e, name=f"wetter_{int(e * 100):02d}")
                    for e in (0.05, 0.10)]
        entry, chosen = confirm("H8", variants, w_b, w_test, offset=WEATHER_OFFSET_H,
                                final=lambda b: WeatherStrategy(model_full, forecasts,
                                                                min_edge=b.min_edge, name=b.name))
        entry["model_in_sample"] = {"bias": model_full.bias, "sigma": model_full.sigma, "n": model_full.n}
        # Für den Live-Betrieb: Modell auf ALLEN Wetterdaten
        live = TempModel.fit(training_rows(weather, forecasts))
        live.save(cfg.state_dir / "weather_model_kalshi.json", n_markets=len(weather),
                  min_edge=(chosen.min_edge if chosen is not None else None))
    except ValueError as exc:
        entry = {"chosen": None, "verdict": f"nicht prüfbar: {exc}"}
    summary["hypotheses"]["H8"] = entry

    # ── Kalibrierung, Bankroll, Dateien ───────────────────────────────────
    for name, ds in (("market", test), ("weather", w_test)):
        px, y = market_calibration_samples(ds)
        if len(px):
            summary[f"{name}_reliability" if name != "market" else "market_reliability"] = \
                metrics.reliability_table(px, y, bins=10).to_dict("records")
            summary[f"{name}_brier_test"] = metrics.brier(px, y)

    from paperbot.backtest.montecarlo import analyse
    sims = {}
    for name, trades in all_test.items():
        if not trades:
            continue
        ordered = sorted(trades, key=lambda t: t.entry_ts)
        curve = simulate_bankroll(ordered, cost, cfg)
        mc = analyse([t.ret(cost) for t in ordered], n_paths=5000, starting_capital=cfg.bankroll,
                     risk_per_trade=cfg.stake_frac, ruin_threshold=0.5, seed=0)
        sims[name] = {
            "final_equity": float(curve["equity"].iloc[-1]) if len(curve) else cfg.bankroll,
            "max_drawdown": metrics.max_drawdown(curve["equity"]) if len(curve) else 0.0,
            "taken": curve.attrs.get("taken", 0), "skipped": curve.attrs.get("skipped", 0),
            "start": cfg.bankroll, "mc_ok": mc.ok, "mc_reason": mc.reason,
            "mc_prob_ruin": mc.prob_ruin, "mc_final_median": mc.final_median,
            "mc_final_p5": mc.final_p5, "mc_final_p95": mc.final_p95,
            "mc_profitable_rate": mc.profitable_rate,
        }
        curve.to_csv(out_dir / f"equity_kalshi_{name}.csv", index=False)
    summary["bankroll"] = sims
    summary["bonferroni_threshold"] = ALPHA / N_VARIANTS_KALSHI
    summary["log"] = log

    frames = [trades_frame(t, cost) for t in all_test.values() if t]
    if frames:
        pd.concat(frames).to_csv(out_dir / "trades_kalshi_oos.csv", index=False)
    (out_dir / "backtest_kalshi_summary.json").write_text(
        json.dumps(summary, indent=1, default=_json_default), encoding="utf-8")
    if register_path is not None:
        _bump_register(register_path, "kalshi", N_VARIANTS_KALSHI)
    return summary


def _by_category(trades: List[BTTrade], cost: CostModel) -> List[dict]:
    """Explorativ (kein Urteil): Ertrag der H5-Variante je Kategorie, Out-of-Sample."""
    groups: Dict[str, List[BTTrade]] = defaultdict(list)
    for t in trades:
        groups[t.category or "unbekannt"].append(t)
    rows = []
    for cat, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        st = metrics.roi_stats([t.ret(cost) for t in ts], clusters=[t.cluster for t in ts])
        rows.append({"category": cat, "n": st["n"], "mean": st["mean"], "ci_lo": st["ci_lo"],
                     "ci_hi": st["ci_hi"], "hit_rate": float(np.mean([t.won for t in ts])),
                     "mean_cost": float(np.mean([cost.cost_per_share(t.side_price, t.category, t.quoted_cost)
                                                 for t in ts]))})
    return rows
