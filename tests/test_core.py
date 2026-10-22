"""Tests für die geldrelevanten Kernteile: Sicht, Gebühren, Broker, Risiko, Kontobuch."""
import math
from dataclasses import replace

import pytest

from paperbot.broker import simulate_buy
from paperbot.config import BotConfig
from paperbot.fees import FeeModel, polymarket_fee_per_share
from paperbot.ledger import Ledger, LedgerError, LedgerStore
from paperbot.models import Book, BookLevel, Fill, Market, PricePoint, Signal, side_price, side_won
from paperbot.risk import kelly_fraction_binary, kill_switch, size_position
from paperbot.view import LookaheadError, MarketInfo, MarketView

DAY = 86_400
T0 = 1_750_000_000


def _market(**kw):
    base = dict(source="synthetic", market_id="m1", question="Q?", category="politics",
                created_ts=T0, end_ts=T0 + 30 * DAY, end_known_in_advance=True,
                closed=True, outcome=1, resolved_ts=T0 + 30 * DAY)
    base.update(kw)
    return Market(**base)


# ── MarketView: kein Blick in die Zukunft ─────────────────────────────────

def test_view_cuts_history_and_blocks_future():
    hist = [PricePoint(T0 + d * DAY, 0.1 * d) for d in range(10)]
    view = MarketView(MarketInfo.from_market(_market()), hist, T0 + 4 * DAY + 10)
    assert view.price() == pytest.approx(0.4)
    assert len(view.history()) == 5
    with pytest.raises(LookaheadError):
        view.price_at(T0 + 5 * DAY)


def test_view_has_no_outcome_and_hides_unknown_end():
    m = _market(end_known_in_advance=False)
    info = MarketInfo.from_market(m)
    assert not hasattr(info, "outcome") and not hasattr(info, "resolved_ts")
    assert info.end_ts is None
    assert MarketInfo.from_market(m, live=True).end_ts == m.end_ts


def test_view_from_sorted_matches_constructor():
    hist = [PricePoint(T0 + d * 3600, 0.5 + d / 100) for d in range(30)]
    info = MarketInfo.from_market(_market())
    a = MarketView(info, list(reversed(hist)), T0 + 7200 * 5)
    b = MarketView.from_sorted(info, hist, [p.t for p in hist], T0 + 7200 * 5)
    assert a.history() == b.history() and a.price() == b.price()


def test_strategy_decision_does_not_change_when_future_is_cut():
    """Kausalitätsprüfung nach Quant-Lab: Entscheidung bei t hängt nur von Daten ≤ t ab."""
    from paperbot.strategies import FavoriteStrategy, MomentumStrategy, ReversionStrategy
    hist = [PricePoint(T0 + d * DAY, min(0.97, 0.5 + 0.04 * d)) for d in range(15)]
    info = MarketInfo.from_market(_market())
    for strat in (FavoriteStrategy(), MomentumStrategy(), ReversionStrategy(0.03, 1.0)):
        for k in range(2, 14):
            t = T0 + k * DAY
            full = strat.evaluate(MarketView(info, hist, t))
            cut = strat.evaluate(MarketView(info, hist[:k + 1], t))
            assert full == cut, (strat.name, k)


# ── Modelle und Gebühren ─────────────────────────────────────────────────

def test_side_helpers():
    assert side_price(0.3, "NO") == pytest.approx(0.7)
    assert side_won(1, "YES") and side_won(0, "NO") and not side_won(1, "NO")
    with pytest.raises(ValueError):
        side_won(2, "YES")


def test_polymarket_fee_peaks_at_half_and_vanishes_at_edges():
    peak = polymarket_fee_per_share(0.5, "politics") / 0.5
    assert peak == pytest.approx(0.010)
    assert polymarket_fee_per_share(0.95, "politics") / 0.95 == pytest.approx(0.04 * 0.95 * 0.05)
    assert polymarket_fee_per_share(0.5, "geopolitics") == 0.0
    assert FeeModel("none").per_share(0.5, "crypto") == 0.0
    with pytest.raises(ValueError):
        FeeModel("weird").per_share(0.5)


# ── Broker ───────────────────────────────────────────────────────────────

def _book(*asks):
    return Book("tok", bids=(BookLevel(0.5, 100),), asks=tuple(BookLevel(p, s) for p, s in asks))


