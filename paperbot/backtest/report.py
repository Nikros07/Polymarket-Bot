"""
Bericht zum Backtest: schreibt BACKTEST_<quelle>.md und drei PNG-Diagramme.

Eingabe ist das Summary-Dict aus paperbot/backtest/experiment.py (run_experiment).
Fehlende oder ungültige Werte (None, NaN) werden als "–" dargestellt.
Alle Ergebnisse sind Auswertungen mit Papiergeld, keine Handelsempfehlung.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # vor pyplot-Import: keine GUI, reines Rendern in Dateien

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import pandas as pd  # noqa: E402

DASH = "–"
HYPOTHESES = ("H1", "H2", "H3", "H4")
COST_CENTS = (0, 1, 2, 3)

LIMITS = (
    "Die Märkte wurden nach Endvolumen bzw. Teilnehmerzahl ausgewählt. "
    "Das ist Wissen vom Marktende (leichte Auswahlverzerrung).",
    "Preise aus der Historie sind Mittel- oder Letztkurse. Der echte Kaufpreis liegt um den "
    "halben Spread höher; das ist als Kosten angesetzt, Markttiefe aber nicht.",
    "Manifold ist ein Spielgeld-Markt. Ergebnisse dort sind ein Hinweis, kein Beweis für Polymarket.",
    "Ein bestätigtes Ergebnis heißt nur: auf diesen Daten nicht durch Zufall erklärbar. "
    "Es garantiert keine Gewinne in der Zukunft.",
    "Die LLM-Strategie ist hier nicht enthalten, weil ein Sprachmodell vergangene Ergebnisse kennen kann.",
)


# ── Formatierung ──────────────────────────────────────────────────────────────

def _f(x: Any) -> Optional[float]:
    """Zahl oder None (None, NaN, Inf und Nicht-Zahlen werden zu None)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _num(x: Any, dp: int = 2, suffix: str = "") -> str:
    v = _f(x)
    return DASH if v is None else f"{v:.{dp}f}{suffix}"


def _pct(x: Any, dp: int = 2) -> str:
    """Anteil 0..1 als Prozent."""
    v = _f(x)
    return DASH if v is None else f"{v * 100:.{dp}f} %"


def _ci(lo: Any, hi: Any) -> str:
    a, b = _f(lo), _f(hi)
    if a is None or b is None:
        return DASH
    return f"[{a * 100:.2f} %, {b * 100:.2f} %]"


def _cell(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return lines


def _hyp(summary: dict, key: str) -> dict:
    return (summary.get("hypotheses") or {}).get(key) or {}


def _oos(summary: dict, key: str) -> dict:
    return _hyp(summary, key).get("out_of_sample") or {}


def _present_hypotheses(summary: dict) -> List[str]:
    hyps = summary.get("hypotheses") or {}
    return [k for k in HYPOTHESES if k in hyps]


# ── Diagramme ─────────────────────────────────────────────────────────────────

def _no_data(ax) -> None:
    ax.text(0.5, 0.5, "keine Daten", ha="center", va="center", transform=ax.transAxes)


def _chart_calibration(summary: dict, out_dir: Path, source: str) -> str:
    name = f"bt_{source}_calibration.png"
    rows = []
    for r in summary.get("market_reliability") or []:
        n, mp, hr = _f(r.get("n")), _f(r.get("mean_prob")), _f(r.get("hit_rate"))
        if n is not None and n > 0 and mp is not None and hr is not None:
            rows.append((mp, hr, int(n)))

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1, label="perfekte Kalibrierung")
    if rows:
        max_n = max(n for _, _, n in rows)
        sizes = [30 + 400 * n / max_n for _, _, n in rows]
        ax.scatter([p for p, _, _ in rows], [h for _, h, _ in rows], s=sizes, alpha=0.7,
                   color="#1f77b4", edgecolor="black", linewidth=0.5,
                   label="Preis-Bins (Größe = Anzahl Märkte)")
    else:
        _no_data(ax)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Marktpreis (YES)")
    ax.set_ylabel("Tatsächliche YES-Quote")
    ax.set_title("Wie gut sind Marktpreise kalibriert? (Out-of-Sample)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=120)
    plt.close(fig)
    return name


def _chart_equity(summary: dict, out_dir: Path, source: str) -> str:
    name = f"bt_{source}_equity.png"
    fig, ax = plt.subplots(figsize=(8, 4.5))
    drawn = 0
    for strategy, info in (summary.get("bankroll") or {}).items():
        info = info or {}
        csv_path = out_dir / f"equity_{source}_{strategy}.csv"
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path)
        except (OSError, ValueError):
            continue
        if not {"ts", "equity"} <= set(df.columns):
            continue
        ts = pd.to_datetime(pd.to_numeric(df["ts"], errors="coerce"), unit="s")
        eq = pd.to_numeric(df["equity"], errors="coerce")
        ok = ts.notna() & eq.notna()
        if not ok.any():
            continue
        (line,) = ax.plot(ts[ok], eq[ok], linewidth=1.5, label=strategy)
        start = _f(info.get("start"))
        if start is not None:
            ax.axhline(start, linestyle="--", linewidth=1, color=line.get_color(), alpha=0.6)
        drawn += 1
    if drawn:
        ax.legend(loc="best", fontsize=8)
    else:
        _no_data(ax)
    ax.set_title("50 € Papiergeld im Out-of-Sample-Zeitraum")
    ax.set_ylabel("€")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=120)
    plt.close(fig)
    return name


