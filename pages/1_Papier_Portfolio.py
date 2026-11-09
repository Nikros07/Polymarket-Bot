"""
Streamlit-Unterseite: Papier-Portfolio.

Zeigt die Papier-Konten (Spielgeld) je Strategie, die offenen und aufgelösten
Positionen, die Freigabe-Prüfung und den Backtest-Bericht. Es wird kein echtes
Geld eingesetzt und keine Order gesendet.

Die Seite setzt bewusst kein st.set_page_config (das macht streamlit_app.py)
und nutzt kein unsafe_allow_html.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from paperbot.config import ROOT, BotConfig  # noqa: E402
from paperbot.gate import DISCLAIMER, backtest_verdicts, evaluate_gate  # noqa: E402
from paperbot.ledger import LedgerStore  # noqa: E402

SOURCES = ("kalshi", "polymarket", "manifold")


def _de(value: float, digits: int = 2) -> str:
    """Zahl im deutschen Format, z. B. 1.234,56."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _cfg(source: str) -> BotConfig:
    # Gleiche Ordnerstruktur wie paperbot/cli.py: je Quelle ein eigenes Konto-Verzeichnis.
    base = BotConfig.from_env()
    return dataclasses.replace(base, state_dir=base.state_dir / source)


def _render_backtest(source: str) -> None:
    results = ROOT / "results"
    md_path = results / f"BACKTEST_{source}.md"
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        # Bild-Zeilen aus dem Bericht entfernen; die PNG-Dateien werden separat gezeigt.
        lines = [line for line in text.splitlines() if not line.lstrip().startswith("![")]
        st.markdown("\n".join(lines))
        for img in sorted(results.glob(f"bt_{source}_*.png")):
            st.image(str(img), caption=img.stem)
    else:
        befehl = f"python -m paperbot backtest --source {source}"
        if source == "kalshi":
            befehl += " --limit 6000"
        st.info("Noch kein Backtest-Bericht vorhanden. Starte einen Backtest mit: " + befehl)


def _render_strategy_overview(ledgers: dict) -> None:
    for name, led in ledgers.items():
        equity = led.equity()
        start = led.start_bankroll
        ret_pct = (equity / start - 1.0) * 100.0 if start > 0 else 0.0
        st.subheader(name)
        c_wert, c_ertrag, c_offen, c_aufgel = st.columns(4)
        c_wert.metric("Wert €", f"{_de(equity)} €")
        c_ertrag.metric("Ertrag % vs. Start", f"{ret_pct:+.1f} %".replace(".", ","))
        c_offen.metric("Offen", len(led.open_positions()))
        c_aufgel.metric("Aufgelöst", len(led.closed_positions()))


def _render_equity_chart(ledgers: dict) -> None:
    st.subheader("Wertverlauf (Papiergeld)")
    series = []
    for name, led in ledgers.items():
        if not led.equity_history:
            continue
        index = pd.to_datetime([ts for ts, _ in led.equity_history], unit="s")
        values = [eq for _, eq in led.equity_history]
        s = pd.Series(values, index=index, name=name)
        series.append(s.groupby(level=0).last())
    if not series:
        st.info("Noch keine Verlaufsdaten vorhanden.")
        return
    df = pd.concat(series, axis=1).sort_index()
    st.line_chart(df)


def _render_open(ledgers: dict) -> None:
    rows = [
        {
            "Strategie": p.strategy,
            "Markt": p.question or p.market_id,
            "Seite": p.side,
            "Anteile": round(p.shares, 2),
            "Preis": round(p.avg_price, 3),
            "Einsatz": round(p.cost, 2),
        }
        for led in ledgers.values()
        for p in led.open_positions()
    ]
    if not rows:
        st.info("Keine offenen Papier-Positionen.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def _render_closed(ledgers: dict) -> None:
    rows = []
    for led in ledgers.values():
        for p in led.closed_positions():
            if p.outcome is None:
                result = "annulliert"
            elif p.payout and p.payout > 0:
                result = "gewonnen"
            else:
                result = "verloren"
            rows.append(
                {
                    "Strategie": p.strategy,
                    "Markt": p.question or p.market_id,
                    "Seite": p.side,
                    "Ergebnis": result,
                    "Gewinn": round(p.pnl, 2) if p.pnl is not None else None,
                }
            )
    if not rows:
        st.info("Noch keine aufgelösten Papier-Positionen.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def _render_gate(ledgers: dict, source: str) -> None:
    control = ledgers.get("random_control")
    verdicts = backtest_verdicts(ROOT / "results", source)
    for name, led in ledgers.items():
        if name == "random_control":
            continue
        verdict = evaluate_gate(led, control, verdicts.get(name))
        st.markdown(f"**{name}**: {'bestanden' if verdict.passed else 'nicht bestanden'}")
        for label, ok, detail in verdict.checks:
            st.write(f"{'✅' if ok else '❌'} {label}: {detail}")
    st.warning(DISCLAIMER)


def main() -> None:
    st.title("Papier-Portfolio")
    st.caption("Nur Papiergeld – es wird kein echtes Geld eingesetzt und keine Order gesendet.")

    source = st.selectbox("Quelle", SOURCES, key="source")
    cfg = _cfg(source)
    store = LedgerStore(cfg.state_dir)

    if not store.path.exists():
        st.info(
            "Noch keine Papier-Daten. Starte einen Zyklus mit: "
            f"python -m paperbot cycle --source {source}"
        )
        st.subheader("Backtest")
        _render_backtest(source)
        return

    ledgers = store.load(cfg.strategies, cfg.bankroll)
    _render_strategy_overview(ledgers)
    _render_equity_chart(ledgers)

    tab_open, tab_closed, tab_gate, tab_bt = st.tabs(
        ["Offen", "Aufgelöst", "Freigabe-Prüfung", "Backtest"]
    )
    with tab_open:
        _render_open(ledgers)
    with tab_closed:
        _render_closed(ledgers)
    with tab_gate:
        _render_gate(ledgers, source)
    with tab_bt:
        _render_backtest(source)


main()
