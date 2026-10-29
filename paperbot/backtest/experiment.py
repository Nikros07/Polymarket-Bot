"""
Versuchsprotokoll aus docs/HYPOTHESEN.md.

1. Chronologische Aufteilung nach Markterstellung: 60 % In-Sample, 40 % Out-of-Sample.
2. Je Hypothese genau eine Variante auf In-Sample wählen (höchster mittlerer
   Ertrag pro Euro, mindestens MIN_TRADES Trades).
3. Diese eine Variante einmal Out-of-Sample prüfen, dazu die Kontrollen
   (Zufallsseite, immer YES) mit denselben Einstiegszeitpunkten.
4. Urteil "bestätigt" nur bei: Mittelwert > 0, untere 95-%-Grenze > 0 und
   p ≤ 0,05 / Anzahl Varianten (Bonferroni). Sonst "verworfen".
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from paperbot.backtest import metrics
from paperbot.backtest.engine import (BTTrade, CostModel, Dataset, market_calibration_samples,
                                      run_strategy, simulate_bankroll, trades_frame)
from paperbot.config import BotConfig
from paperbot.strategies import (AlwaysYesControl, CalibrationStrategy, FavoriteStrategy,
                                 IsotonicCalibrator, MomentumStrategy, RandomSideControl,
                                 ReversionStrategy)

MIN_TRADES = 30
N_VARIANTS = 9          # H1: 3, H2: 2, H3: 2, H4: 2 — siehe HYPOTHESEN.md
ALPHA = 0.05
COST_GRID = (0.0, 0.01, 0.02, 0.03)


def h1_variants():
    return [FavoriteStrategy(0.80, 0.95, name="favorite_80_95"),
            FavoriteStrategy(0.85, 0.97, name="favorite_85_97"),
            FavoriteStrategy(0.90, 0.98, name="favorite_90_98")]


def h2_variants():
    return [MomentumStrategy(0.10, 3.0, name="momentum_10_3d"),
            MomentumStrategy(0.20, 3.0, name="momentum_20_3d")]


def h3_variants():
    return [ReversionStrategy(0.15, 1.0, name="reversion_15_1d"),
            ReversionStrategy(0.25, 1.0, name="reversion_25_1d")]


def split_by_created(dataset: Dataset, frac: float = 0.6, purge: bool = True) -> Tuple[Dataset, Dataset]:
    """Chronologisch nach Erstellung. purge=True: Trainingsmärkte, die erst nach dem
    Start des Testzeitraums aufgelöst wurden, fliegen raus. Sonst würde die Auswahl
    Ergebnisse kennen, die in der Testzeit liegen."""
    ordered = sorted(dataset, key=lambda mh: (_created(mh), mh[0].market_id))
    cut = int(len(ordered) * frac)
    train, test = ordered[:cut], ordered[cut:]
    if purge and test:
        test_start = _created(test[0])
        train = [mh for mh in train if (mh[0].resolved_ts or mh[1][-1].t) < test_start]
    return train, test


def _created(mh) -> int:
    return mh[0].created_ts if mh[0].created_ts is not None else mh[1][0].t


@dataclass
class Evaluation:
    name: str
    n: int
    mean: float
    ci_lo: float
    ci_hi: float
    p_value: float
    hit_rate: float
    worst: float
    mean_price: float
    mean_hold_days: float
    ret_per_capital_day: float
    brier_strategy: Optional[float]
    brier_market: Optional[float]
    by_cost: Dict[str, float] = field(default_factory=dict)
    n_clusters: Optional[int] = None     # Anzahl Events beim Event-Bootstrap

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def grid_cost(cost: CostModel, step: float, quoted: bool) -> CostModel:
    """Kostenstufe der Sensitivität: ohne echten Kurs ist `step` der angenommene halbe
    Spread, mit echtem Briefkurs ist `step` zusätzlicher Schlupf darauf."""
    if quoted:
        return CostModel(half_spread=cost.half_spread, fee=cost.fee, max_price=cost.max_price,
                         slippage=step)
    return CostModel(half_spread=step, fee=cost.fee, max_price=cost.max_price)


def evaluate(name: str, trades: List[BTTrade], cost: CostModel, seed: int = 0,
             clustered: bool = False) -> Evaluation:
    """clustered=True: Bootstrap über Events (Kalshi), sonst über Trades."""
    if not trades:
        nan = float("nan")
        return Evaluation(name, 0, nan, nan, nan, nan, nan, nan, nan, nan, nan, None, None, {})
    rets = np.array([t.ret(cost) for t in trades])
    st = metrics.roi_stats(rets, seed=seed,
                           clusters=[t.cluster for t in trades] if clustered else None)
    holds = np.array([t.hold_days for t in trades])
    wins = np.array([1 if t.won else 0 for t in trades])
    prices = np.array([t.side_price for t in trades])
    probs = np.array([t.prob if t.prob is not None else t.side_price for t in trades])
    has_prob = any(t.prob is not None for t in trades)
    by_cost = {}
    for hs in COST_GRID:
        by_cost[f"{hs:.2f}"] = float(np.mean(
            [t.ret(grid_cost(cost, hs, t.quoted_cost is not None)) for t in trades]))
    mean_hold = float(holds.mean())
    return Evaluation(
        name=name, n=st["n"], mean=st["mean"], ci_lo=st["ci_lo"], ci_hi=st["ci_hi"],
        p_value=st["p_value"], hit_rate=float(wins.mean()), worst=st["worst"],
        mean_price=float(prices.mean()), mean_hold_days=mean_hold,
        ret_per_capital_day=st["mean"] / max(mean_hold, 1 / 24),
        brier_strategy=metrics.brier(probs, wins) if has_prob else None,
        brier_market=metrics.brier(prices, wins),
        by_cost=by_cost,
        n_clusters=st.get("n_clusters"),
    )


def verdict(ev: Evaluation, n_variants: int = N_VARIANTS) -> str:
    if ev.n < MIN_TRADES:
        return "zu wenige Trades"
    if ev.mean > 0 and ev.ci_lo > 0 and ev.p_value <= ALPHA / n_variants:
        return "bestätigt"
    return "verworfen"


def _select(variants, train: Dataset, cost: CostModel, log: List[str]):
    best, best_ev = None, None
    rows = []
    for v in variants:
        ev = evaluate(v.name, run_strategy(train, v), cost)
        rows.append(ev)
        log.append(f"  In-Sample {v.name}: n={ev.n}, Ø={ev.mean:+.4f}")
        if ev.n >= MIN_TRADES and (best_ev is None or ev.mean > best_ev.mean):
            best, best_ev = v, ev
    return best, best_ev, rows


def _controls(chosen, test: Dataset, cost: CostModel) -> List[Evaluation]:
    out = []
    for ctrl in (RandomSideControl(chosen, name=f"zufall@{chosen.name}"),
                 AlwaysYesControl(chosen, name=f"immer_yes@{chosen.name}")):
        out.append(evaluate(ctrl.name, run_strategy(test, ctrl), cost))
    return out


def run_experiment(dataset: Dataset, *, source: str, cost: CostModel, cfg: BotConfig,
                   out_dir: Path, register_path: Optional[Path] = None,
                   progress: Callable[[str], None] = print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    train, test = split_by_created(dataset)
    n_purged = int(len(dataset) * 0.6) - len(train)
    log: List[str] = [f"Sperrzone: {n_purged} Trainingsmärkte entfernt (erst im Testzeitraum aufgelöst)"]
    summary: dict = {
        "source": source, "n_markets": len(dataset), "n_train": len(train), "n_test": len(test),
        "n_purged": n_purged,
        "cost": {"half_spread": cost.half_spread, "fee": cost.fee.kind},
        "hypotheses": {},
    }
    all_test_trades: Dict[str, List[BTTrade]] = {}

    for key, variants in (("H1", h1_variants()), ("H2", h2_variants()), ("H3", h3_variants())):
        progress(f"{key}: Auswahl auf {len(train)} Trainingsmärkten …")
        chosen, chosen_ev, in_rows = _select(variants, train, cost, log)
        entry = {"in_sample": [e.as_dict() for e in in_rows]}
        if chosen is None:
            entry.update(chosen=None, verdict="zu wenige Trades In-Sample")
        else:
            test_trades = run_strategy(test, chosen)
            ev = evaluate(chosen.name, test_trades, cost)
            all_test_trades[chosen.name] = test_trades
            entry.update(chosen=chosen.name, out_of_sample=ev.as_dict(), verdict=verdict(ev),
                         controls=[c.as_dict() for c in _controls(chosen, test, cost)])
        summary["hypotheses"][key] = entry

    # H4: Kurve auf Train-A lernen, Variante auf Train-B wählen, dann auf ganzem Train neu lernen
    progress("H4: Kalibrierungskurve lernen …")
    train_a, train_b = split_by_created(train, 0.5)
    entry = {}
    try:
        px_a, y_a = market_calibration_samples(train_a)
        cal_a = IsotonicCalibrator.fit(px_a, y_a)
        variants = [CalibrationStrategy(cal_a, min_edge=e, cost=cost.half_spread,
                                        name=f"calibration_{int(e * 100):02d}") for e in (0.02, 0.04)]
        chosen, _, in_rows = _select(variants, train_b, cost, log)
        entry["in_sample"] = [e.as_dict() for e in in_rows]
        px, y = market_calibration_samples(train)
        cal = IsotonicCalibrator.fit(px, y)
        entry["calibration_curve"] = cal.to_dict()
        if chosen is None:
            entry.update(chosen=None, verdict="zu wenige Trades In-Sample")
        else:
            final = CalibrationStrategy(cal, min_edge=chosen.min_edge, cost=cost.half_spread, name=chosen.name)
            test_trades = run_strategy(test, final)
            ev = evaluate(final.name, test_trades, cost)
            all_test_trades[final.name] = test_trades
            entry.update(chosen=final.name, out_of_sample=ev.as_dict(), verdict=verdict(ev),
                         controls=[c.as_dict() for c in _controls(final, test, cost)])
        # Für den Live-Betrieb: Kurve auf ALLEN Daten der Quelle
        px_all, y_all = market_calibration_samples(dataset)
        IsotonicCalibrator.fit(px_all, y_all).save(
            cfg.state_dir / f"calibration_{source}.json", source=source, n_markets=len(dataset),
            min_edge=(chosen.min_edge if chosen is not None else None))
    except ValueError as exc:
        entry.update(chosen=None, verdict=f"nicht prüfbar: {exc}")
    summary["hypotheses"]["H4"] = entry

    # Marktkalibrierung Out-of-Sample (für Bericht und Pitch)
    px_t, y_t = market_calibration_samples(test)
    if len(px_t):
        summary["market_reliability"] = metrics.reliability_table(px_t, y_t, bins=10).to_dict("records")
        summary["market_brier_test"] = metrics.brier(px_t, y_t)

    # Bankroll-Simulation mit echtem Startkapital und Monte-Carlo-Ruinrisiko
    from paperbot.backtest.montecarlo import analyse
    sims = {}
    for name, trades in all_test_trades.items():
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
            "start": cfg.bankroll,
            "mc_ok": mc.ok, "mc_reason": mc.reason, "mc_prob_ruin": mc.prob_ruin,
            "mc_final_median": mc.final_median, "mc_final_p5": mc.final_p5,
            "mc_final_p95": mc.final_p95, "mc_profitable_rate": mc.profitable_rate,
        }
        curve.to_csv(out_dir / f"equity_{source}_{name}.csv", index=False)
    summary["bankroll"] = sims

    pvals = {k: v.get("out_of_sample", {}).get("p_value", float("nan"))
             for k, v in summary["hypotheses"].items()}
    summary["bonferroni_threshold"] = ALPHA / N_VARIANTS
    summary["bonferroni"] = {k: (not math.isnan(p)) and p <= ALPHA / N_VARIANTS for k, p in pvals.items()}
    summary["log"] = log

    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [trades_frame(t, cost) for t in all_test_trades.values() if t]
    if frames:
        pd.concat(frames).to_csv(out_dir / f"trades_{source}_oos.csv", index=False)
    (out_dir / f"backtest_{source}_summary.json").write_text(
        json.dumps(summary, indent=1, default=_json_default), encoding="utf-8")
    if register_path is not None:
        _bump_register(register_path, source, N_VARIANTS)
    return summary


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, float) and math.isnan(o):
        return None
    return str(o)


def _bump_register(path: Path, source: str, n: int) -> None:
    """Versuchsregister: zählt jede geprüfte Variante (Lehre Quant-Lab: n_trials ehrlich zählen)."""
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[source] = int(data.get(source, 0)) + n
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