def test_broker_walks_the_book_and_respects_budget():
    book = _book((0.90, 3), (0.92, 100))
    r = simulate_buy(book, 9.0, side="YES", market_id="m", ts=1, fee=FeeModel("none"), min_shares=5)
    f = r.fill
    assert f is not None
    assert f.cost <= 9.0 + 1e-9
    assert f.avg_price > 0.90                     # zweite Stufe wurde mitgenommen
    assert f.shares == pytest.approx(math.floor(f.shares * 100) / 100)


def test_broker_rejects_below_min_shares_and_above_max_price():
    assert simulate_buy(_book((0.9, 100)), 2.0, side="YES", market_id="m", ts=1,
                        fee=FeeModel("none"), min_shares=5).fill is None
    r = simulate_buy(_book((0.99, 100)), 50.0, side="YES", market_id="m", ts=1,
                     fee=FeeModel("none"), max_price=0.98)
    assert r.fill is None and "erreichbar" in r.reason
    assert simulate_buy(_book(), 10, side="YES", market_id="m", ts=1, fee=FeeModel("none")).fill is None


def test_broker_fills_exactly_minimum_size():
    """Review-Fund: 5·c / c ergab 4,999…, das Abrunden verwarf den Kauf still."""
    from paperbot.fees import FeeModel as FM
    for price, cat in ((0.82, ""), (0.92, ""), (0.95, "crypto"), (0.98, "sports")):
        fee = FM("polymarket")
        cps = price + fee.per_share(price, cat)
        r = simulate_buy(_book((price, 1000)), 5 * cps, side="YES", market_id="m", ts=1,
                         fee=fee, category=cat, min_shares=5, max_price=0.99)
        assert r.fill is not None and r.fill.shares == 5.0, (price, cat, r.reason)


def test_ledger_partial_resolution_pays_at_price():
    led = Ledger("s", 50)
    led.open(Signal("s", "y", "YES", 0.6, None), _fill("y", "YES", 10, 0.6, 0))
    led.open(Signal("s", "n", "NO", 0.4, None), _fill("n", "NO", 10, 0.4, 0))
    assert led.settle("y", None, T0, yes_payout=0.2).payout == pytest.approx(2.0)
    assert led.settle("n", None, T0, yes_payout=0.2).payout == pytest.approx(8.0)


def test_broker_charges_fee():
    r = simulate_buy(_book((0.5, 1000)), 10.0, side="YES", market_id="m", ts=1,
                     fee=FeeModel("polymarket"), category="crypto")
    assert r.fill.fee > 0
    assert r.fill.cost <= 10.0 + 1e-9


# ── Risiko ───────────────────────────────────────────────────────────────

def _sig(prob=None, price=0.9):
    return Signal("s", "m", "YES", price, prob, "test", 0)


def test_kelly_formula():
    assert kelly_fraction_binary(0.6, 0.5) == pytest.approx(0.2)
    assert kelly_fraction_binary(0.5, 0.5) == 0.0 or kelly_fraction_binary(0.5, 0.5) <= 0
    assert kelly_fraction_binary(0.9, 1.0) == 0.0


def test_fixed_stake_bumped_to_minimum_but_kelly_is_not():
    cfg = BotConfig(stake_frac=0.05, max_stake_frac=0.12)
    d = size_position(_sig(None), 0.9, equity=50, cash=50, open_positions=[], category="x", cfg=cfg)
    assert d.stake == pytest.approx(5 * 0.9)        # 2,50 € → auf 5 Anteile angehoben
    tiny_edge = size_position(_sig(0.905), 0.9, equity=50, cash=50, open_positions=[], category="x", cfg=cfg)
    assert tiny_edge.stake == 0 and "Mindestgröße" in tiny_edge.reason
    no_edge = size_position(_sig(0.85), 0.9, equity=50, cash=50, open_positions=[], category="x", cfg=cfg)
    assert no_edge.stake == 0


