"""Tests für pages/1_Papier_Portfolio.py mit streamlit.testing.v1.AppTest. Offline, ohne Netzwerk."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")      # im GitHub-Actions-Lauf ist Streamlit nicht installiert
from streamlit.testing.v1 import AppTest  # noqa: E402

from paperbot.ledger import Ledger, LedgerStore
from paperbot.models import Fill, Signal

PAGE = Path(__file__).resolve().parents[1] / "pages" / "1_Papier_Portfolio.py"
T0 = 1_750_000_000
T1 = T0 + 86_400


@pytest.fixture
def state_root(tmp_path, monkeypatch):
    # BotConfig.from_env liest PAPERBOT_STATE_DIR; die Seite hängt die Quelle an.
    monkeypatch.setenv("PAPERBOT_STATE_DIR", str(tmp_path))
    return tmp_path


def _seed_polymarket(state_dir: Path) -> None:
    fav = Ledger("favorite", 50.0)
    fav.open(
        Signal(strategy="favorite", market_id="m1", side="YES", price=0.4, prob=0.6, ts=T0),
        Fill(market_id="m1", side="YES", shares=10, avg_price=0.4, fee=0.1, ts=T0),
        question="Offene Frage", category="politics",
    )
    fav.snapshot(T0)
    fav.open(
        Signal(strategy="favorite", market_id="m2", side="NO", price=0.5, prob=0.6, ts=T0),
        Fill(market_id="m2", side="NO", shares=10, avg_price=0.5, fee=0.0, ts=T0),
        question="Geschlossene Frage", category="sports",
    )
    fav.settle("m2", 1, T1)   # NO verliert, YES gewinnt
    fav.snapshot(T1)
    rc = Ledger("random_control", 50.0)
    LedgerStore(state_dir).save({"favorite": fav, "random_control": rc})


def test_empty_state_shows_info_and_no_exception(state_root):
    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()

    assert not at.exception
    messages = [i.value for i in at.info]
    assert any("Noch keine Papier-Daten" in m for m in messages)
    assert not at.metric


def test_page_renders_title_and_metrics_with_ledgers(state_root):
    _seed_polymarket(state_root / "polymarket")

    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()

    assert not at.exception
    assert at.title[0].value == "Papier-Portfolio"
    assert len(at.metric) >= 4
    labels = [m.label for m in at.metric]
    assert "Wert €" in labels
    assert "Aufgelöst" in labels