def _chart_costs(summary: dict, out_dir: Path, source: str) -> str:
    name = f"bt_{source}_costs.png"
    series = []
    for key in _present_hypotheses(summary):
        oos = _oos(summary, key)
        if not oos:
            continue
        by_cost = oos.get("by_cost") or {}
        vals = [_f(by_cost.get(f"{c / 100:.2f}")) for c in COST_CENTS]
        if all(v is None for v in vals):
            continue
        chosen = _hyp(summary, key).get("chosen")
        label = f"{key} ({chosen})" if chosen else key
        series.append((label, [math.nan if v is None else v for v in vals]))

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = list(range(len(COST_CENTS)))
    if series:
        width = 0.8 / len(series)
        for i, (label, vals) in enumerate(series):
            offset = (i - (len(series) - 1) / 2) * width
            ax.bar([xi + offset for xi in x], vals, width=width * 0.9, label=label)
        ax.legend(loc="best", fontsize=8)
    else:
        _no_data(ax)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{c} ct" for c in COST_CENTS])
    ax.set_xlabel("Kosten: halber Spread (Cent)")
    ax.set_ylabel("Ø Ertrag pro €")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    ax.set_title("Ertrag pro Euro je nach Kosten")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=120)
    plt.close(fig)
    return name


# ── Markdown ──────────────────────────────────────────────────────────────────

def _section_intro(summary: dict, source: str) -> List[str]:
    cost = summary.get("cost") or {}
    hs = _f(cost.get("half_spread"))
    spread = DASH if hs is None else f"{hs * 100:g} ct"
    fee = cost.get("fee")
    fee_txt = DASH if fee in (None, "") else str(fee)
    return [
        f"# Backtest: {source}",
        "",
        f"Märkte insgesamt: {_num(summary.get('n_markets'), 0)}, Training (In-Sample): "
        f"{_num(summary.get('n_train'), 0)}, Test (Out-of-Sample): {_num(summary.get('n_test'), 0)}. "
        f"Kosten-Annahmen: halber Spread {spread} je Seite, Gebühren-Modell: {fee_txt}. "
        "Alle Schwellen wurden vor dem Test in docs/HYPOTHESEN.md festgelegt.",
        "",
    ]


def _section_oos(summary: dict) -> List[str]:
    rows = []
    for key in _present_hypotheses(summary):
        h = _hyp(summary, key)
        oos = _oos(summary, key)
        rows.append([
            key,
            h.get("chosen") or DASH,
            _num(oos.get("n"), 0),
            _pct(oos.get("mean")),
            _ci(oos.get("ci_lo"), oos.get("ci_hi")),
            _num(oos.get("p_value"), 4),
            _pct(oos.get("hit_rate"), 1),
            _pct(oos.get("mean_price"), 1),
            _pct(oos.get("worst"), 2),
            h.get("verdict") or DASH,
        ])
    out = ["## Ergebnis auf ungesehenen Daten (Out-of-Sample)", ""]
    out += _table(["Hypothese", "gewählte Variante", "Trades", "Ø Ertrag pro €", "95 %-Intervall",
                   "p-Wert", "Trefferquote", "Ø Preis", "größter Verlust", "Urteil"], rows)
    out += ["", f"Signifikanzschwelle nach Bonferroni: p ≤ {_num(summary.get('bonferroni_threshold'), 4)}", ""]
    return out


def _section_controls(summary: dict) -> List[str]:
    rows = []
    for key in _present_hypotheses(summary):
        for c in _hyp(summary, key).get("controls") or []:
            rows.append([
                c.get("name") or key,
                _num(c.get("n"), 0),
                _pct(c.get("mean")),
                _ci(c.get("ci_lo"), c.get("ci_hi")),
                _pct(c.get("hit_rate"), 1),
            ])
    out = ["## Kontrollen (gleiche Einstiegszeitpunkte)", ""]
    if rows:
        out += _table(["Kontrolle", "Trades", "Ø Ertrag pro €", "95 %-Intervall", "Trefferquote"], rows)
    else:
        out.append("Keine Kontrollen vorhanden.")
    out.append("")
    return out


def _section_costs(summary: dict, source: str, chart: str) -> List[str]:
    rows = []
    for key in _present_hypotheses(summary):
        oos = _oos(summary, key)
        by_cost = oos.get("by_cost") or {}
        chosen = _hyp(summary, key).get("chosen")
        label = f"{key} ({chosen})" if chosen else key
        rows.append([label] + [_pct(by_cost.get(f"{c / 100:.2f}")) for c in COST_CENTS])
    out = ["## Kosten-Sensitivität", ""]
    out += _table(["Hypothese", "0 ct", "1 ct", "2 ct", "3 ct"], rows)
    out += ["", "Ø Ertrag pro € je Kostenstufe (halber Spread):", "", f"![Kosten je Hypothese]({chart})", ""]
    return out


