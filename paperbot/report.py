"""
Statusbericht des Papier-Bots als Markdown (deutsch).

Schreibt STATUS_<quelle>.md und STATUS.md in cfg.report_dir. Es wird nur mit
Papiergeld gerechnet; der Bericht sendet keine Orders und bewegt kein Geld.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from paperbot.backtest.metrics import max_drawdown
from paperbot.config import BotConfig
from paperbot.ledger import Ledger, LedgerStore, atomic_write_text

DASH = "–"
QUESTION_MAX = 70
RECENT_CLOSED = 15
TOP_SKIP_REASONS = 8
MAX_ERRORS = 10
RESULT_NAMES = {1: "YES", 0: "NO", None: "annulliert"}
HONESTY_LINE = ("Diese Übersicht beweist keinen Vorteil. Aussagekräftig wird sie erst "
                "ab etwa 100 aufgelösten Märkten pro Strategie.")


def _esc(text: str) -> str:
    """Escapt Pipe-Zeichen, damit Tabellenzellen nicht brechen."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _utc_str(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d") if ts is not None else DASH


def _truncate(text: str, limit: int = QUESTION_MAX) -> str:
    """Kürzt auf höchstens `limit` Zeichen (inkl. '…')."""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _table(headers: List[str], rows: List[List[str]]) -> List[str]:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _hit_rate(led: Ledger) -> str:
    decided = [p for p in led.closed_positions() if p.outcome is not None]
    if not decided:
        return DASH
    wins = sum(1 for p in decided if (p.payout or 0.0) > 0)
    return f"{100.0 * wins / len(decided):.1f} %"


def _max_dd(led: Ledger) -> str:
    if len(led.equity_history) < 2:
        return DASH
    values = [e for _, e in led.equity_history]
    try:
        return f"{100.0 * max_drawdown(values):.1f} %"
    except ValueError:
        return DASH


def _reference_ts(led: Ledger) -> int:
    if led.equity_history:
        return int(max(t for t, _ in led.equity_history))
    return int(datetime.now(timezone.utc).timestamp())


def _brake(led: Ledger) -> str:
    if led.paused_until is None:
        return DASH
    if led.paused_until > _reference_ts(led):
        return f"bis {_utc_str(led.paused_until)}"
    return DASH


def _accounts_section(ledgers: dict, cfg: BotConfig) -> List[str]:
    rows = []
    for name, led in ledgers.items():
        equity = led.equity()
        ret = (equity / led.start_bankroll - 1.0) * 100.0 if led.start_bankroll else 0.0
        rows.append((equity, [
            _esc(name),
            f"{equity:.2f}",
            f"{ret:+.1f} %",
            f"{led.cash:.2f}",
            f"{led.invested():.2f}",
            str(len(led.open_positions())),
            str(len(led.closed_positions())),
            _hit_rate(led),
            _max_dd(led),
            _brake(led),
        ]))
    rows.sort(key=lambda r: r[0], reverse=True)
    out = [f"## Konten (je {cfg.bankroll:.0f} € Papiergeld)", ""]
    out += _table(["Strategie", "Wert (€)", "Ertrag", "Bargeld", "investiert", "offen",
                   "aufgelöst", "Trefferquote", "max. Rückgang", "Notbremse"],
                  [r[1] for r in rows])
    return out


def _open_section(ledgers: dict) -> List[str]:
    rows = []
    for name, led in ledgers.items():
        for p in led.open_positions():
            rows.append([_esc(name), _esc(_truncate(p.question)), p.side,
                         f"{p.shares:.2f}", f"{p.avg_price:.3f}", f"{p.cost:.2f}",
                         _utc_str(p.opened_ts)])
    out = ["## Offene Positionen", ""]
    if not rows:
        return out + ["Keine offenen Positionen."]
    return out + _table(["Strategie", "Markt", "Seite", "Anteile", "Preis", "Einsatz (€)", "seit"], rows)


