"""Der automatische Zyklus mit einer Speicher-Datenquelle (kein Netzwerk)."""
from dataclasses import replace

import pytest

from paperbot.config import BotConfig
from paperbot.data.fake import FakeClient
from paperbot.engine import eligible, run_cycle
from paperbot.ledger import LedgerStore
from paperbot.models import Book, BookLevel, Market
from paperbot.strategies import FavoriteStrategy, RandomSideControl

DAY = 86_400
NOW = 1_760_000_000


def _m(mid, price, **kw):
    base = dict(source="fake", market_id=mid, question=f"Will {mid} happen?", category="politics",
                created_ts=NOW - 10 * DAY, end_ts=NOW + 5 * DAY, end_known_in_advance=True,
                volume=50_000, liquidity=10_000, last_price=price)
    base.update(kw)
    return Market(**base)


def _cfg(tmp_path, **kw):
    return replace(BotConfig(state_dir=tmp_path, report_dir=tmp_path / "r"), **kw)


def _strats():
    fav = FavoriteStrategy(0.90, 0.98, name="favorite")
    return [fav, RandomSideControl(fav, name="random_control")]


def test_filters():
    cfg = BotConfig()
    assert eligible(_m("a", 0.9), NOW, cfg) is None
    assert eligible(_m("a", 0.9, volume=10), NOW, cfg) == "zu wenig Volumen"
    assert eligible(_m("a", 0.9, end_ts=NOW + 100 * DAY), NOW, cfg) == "Ende zu weit weg"
    assert eligible(_m("a", 0.9, end_ts=NOW + 3600), NOW, cfg) == "zu kurz vor Ende"
    assert eligible(_m("a", 0.9, end_ts=None), NOW, cfg) == "kein Enddatum"
    assert "unklare" in eligible(_m("a", 0.9, question="Will Trump say 'tariff'?"), NOW, cfg)


def test_cycle_opens_then_settles(tmp_path):
    client = FakeClient([_m("fav", 0.93), _m("mid", 0.5)])
    cfg = _cfg(tmp_path)
    r1 = run_cycle(client, cfg, NOW, _strats())
    assert any(o.startswith("favorite:fav:YES") for o in r1.opened)
    assert not any(":mid:" in o for o in r1.opened)          # kein Signal → kein Kauf
    led = LedgerStore(tmp_path).load(["favorite"], 50)["favorite"]
    assert led.cash < 50 and len(led.open_positions()) == 1

    # zweiter Lauf zur selben Zeit: kein doppelter Kauf
    r2 = run_cycle(client, cfg, NOW, _strats())
    assert not any(o.startswith("favorite:") for o in r2.opened)

    client.set_market("fav", closed=True, outcome=1, last_price=1.0)
    r3 = run_cycle(client, cfg, NOW + DAY, _strats())
    assert "favorite:fav" in r3.settled
    led = LedgerStore(tmp_path).load(["favorite"], 50)["favorite"]
    assert led.cash > 50 and not led.open_positions()


def test_no_signal_means_no_trade(tmp_path):
    """Lehre Apex: kein Codepfad erzwingt einen Trade."""
    client = FakeClient([_m(f"x{i}", 0.5) for i in range(20)])
    r = run_cycle(client, _cfg(tmp_path), NOW, _strats())
    assert r.opened == [] and r.signals == 0


def test_kill_switch_off_does_nothing(tmp_path):
    client = FakeClient([_m("fav", 0.93)])
    r = run_cycle(client, _cfg(tmp_path, enabled=False), NOW, _strats())
    assert r.opened == [] and "Notaus" in r.errors[0]
    assert client.calls == []


def test_wide_spread_and_polymarket_pending_resolution(tmp_path):
    client = FakeClient([_m("fav", 0.93)], half_spread=0.05)
    r = run_cycle(client, _cfg(tmp_path), NOW, _strats())
    assert r.opened == [] and r.skipped["Spread zu groß"] >= 1

    client = FakeClient([_m("fav", 0.93)], source="polymarket")
    cfg = _cfg(tmp_path / "pm")
    run_cycle(client, cfg, NOW, _strats())
    client.set_market("fav", closed=True, outcome=None, last_price=0.5, resolved_ts=NOW + DAY)
    r = run_cycle(client, cfg, NOW + DAY, _strats())
    assert "fav" in r.waiting and not r.settled
    r = run_cycle(client, cfg, NOW + 9 * DAY, _strats())    # nach der Frist: 50/50 abrechnen
    assert "favorite:fav" in r.settled


def test_kill_switch_sees_losses_from_same_cycle(tmp_path):
    """Review-Fund: die Notbremse muss den Verlust aus dem Abrechnen sofort sehen."""
    cfg = _cfg(tmp_path, stake_frac=0.12, max_stake_frac=0.12, kill_drawdown_frac=0.05)
    client = FakeClient([_m("fav", 0.93)])
    run_cycle(client, cfg, NOW, _strats())
    client.set_market("fav", closed=True, outcome=0, last_price=0.0)
    r = run_cycle(client, cfg, NOW + DAY, _strats())
    assert "favorite" in r.paused


def test_errors_in_one_strategy_do_not_stop_others(tmp_path):
    class Broken:
        name, needs_history, live_only = "broken", False, False

        def evaluate(self, view):
            raise RuntimeError("kaputt")

    client = FakeClient([_m("fav", 0.93)])
    r = run_cycle(client, _cfg(tmp_path), NOW, [Broken(), FavoriteStrategy(0.9, 0.98, name="favorite")])
    assert any("kaputt" in e for e in r.errors)
    assert any(o.startswith("favorite:") for o in r.opened)


def test_arbitrage_scanner_logs_gap_without_trading(tmp_path):
    class ArbClient(FakeClient):
        def book(self, market, side):
            price = 0.45 if side == "YES" else 0.50
            return Book(f"{market.market_id}:{side}", bids=(BookLevel(price - 0.01, 50),),
                        asks=(BookLevel(price, 40),))

    client = ArbClient([_m("gap", 0.47)], source="polymarket")
    r = run_cycle(client, _cfg(tmp_path), NOW, _strats())
    assert r.arb_checked == 1 and len(r.arb_found) == 1
    assert (tmp_path / "arbitrage.jsonl").exists()
    assert not any(":gap:" in o for o in r.opened)