def _section_bankroll(summary: dict, chart: str) -> List[str]:
    bankroll = summary.get("bankroll") or {}
    rows = []
    starts = []
    reasons = []
    for name, b in bankroll.items():
        b = b or {}
        if _f(b.get("start")) is not None:
            starts.append(_f(b.get("start")))
        rows.append([
            name,
            _num(b.get("final_equity"), 2),
            _pct(b.get("max_drawdown"), 1),
            _num(b.get("taken"), 0),
            _num(b.get("skipped"), 0),
            _pct(b.get("mc_prob_ruin"), 1),
            f"{_num(b.get('mc_final_median'), 2)} / {_num(b.get('mc_final_p5'), 2)} / "
            f"{_num(b.get('mc_final_p95'), 2)}",
        ])
        ok = b.get("mc_ok")
        if ok is not None and not ok:
            reasons.append(f"Monte-Carlo für {name} nicht belastbar: {b.get('mc_reason') or DASH}")
    out = ["## 50 € Papiergeld nachgespielt", ""]
    if starts:
        out += [f"Startkapital je Strategie: {_num(starts[0], 2)} €.", ""]
    out += _table(["Strategie", "Endwert (€)", "max. Rückgang", "gespielt", "ausgelassen",
                   "Ruin-Risiko (−50 %)", "Median / 5 % / 95 % (Monte-Carlo)"], rows)
    out.append("")
    few = [n for n, b in (summary.get("bankroll") or {}).items()
           if isinstance(b, dict) and (b.get("taken") or 0) < 100]
    if few:
        out += [f"> Achtung: {', '.join(few)} hat im Einzelpfad weniger als 100 Trades gespielt "
                "(Limits bei 50 €). Ein einzelner Pfad mit so wenigen Trades ist Zufall. "
                "Maßgeblich sind der Ø Ertrag oben und die Monte-Carlo-Spalte über alle Trades.", ""]
    out += reasons
    if reasons:
        out.append("")
    out += [f"![Papiergeld-Verlauf]({chart})", ""]
    return out


def _section_calibration(summary: dict, chart: str) -> List[str]:
    rows = []
    for r in summary.get("market_reliability") or []:
        lo, hi = _f(r.get("bin_lo")), _f(r.get("bin_hi"))
        label = DASH if lo is None or hi is None else f"{lo:.1f}–{hi:.1f}"
        rows.append([label, _num(r.get("n"), 0), _pct(r.get("mean_prob"), 1), _pct(r.get("hit_rate"), 1)])
    out = ["## Kalibrierung der Marktpreise", ""]
    if rows:
        out += _table(["Marktpreis (YES)", "Märkte", "Ø Marktpreis", "Tatsächliche YES-Quote"], rows)
    else:
        out.append("Keine Kalibrierungsdaten vorhanden.")
    out += ["", f"Brier-Score der Marktpreise (Out-of-Sample): {_num(summary.get('market_brier_test'), 4)}",
            "", f"![Kalibrierung der Marktpreise]({chart})", ""]
    return out


def _section_in_sample(summary: dict) -> List[str]:
    out = ["## Auswahl im In-Sample", ""]
    for key in _present_hypotheses(summary):
        h = _hyp(summary, key)
        out += [f"### {key}", ""]
        rows = [[e.get("name") or DASH, _num(e.get("n"), 0), _pct(e.get("mean"))]
                for e in h.get("in_sample") or []]
        if rows:
            out += _table(["Variante", "Trades", "Ø Ertrag pro €"], rows)
        else:
            out.append("Keine In-Sample-Varianten vorhanden.")
        out += ["", f"Gewählt: {h.get('chosen') or DASH}", ""]
    return out


def _section_limits() -> List[str]:
    out = ["## Grenzen dieses Tests", ""]
    out += [f"- {text}" for text in LIMITS]
    out.append("")
    return out


def write_backtest_report(summary: dict, out_dir: Path) -> Path:
    """Schreibt BACKTEST_<source>.md und die Diagramme nach out_dir; gibt den Pfad der Markdown-Datei zurück."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = str(summary.get("source") or "unbekannt")

    cal = _chart_calibration(summary, out_dir, source)
    equity = _chart_equity(summary, out_dir, source)
    costs = _chart_costs(summary, out_dir, source)

    lines: List[str] = []
    lines += _section_intro(summary, source)
    lines += _section_oos(summary)
    lines += _section_controls(summary)
    lines += _section_costs(summary, source, costs)
    lines += _section_bankroll(summary, equity)
    lines += _section_calibration(summary, cal)
    lines += _section_in_sample(summary)
    lines += _section_limits()

    path = out_dir / f"BACKTEST_{source}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
