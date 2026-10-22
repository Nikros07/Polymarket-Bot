"""
Selbsttest des Prüfstands (Lehre Quant-Lab): Er muss einen eingebauten
Vorteil finden und bei fairen Märkten keinen bestätigen.
"""
from paperbot.backtest.engine import BTTrade, CostModel, run_strategy, simulate_bankroll
from paperbot.backtest.experiment import evaluate, run_experiment, verdict
from paperbot.backtest.synthetic import make_dataset
from paperbot.config import BotConfig
from paperbot.models import Market, PricePoint
from paperbot.strategies import FavoriteStrategy

DAY = 86_400


def test_planted_edge_is_found(tmp_path):
    ds = make_dataset(4000, bias=0.06, seed=3)
    s = run_experiment(ds, source="synthetic", cost=CostModel(0.01), cfg=BotConfig(state_dir=tmp_path),
                       out_dir=tmp_path, progress=lambda m: None)
    assert s["hypotheses"]["H1"]["verdict"] == "bestätigt"


def test_fair_markets_confirm_nothing(tmp_path):
    ds = make_dataset(4000, bias=0.0, seed=4)
    s = run_experiment(ds, source="synthetic", cost=CostModel(0.01), cfg=BotConfig(state_dir=tmp_path),
                       out_dir=tmp_path, progress=lambda m: None)
    for key, h in s["hypotheses"].items():
        assert h["verdict"] != "bestätigt", key


def test_strategy_never_trades_after_trading_end():
    m = Market(source="synthetic", market_id="x", question="q", created_ts=0, end_ts=10 * DAY,
               end_known_in_advance=True, closed=True, outcome=1, resolved_ts=5 * DAY)
    hist = [PricePoint(d * DAY, 0.5 if d < 6 else 0.95) for d in range(11)]
    trades = run_strategy([(m, hist)], FavoriteStrategy(0.9, 0.98))
    assert trades == []          # 0,95 erst nach der Auflösung → kein Einstieg


def test_returns_and_costs():
    t = BTTrade("s", "m", "q", "", 0, DAY, "YES", 0.9, None, 1)
    assert t.ret(CostModel(0.0)) == (1 - 0.9) / 0.9
    assert t.ret(CostModel(0.01)) < t.ret(CostModel(0.0))
    lost = BTTrade("s", "m", "q", "", 0, DAY, "NO", 0.9, None, 1)
    assert lost.ret(CostModel(0.01)) == -1.0


def test_bankroll_simulation_respects_cash():
    trades = [BTTrade("s", f"m{i}", "q", "", i * 60, 10 * DAY, "YES", 0.9, None, 1) for i in range(50)]
    cfg = BotConfig(max_open_positions=100, max_exposure_frac=1.0)
    curve = simulate_bankroll(trades, CostModel(0.01), cfg)
    assert (curve["cash"] >= -1e-9).all()
    assert curve.attrs["skipped"] > 0      # 50 € reichen nicht für 50 gleichzeitige Positionen


def test_verdict_needs_enough_trades():
    ev = evaluate("x", [BTTrade("s", "m", "q", "", 0, DAY, "YES", 0.9, None, 1)] * 5, CostModel(0.0))
    assert verdict(ev) == "zu wenige Trades"