def _closed_section(ledgers: dict) -> List[str]:
    closed: List[tuple] = []
    for name, led in ledgers.items():
        for p in led.closed_positions():
            closed.append((p.closed_ts or 0, name, p))
    closed.sort(key=lambda x: x[0], reverse=True)
    out = ["## Zuletzt aufgelöst", ""]
    if not closed:
        return out + ["Noch nichts aufgelöst."]
    rows = []
    for _, name, p in closed[:RECENT_CLOSED]:
        pnl = p.pnl if p.pnl is not None else 0.0
        rows.append([_esc(name), _esc(_truncate(p.question)), p.side,
                     RESULT_NAMES.get(p.outcome, "annulliert"), f"{pnl:+.2f}"])
    return out + _table(["Strategie", "Markt", "Seite", "Ergebnis", "Gewinn (€)"], rows)


def _cycle_section(last_cycle: dict) -> List[str]:
    def items(key: str) -> list:
        val = last_cycle.get(key) or []
        return list(val)

    opened = items("opened")
    settled = items("settled")
    waiting = items("waiting")
    skipped = last_cycle.get("skipped") or {}
    errors = items("errors")

    out = ["## Letzter Zyklus", ""]
    out.append(f"- gescannt: {last_cycle.get('scanned', 0)}")
    out.append(f"- handelbar: {last_cycle.get('eligible', 0)}")
    out.append(f"- Signale: {last_cycle.get('signals', 0)}")
    opened_txt = ", ".join(_esc(str(x)) for x in opened) if opened else DASH
    out.append(f"- gekauft: {len(opened)} ({opened_txt})")
    out.append(f"- abgerechnet: {len(settled)}")
    out.append(f"- wartet auf Auflösung: {len(waiting)}")
    if skipped:
        top = sorted(skipped.items(), key=lambda kv: kv[1], reverse=True)[:TOP_SKIP_REASONS]
        out.append("- häufigste Ablehnungsgründe: " + "; ".join(
            f"{_esc(reason)} ({count})" for reason, count in top))
    if errors:
        out.append("- Fehler:")
        for err in errors[:MAX_ERRORS]:
            out.append(f"  - {_esc(str(err))}")
    else:
        out.append("- keine Fehler")
    return out


def _read_last_cycle(state_dir: Path) -> Optional[dict]:
    path = Path(state_dir) / "ledgers.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = (data.get("meta") or {}).get("last_cycle")
    return value if isinstance(value, dict) else None


def render_status(ledgers: dict, cfg: BotConfig, source: str,
                  last_cycle: Optional[dict] = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: List[str] = [
        f"# Papier-Bot: Stand ({source})",
        "",
        f"Stand: {now}",
        "",
        "> Nur Papiergeld. Es wird kein echtes Geld eingesetzt und keine Order gesendet.",
        "",
    ]
    lines += _accounts_section(ledgers, cfg) + [""]
    lines += _open_section(ledgers) + [""]
    lines += _closed_section(ledgers) + [""]
    if last_cycle:
        lines += _cycle_section(last_cycle) + [""]
    lines += [HONESTY_LINE, ""]
    return "\n".join(lines)


def write_status(cfg: BotConfig, source: str, last_cycle: dict | None = None) -> Path:
    """Lädt die Kontobücher, schreibt den Statusbericht und gibt den quellenspezifischen Pfad zurück."""
    store = LedgerStore(cfg.state_dir)
    ledgers = store.load(cfg.strategies, cfg.bankroll)
    if last_cycle is None:
        last_cycle = _read_last_cycle(cfg.state_dir)
    text = render_status(ledgers, cfg, source, last_cycle)

    report_dir = Path(cfg.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    source_path = report_dir / f"STATUS_{source}.md"
    atomic_write_text(source_path, text)
    atomic_write_text(report_dir / "STATUS.md", text)
    return source_path
