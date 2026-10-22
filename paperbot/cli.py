"""
Befehlszeile:

  python -m paperbot cycle    --source polymarket|manifold   ein Papier-Zyklus
  python -m paperbot status   --source …                     Bericht reports/STATUS.md
  python -m paperbot backtest --source manifold|polymarket|synthetic [--limit N] [--refresh]
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
        sp.add_argument("--source", default="polymarket", choices=["polymarket", "manifold"])
        sp.set_defaults(func=fn)
    bt = sub.add_parser("backtest")
    bt.add_argument("--source", default="manifold", choices=["polymarket", "manifold", "synthetic"])
    bt.add_argument("--limit", type=int, default=3000)
    bt.add_argument("--half-spread", type=float, default=0.01)
    bt.add_argument("--refresh", action="store_true")
    bt.set_defaults(func=cmd_backtest)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
