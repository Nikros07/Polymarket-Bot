"""Tests für paperbot.report. Offline, ohne Netzwerk, nur Papiergeld."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from paperbot.config import BotConfig
from paperbot.ledger import Ledger, LedgerStore
from paperbot.models import Fill, Signal
from paperbot.report import write_status

T0 = 1_760_000_000  # Unix-Sekunden, UTC


def _buy(led: Ledger, market_id: str, side: str, shares: float, price: float,
         question: str, ts: int) -> None:
    sig = Signal(strategy=led.strategy, market_id=market_id, side=side,
                 price=price, prob=None, reason="test", ts=ts)
    fill = Fill(market_id=market_id, side=side, shares=shares,
                avg_price=price, fee=0.0, ts=ts)
    led.open(sig, fill, question=question, category="politics")


def _build_state(state: Path) -> None:
    a = Ledger("a", 50.0)
    b = Ledger("b", 50.0)

    # a: Gewinner (YES bei 0,40, 10 Anteile, gewinnt) -> Ertrag positiv
    _buy(a, "m1", "YES", 10, 0.40, "Kurze Frage?", T0)
    a.mark("m1", 0.40)
    a.snapshot(T0)
    a.settle("m1", 1, T0 + 100)  # +6,00 €

    # a: offene Position mit langer Frage (wird gekürzt) und Pipe-Zeichen
    long_q = "Wird die Partei A | Partei B gewinnen bei der sehr langen Wahl im Jahr 2026 in Europa?"
    _buy(a, "m2", "NO", 5, 0.50, long_q, T0 + 200)
    a.mark("m2", 0.50)
    a.snapshot(T0 + 200)
    a.snapshot(T0 + 300)

    # b: Verlierer (YES bei 0,50, Ergebnis NO) -> Ertrag negativ
    _buy(b, "m3", "YES", 10, 0.50, "Verlierer-Markt", T0)
    b.mark("m3", 0.50)
    b.snapshot(T0)
    b.settle("m3", 0, T0 + 150)  # -5,00 €
    b.snapshot(T0 + 300)

    LedgerStore(state).save({"a": a, "b": b})


def test_write_status_full_report(tmp_path: Path):
    state = tmp_path / "state"
    _build_state(state)
    cfg = BotConfig(state_dir=state, report_dir=tmp_path / "reports", strategies=("a", "b"))

    out = write_status(cfg, "paper")

    assert out == tmp_path / "reports" / "STATUS_paper.md"
    assert out.exists()
    assert (tmp_path / "reports" / "STATUS.md").read_text(encoding="utf-8") == out.read_text(encoding="utf-8")
    text = out.read_text(encoding="utf-8")

    # Titel, Hinweis, Tabellenköpfe
    assert "# Papier-Bot: Stand (paper)" in text
    assert "> Nur Papiergeld. Es wird kein echtes Geld eingesetzt und keine Order gesendet." in text
    assert "## Konten (je 50 € Papiergeld)" in text
    assert "| Strategie | Wert (€) | Ertrag | Bargeld | investiert | offen | aufgelöst |" in text
    assert "| Trefferquote | max. Rückgang | Notbremse |" in text
    assert "## Offene Positionen" in text
    assert "| Strategie | Markt | Seite | Anteile | Preis | Einsatz (€) | seit |" in text
    assert "## Zuletzt aufgelöst" in text
    assert "Diese Übersicht beweist keinen Vorteil." in text

    # Ertrag: a gewinnt (+), b verliert (-)
    assert "+12.0 %" in text  # a: Wert 56,00 € -> +12 %
    assert "-10.0 %" in text  # b: 45 € Wert

    # Sortierung: a (Wert größer) steht vor b
    assert text.index("| a |") < text.index("| b |")

    # Lange Frage gekürzt mit "…", Pipe escaped, Originalfrage nicht vollständig
    assert "…" in text
    assert "Wird die Partei A | Partei B" not in text
    assert "Partei A \\| Partei B" in text or "Partei A \\|" in text
    assert "Wird die Partei A \\| Partei B gewinnen bei der sehr langen Wahl im Jahr 2026 in Europa?" not in text

    # Gewinn der aufgelösten Position mit Vorzeichen
    assert "+6.00" in text
    assert "-5.00" in text
    assert "| a | Kurze Frage? | YES | YES | +6.00 |" in text

    # Trefferquote: a 100 %, b 0 %
    assert "100.0 %" in text
    assert "0.0 %" in text

    # Kein letzter Zyklus, da weder Argument noch ledgers.json-Meta
    assert "## Letzter Zyklus" not in text


def test_truncated_question_has_ellipsis_and_max_length(tmp_path: Path):
    state = tmp_path / "state"
    _build_state(state)
    cfg = BotConfig(state_dir=state, report_dir=tmp_path / "reports", strategies=("a", "b"))
    text = write_status(cfg, "x").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if "| a | Wird die Partei A" in l)
    cell = line.split(" | ")[1]
    assert cell.endswith("…")
    assert len(cell.replace("\\|", "|")) <= 70


def test_empty_setup_shows_placeholders(tmp_path: Path):
    state = tmp_path / "empty"
    cfg = BotConfig(state_dir=state, report_dir=tmp_path / "reports", strategies=("a", "b"))
    text = write_status(cfg, "empty").read_text(encoding="utf-8")
    assert "Keine offenen Positionen." in text
    assert "Noch nichts aufgelöst." in text
    assert "## Letzter Zyklus" not in text
    # Ohne Abschlüsse gibt es keine Trefferquote
    assert "–" in text


def test_last_cycle_read_from_ledgers_meta(tmp_path: Path):
    state = tmp_path / "state"
    a = Ledger("a", 50.0)
    cycle = {
        "scanned": 42,
        "eligible": 7,
        "signals": 3,
        "opened": ["m-open-1"],
        "settled": [],
        "waiting": ["m-w1", "m-w2"],
        "skipped": {"zu teuer": 5, "zu dünn": 9, "Spread": 2},
        "errors": [],
    }
    LedgerStore(state).save({"a": a}, meta={"last_cycle": cycle})
    cfg = BotConfig(state_dir=state, report_dir=tmp_path / "reports", strategies=("a",))

    text = write_status(cfg, "cyc").read_text(encoding="utf-8")

    assert "## Letzter Zyklus" in text
    assert "- gescannt: 42" in text
    assert "- handelbar: 7" in text
    assert "- Signale: 3" in text
    assert "- gekauft: 1 (m-open-1)" in text
    assert "- abgerechnet: 0" in text
    assert "- wartet auf Auflösung: 2" in text
    assert "- keine Fehler" in text
    # Gründe nach Anzahl sortiert
    assert text.index("zu dünn (9)") < text.index("zu teuer (5)") < text.index("Spread (2)")


def test_explicit_last_cycle_overrides_meta_and_lists_errors(tmp_path: Path):
    state = tmp_path / "state"
    LedgerStore(state).save({"a": Ledger("a", 50.0)}, meta={"last_cycle": {"scanned": 1}})
    cfg = BotConfig(state_dir=state, report_dir=tmp_path / "reports", strategies=("a",))
    cycle = {"scanned": 99, "errors": ["Netzwerkfehler"]}

    text = write_status(cfg, "err", last_cycle=cycle).read_text(encoding="utf-8")

    assert "- gescannt: 99" in text
    assert "Netzwerkfehler" in text
    assert "- keine Fehler" not in text


def test_utc_timestamp_line(tmp_path: Path):
    cfg = BotConfig(state_dir=tmp_path / "s", report_dir=tmp_path / "r", strategies=("a",))
    text = write_status(cfg, "t").read_text(encoding="utf-8")
    stamp = next(l for l in text.splitlines() if l.startswith("Stand: "))
    parsed = datetime.strptime(stamp[len("Stand: "):], "%Y-%m-%d %H:%M UTC")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now - parsed).total_seconds()) < 120
