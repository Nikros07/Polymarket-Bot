"""
Befehlszeile:

  python -m paperbot cycle    --source polymarket|manifold|kalshi   ein Papier-Zyklus
  python -m paperbot serve    --source kalshi [--interval 30]       Dauerbetrieb + Statusseite
  python -m paperbot status   --source …                     Bericht reports/STATUS.md
  python -m paperbot backtest --source manifold|polymarket|synthetic|kalshi [--limit N] [--refresh]
  python -m paperbot gate     --source …                     Freigabe-Prüfung (nur Auskunft)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from paperbot.config import ROOT, BotConfig


def _client(source: str):
    if source == "polymarket":
        from paperbot.data.polymarket import PolymarketClient
        return PolymarketClient()
    if source == "manifold":
        from paperbot.data.manifold import ManifoldClient
        return ManifoldClient()
    if source == "kalshi":
        from paperbot.data.kalshi import KalshiClient
        return KalshiClient()
    raise SystemExit(f"unbekannte Quelle: {source}")


def _cfg(source: str) -> BotConfig:
    cfg = BotConfig.from_env()
    # Jede Quelle bekommt ein eigenes Konto-Verzeichnis, damit sich Spielgeld-Daten
    # (Manifold) und Polymarket nie vermischen.
    from dataclasses import replace
    return replace(cfg, state_dir=cfg.state_dir / source)


def cmd_cycle(args) -> int:
    from paperbot.engine import run_cycle
    from paperbot.report import write_status
    cfg = _cfg(args.source)
    report = run_cycle(_client(args.source), cfg)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=1))
    write_status(cfg, args.source, last_cycle=report.as_dict())
    return 1 if (report.errors and report.scanned == 0) else 0


def cmd_status(args) -> int:
    from paperbot.report import write_status
    cfg = _cfg(args.source)
    path = write_status(cfg, args.source)
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_backtest(args) -> int:
    from paperbot.backtest.datasets import fetch_dataset
    from paperbot.backtest.engine import CostModel
    from paperbot.backtest.experiment import run_experiment
    from paperbot.backtest.report import write_backtest_report
    from paperbot.fees import fee_model_for

    cfg = _cfg(args.source)
    if args.source == "kalshi":
        return _backtest_kalshi(args, cfg)
    t0 = time.time()
    ds = fetch_dataset(args.source, args.limit, BotConfig.from_env().state_dir, refresh=args.refresh)
    print(f"{len(ds)} aufgelöste Märkte geladen ({time.time() - t0:.0f} s)", file=sys.stderr)
    out = ROOT / "results"
    cost = CostModel(half_spread=args.half_spread, fee=fee_model_for(args.source))
    summary = run_experiment(ds, source=args.source, cost=cost, cfg=cfg, out_dir=out,
                             register_path=ROOT / "results" / "trials.json",
                             progress=lambda m: print(m, file=sys.stderr))
    path = write_backtest_report(summary, out)
    print(f"Bericht: {path}")
    return 0


def _backtest_kalshi(args, cfg) -> int:
    from datetime import date, timedelta

    from paperbot.backtest.datasets import check_quality, fetch_dataset, load_quality
    from paperbot.backtest.engine import CostModel
    from paperbot.backtest.kalshi_experiment import run_kalshi_experiment
    from paperbot.backtest.report import write_backtest_report
    from paperbot.data.kalshi import WEATHER_SERIES, WEATHER_START, event_date
    from paperbot.fees import fee_model_for
    from paperbot.weather import ForecastBook, fetch_forecasts

    root = BotConfig.from_env().state_dir
    t0 = time.time()
    broad = fetch_dataset("kalshi", args.limit, root, refresh=args.refresh)
    weather = fetch_dataset("kalshi_weather", 30_000, root, refresh=args.refresh)
    quality = {name: load_quality(root / "datasets" / f"{name}_{n}.json.gz")
               for name, n in (("kalshi", args.limit), ("kalshi_weather", 30_000))}
    problems = [p for p in (check_quality(q, name) for name, q in quality.items()) if p]
    for p in problems:
        print(f"Datenqualität: {p}", file=sys.stderr)
    if problems and not args.allow_data_loss:
        print("Abbruch. Mit --refresh neu laden oder bewusst mit --allow-data-loss weiter "
              "(wird im Bericht vermerkt).", file=sys.stderr)
        return 2
    fc_path = root / "datasets" / "forecasts_kalshi.json"
    forecasts = None
    if fc_path.exists() and not args.refresh:
        forecasts = ForecastBook.from_json(fc_path.read_text(encoding="utf-8"))
        last_fc = max((d for _, d in forecasts.highs), default="")
        last_ev = max((str(event_date(m.event_id)) for m, _ in weather if event_date(m.event_id)), default="")
        if last_fc < last_ev:          # Cache älter als die neuesten Märkte → Testteil ohne Vorhersage
            print(f"Vorhersage-Cache endet {last_fc}, Märkte bis {last_ev}: neu laden", file=sys.stderr)
            forecasts = None
    if forecasts is None:
        forecasts = fetch_forecasts(WEATHER_SERIES, WEATHER_START, date.today() - timedelta(days=1))
        fc_path.parent.mkdir(parents=True, exist_ok=True)
        fc_path.write_text(forecasts.to_json(), encoding="utf-8")
    print(f"{len(broad)} + {len(weather)} Märkte, {len(forecasts.highs)} Vorhersagetage "
          f"({time.time() - t0:.0f} s)", file=sys.stderr)
    cost = CostModel(half_spread=args.half_spread, fee=fee_model_for("kalshi"))
    summary = run_kalshi_experiment(broad, weather, forecasts, cost=cost, cfg=cfg,
                                    out_dir=ROOT / "results", register_path=ROOT / "results" / "trials.json",
                                    progress=lambda m: print(m, file=sys.stderr),
                                    data_quality={"datensätze": quality, "probleme": problems,
                                                  "vorhersagetage": len(forecasts.highs)})
    path = write_backtest_report(summary, ROOT / "results")
    print(f"Bericht: {path}")
    return 0


def cmd_serve(args) -> int:
    from paperbot.serve import serve
    return serve(args.source, interval_min=args.interval, port=args.port)


def cmd_gate(args) -> int:
    from paperbot.gate import DISCLAIMER, backtest_verdicts, evaluate_gate
    from paperbot.ledger import LedgerStore
    cfg = _cfg(args.source)
    ledgers = LedgerStore(cfg.state_dir).load(cfg.strategies, cfg.bankroll)
    verdicts = backtest_verdicts(ROOT / "results", args.source)
    control = ledgers.get("random_control")
    for name, led in ledgers.items():
        if name == "random_control":
            continue
        v = evaluate_gate(led, control, verdicts.get(name))
        print(f"\n{name}: {'BESTANDEN' if v.passed else 'nicht bestanden'}")
        for label, ok, detail in v.checks:
            print(f"  [{'x' if ok else ' '}] {label}: {detail}")
    print(f"\n{DISCLAIMER}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="paperbot", description="Papier-Handel und Backtest für Prognosemärkte")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("cycle", cmd_cycle), ("status", cmd_status), ("gate", cmd_gate)):
        sp = sub.add_parser(name)
        sp.add_argument("--source", default="polymarket", choices=["polymarket", "manifold", "kalshi"])
        sp.set_defaults(func=fn)
    sv = sub.add_parser("serve", help="Dauerbetrieb: Zyklus alle N Minuten + Statusseite")
    sv.add_argument("--source", default="kalshi", choices=["polymarket", "manifold", "kalshi"])
    sv.add_argument("--interval", type=float, default=30.0, help="Minuten zwischen Zyklen")
    sv.add_argument("--port", type=int, default=None, help="HTTP-Port (Standard: $PORT oder 8080)")
    sv.set_defaults(func=cmd_serve)
    bt = sub.add_parser("backtest")
    bt.add_argument("--source", default="manifold", choices=["polymarket", "manifold", "synthetic", "kalshi"])
    bt.add_argument("--limit", type=int, default=3000)
    bt.add_argument("--half-spread", type=float, default=0.01)
    bt.add_argument("--refresh", action="store_true")
    bt.add_argument("--allow-data-loss", action="store_true",
                    help="trotz > 20 %% verworfener Märkte rechnen (wird im Bericht vermerkt)")
    bt.set_defaults(func=cmd_backtest)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