def test_caps_block_trades():
    cfg = BotConfig(max_open_positions=1)
    from paperbot.models import Position
    pos = Position("s", "m0", "q", "x", "YES", 5, 0.9, 0, 0, 0.9, None)
    assert size_position(_sig(), 0.9, equity=50, cash=50, open_positions=[pos], category="x",
                         cfg=cfg).stake == 0
    cfg = BotConfig(max_category_frac=0.1)
    big = Position("s", "m0", "q", "x", "YES", 5, 0.9, 0, 0, 0.9, None)   # 4,50 € in Kategorie x
    assert "Kategorie" in size_position(_sig(), 0.9, equity=50, cash=50, open_positions=[big],
                                        category="x", cfg=cfg).reason
    assert size_position(_sig(), 0.9, equity=50, cash=1, open_positions=[], category="x",
                         cfg=BotConfig()).reason == "zu wenig Bargeld"
    assert size_position(_sig(), 0.9, equity=50, cash=50, open_positions=[], category="x",
                         cfg=BotConfig(), paused=True).stake == 0


def test_kill_switch_is_rolling_and_resettable():
    cfg = BotConfig(kill_drawdown_frac=0.3, kill_window_days=30)
    hist = [(T0, 50.0), (T0 + DAY, 30.0)]
    assert kill_switch(hist, T0 + DAY, cfg)
    assert not kill_switch(hist, T0 + DAY, cfg, reset_ts=T0 + DAY)     # neu gemessen
    old_peak = [(T0, 50.0), (T0 + 40 * DAY, 30.0), (T0 + 41 * DAY, 30.0)]
    assert not kill_switch(old_peak, T0 + 41 * DAY, cfg)                # Hoch aus dem Fenster


# ── Kontobuch ────────────────────────────────────────────────────────────

def _fill(mid="m1", side="YES", shares=10.0, price=0.9, fee=0.01, ts=T0):
    return Fill(mid, side, shares, price, fee, ts)


def test_ledger_open_settle_and_cash_invariant():
    led = Ledger("s", 50)
    led.open(Signal("s", "m1", "YES", 0.9, None), _fill(), question="Q", category="x")
    assert led.cash == pytest.approx(50 - 9.01)
    with pytest.raises(LedgerError):
        led.open(Signal("s", "m1", "YES", 0.9, None), _fill())           # zweiter Einstieg
    with pytest.raises(LedgerError):
        led.open(Signal("s", "m2", "YES", 0.9, None), _fill("m2", shares=100))   # zu teuer
    led.mark("m1", 0.95)
    assert led.equity() == pytest.approx(50 - 9.01 + 9.5)
    p = led.settle("m1", 1, T0 + DAY)
    assert p.payout == 10 and p.pnl == pytest.approx(0.99)
    assert led.settle("m1", 1, T0 + 2 * DAY) is None                     # idempotent
    assert led.cash == pytest.approx(50.99)


def test_ledger_loss_and_void():
    led = Ledger("s", 50)
    led.open(Signal("s", "a", "NO", 0.9, None), _fill("a", "NO"))
    led.open(Signal("s", "b", "YES", 0.9, None), _fill("b"))
    led.settle("a", 1, T0)          # NO verliert
    led.settle("b", None, T0)       # annulliert → Einsatz zurück
    assert led.cash == pytest.approx(50 - 9.01)


def test_ledger_rejects_foreign_signal():
    with pytest.raises(LedgerError):
        Ledger("s", 50).open(Signal("other", "m1", "YES", 0.9, None), _fill())


def test_ledger_store_roundtrip_and_append_only_events(tmp_path):
    store = LedgerStore(tmp_path)
    led = Ledger("s", 50)
    led.open(Signal("s", "m1", "YES", 0.9, 0.95), _fill())
    led.snapshot(T0)
    led.snapshot(T0)                # Doppellauf ersetzt
    store.save({"s": led})
    again = store.load(["s", "t"], 50)
    assert again["s"].cash == pytest.approx(led.cash)
    assert again["s"].positions[0].signal_prob == 0.95
    assert len(again["s"].equity_history) == 1
    assert again["t"].cash == 50
    lines_before = (tmp_path / "events.jsonl").read_text().count("\n")
    again["s"].settle("m1", 0, T0 + DAY)
    store.save(again)
    assert (tmp_path / "events.jsonl").read_text().count("\n") == lines_before + 1


def test_kill_switch_pauses_and_resumes():
    cfg = BotConfig(pause_days=7)
    led = Ledger("s", 50)
    led.equity_history = [(T0, 50.0), (T0 + DAY, 30.0)]
    assert led.update_kill_switch(T0 + DAY, cfg)
    assert led.is_paused(T0 + 3 * DAY)
    assert not led.update_kill_switch(T0 + 9 * DAY, cfg)
    assert led.kill_reset_ts == T0 + 9 * DAY
