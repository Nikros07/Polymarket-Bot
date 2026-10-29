"""Tests für die Wetter-Spezialisierung (H8): Zukunftssperre, Spannen, Modell, Strategie, Dienst."""
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from paperbot.backtest.engine import CostModel, run_strategy
from paperbot.backtest.experiment import evaluate
from paperbot.fees import FeeModel
from paperbot.models import Market, PricePoint
from paperbot.view import LookaheadError, MarketInfo, MarketView
from paperbot.weather import (ForecastBook, TempModel, WeatherStrategy, available_from, bracket,
                              daily_max, training_rows)

DAY = 86_400
HOUR = 3_600
D = date(2025, 7, 10)


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


def _market(strike_type="between", lo=80.0, hi=81.0, outcome=1, day=D, mid="X"):
    open_ts = _ts(datetime(day.year, day.month, day.day, 14, tzinfo=timezone.utc)) - DAY
    tag = day.strftime("%y%b%d").upper()
    return Market(source="kalshi", market_id=f"KXHIGHNY-{tag}-{mid}", question="q",
                  category="climate and weather", created_ts=open_ts, end_ts=open_ts + 39 * HOUR,
                  closed=True, outcome=outcome, resolved_ts=open_ts + 45 * HOUR,
                  event_id=f"KXHIGHNY-{tag}", series="KXHIGHNY", strike_type=strike_type,
                  floor_strike=lo, cap_strike=hi)


def test_brackets_match_kalshi_subtitles():
    info = lambda m: MarketInfo.from_market(m)
    assert bracket(info(_market("between", 80, 81))) == (79.5, 81.5)    # „80° to 81°“
    assert bracket(info(_market("greater", 87, None))) == (87.5, math.inf)   # „88° or above“
    assert bracket(info(_market("less", None, 80))) == (-math.inf, 79.5)     # „79° or below“
    assert bracket(info(_market("", None, None))) is None


def test_forecast_is_locked_until_issued():
    book = ForecastBook({("KXHIGHNY", D.isoformat()): 82.0})
    t = available_from("KXHIGHNY", D)
    # D−1 06:00 New York (Sommerzeit, UTC−4) = 10:00 UTC
    assert t == _ts(datetime(2025, 7, 9, 10, tzinfo=timezone.utc))
    with pytest.raises(LookaheadError):
        book.get("KXHIGHNY", D, t - 1)
    assert book.get("KXHIGHNY", D, t) == 82.0
    assert ForecastBook.from_json(book.to_json()).highs == book.highs


def test_daily_max_needs_full_days():
    times = [f"2025-07-10T{h:02d}:00" for h in range(24)] + ["2025-07-11T00:00"]
    temps = [70 + h for h in range(24)] + [60]
    assert daily_max(times, temps) == {"2025-07-10": 93}
    temps[5] = None
    assert daily_max(times, temps) == {}


def test_model_fit_recovers_bias_and_sigma():
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(3000):
        mu = rng.uniform(60, 95)
        truth = mu + 1.5 + rng.normal(0, 2.5)
        lo = math.floor(mu) - 0.5 + rng.integers(-4, 4) * 2
        rows.append((mu, lo, lo + 2.0, int(lo <= truth < lo + 2.0)))
    m = TempModel.fit(rows)
    assert m.bias == pytest.approx(1.5, abs=0.3) and m.sigma == pytest.approx(2.5, abs=0.4)
    with pytest.raises(ValueError):
        TempModel.fit(rows[:10])


def _hist(m, p=0.30, bid=0.29, ask=0.31):
    return [PricePoint(m.created_ts + h * HOUR, p, bid, ask) for h in range(1, 40)]


def test_strategy_waits_for_forecast_and_is_causal():
    m = _market()
    book = ForecastBook({("KXHIGHNY", D.isoformat()): 80.5})
    strat = WeatherStrategy(TempModel(0.0, 1.5), book, min_edge=0.05)
    info = MarketInfo.from_market(m)
    hist = _hist(m)
    early = available_from("KXHIGHNY", D) - HOUR
    assert strat.evaluate(MarketView(info, hist, early)) is None       # vor Ausgabe: nichts
    for k in range(10, 38):
        t = m.created_ts + k * HOUR
        full = strat.evaluate(MarketView(info, hist, t))
        cut = strat.evaluate(MarketView(info, hist[:k], t))
        assert full == cut, k
    sig = strat.evaluate(MarketView(info, hist, m.created_ts + 20 * HOUR))
    assert sig is not None and sig.side == "YES" and sig.prob > 0.4     # Modell ~0,49 vs. 0,31


def test_strategy_without_model_never_trades():
    m = _market()
    book = ForecastBook({("KXHIGHNY", D.isoformat()): 80.5})
    view = MarketView(MarketInfo.from_market(m), _hist(m), m.created_ts + 20 * HOUR)
    assert WeatherStrategy(None, book).evaluate(view) is None


def test_planted_forecast_edge_is_found_and_fair_market_is_not():
    """Selbsttest: Markt ignoriert die Vorhersage → Vorteil. Markt kennt sie → keiner."""
    rng = np.random.default_rng(5)
    book, ds_bad, ds_fair = ForecastBook(), [], []
    model = TempModel(0.0, 2.0)
    for i in range(400):
        day = D + timedelta(days=i)
        mu = float(rng.uniform(60, 95))
        book.highs[("KXHIGHNY", day.isoformat())] = mu
        truth = mu + rng.normal(0, 2.0)
        for j, lo in enumerate(np.arange(math.floor(mu) - 6.5, math.floor(mu) + 6.5, 2.0)):
            hi = lo + 2.0
            m = _market("between", lo + 0.5, hi - 0.5, int(lo <= truth < hi), day, mid=f"B{j}")
            fair = model.prob_yes(mu, lo, hi)
            for p, ds in ((0.15, ds_bad), (min(0.97, max(0.03, fair)), ds_fair)):
                ds.append((m, _hist(m, p, max(0.0, p - 0.01), p + 0.01)))
    strat = WeatherStrategy(model, book, min_edge=0.05)
    cost = CostModel(0.01, fee=FeeModel("kalshi"))
    bad = evaluate("bad", run_strategy(ds_bad, strat, start_offset_hours=6, max_spread=0.1), cost, clustered=True)
    fair = run_strategy(ds_fair, strat, start_offset_hours=6, max_spread=0.1)
    assert bad.n > 100 and bad.mean > 0 and bad.ci_lo > 0
    assert len(fair) == 0          # fairer Markt + Kosten → kein Signal


def test_training_rows_read_forecast_at_issue_time():
    m = _market(outcome=0)
    book = ForecastBook({("KXHIGHNY", D.isoformat()): 70.0})
    assert training_rows([(m, [])], book) == [(70.0, 79.5, 81.5, 0)]
    assert training_rows([(m, [])], ForecastBook()) == []


def test_serve_health_and_one_cycle(monkeypatch, tmp_path):
    import paperbot.serve as serve
    monkeypatch.setenv("PAPERBOT_REPORT_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(serve, "run_one", lambda src: calls.append(src) or {"opened": [], "settled": [], "errors": []})
    assert serve.serve("kalshi", interval_min=0.001, port=0, max_cycles=1) == 0
    assert calls == ["kalshi"]
    st = serve._State("kalshi", 60, tmp_path / "x.md")
    assert st.health()["ok"] and st.health()["paper_only"] is True
    st.started -= 10_000
    assert not st.health()["ok"]          # seit Langem kein erfolgreicher Zyklus
