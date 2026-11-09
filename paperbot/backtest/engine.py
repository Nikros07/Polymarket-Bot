"""
Ereignis-Backtest für binäre Märkte.

Ablauf je Markt:
1. Entscheidungszeitpunkte auf festem 24-h-Raster ab Marktstart + 1 Tag,
   bis 1 Stunde vor dem Handelsende (Ende oder Auflösung, was früher kommt).
   Das Handelsende begrenzt nur das Raster; die Strategie sieht es nicht.
2. Die Strategie bekommt pro Zeitpunkt eine auf diesen Zeitpunkt gekürzte
   MarketView. Das erste Signal ist der Einstieg.
3. Gehalten bis zur Auflösung: Gewinn = (1 − c) / c pro eingesetztem Euro,
   Verlust = −1, mit c = Preis + halber Spread + Gebühr. Ist der echte
   Briefkurs der Seite bekannt (Kalshi-Kerzen), ersetzt er Preis + halben
   Spread; dazu kommt nur der Schlupf aus der Sensitivität.

Kosten werden erst bei der Auswertung angewendet, damit dieselben Trades mit
verschiedenen Kostenannahmen (Sensitivität) bewertet werden können.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from paperbot.config import BotConfig
from paperbot.fees import FeeModel
from paperbot.models import Market, PricePoint, side_won
from paperbot.strategies.base import Strategy
from paperbot.view import MarketInfo, MarketView

HOUR = 3_600
DAY = 86_400
MAX_TRADABLE = 0.99      # Kalshi-Höchstpreis; Brief darüber (1,00) = kein Angebot

Dataset = List[Tuple[Market, List[PricePoint]]]


@dataclass(frozen=True)
class CostModel:
    half_spread: float = 0.01      # angenommen, wenn kein echter Briefkurs bekannt ist
    fee: FeeModel = FeeModel("none")
    max_price: float = 0.99
    slippage: float = 0.0          # Aufschlag auf den echten Briefkurs (Sensitivität)

    def cost_per_share(self, side_price: float, category: str = "",
                       quoted: Optional[float] = None) -> float:
        if quoted is not None:
            # Echter Briefkurs: NICHT deckeln. Ein Deckel machte aus „kein Angebot“ (1,00)
            # einen Kauf zu 0,99 (Review 2026-11-03). Nicht kaufbare Fälle filtert
            # run_strategy; Schlupf darüber hinaus macht den Trade nur teurer.
            fill = quoted + self.slippage
            return fill + self.fee.per_share(min(fill, 0.999), category)
        fill = min(self.max_price, side_price + self.half_spread + self.slippage)
        return fill + self.fee.per_share(fill, category)


@dataclass(frozen=True)
class BTTrade:
    strategy: str
    market_id: str
    question: str
    category: str
    entry_ts: int
    resolved_ts: int
    side: str
    side_price: float
    prob: Optional[float]
    outcome: int
    quoted_cost: Optional[float] = None   # echter Briefkurs der Seite bei Einstieg
    event_id: str = ""                    # für Bootstrap über Events

    @property
    def won(self) -> bool:
        return side_won(self.outcome, self.side)

    @property
    def hold_days(self) -> float:
        return max(0.0, (self.resolved_ts - self.entry_ts) / DAY)

    @property
    def cluster(self) -> str:
        return self.event_id or self.market_id

    def ret(self, cost: CostModel) -> float:
        c = cost.cost_per_share(self.side_price, self.category, self.quoted_cost)
        return (1.0 - c) / c if self.won else -1.0


def trading_end(market: Market, history: Sequence[PricePoint]) -> int:
    ends = [t for t in (market.end_ts, market.resolved_ts) if t]
    return min(ends) if ends else history[-1].t


def decision_times(market: Market, history: Sequence[PricePoint],
                   grid_hours: int = 24, start_offset_hours: int = 24) -> range:
    start = (market.created_ts if market.created_ts is not None else history[0].t)
    start += start_offset_hours * HOUR
    stop = trading_end(market, history) - HOUR
    return range(start, stop, grid_hours * HOUR)


def run_strategy(dataset: Dataset, strategy: Strategy, grid_hours: int = 24,
                 start_offset_hours: int = 24, max_spread: Optional[float] = None,
                 max_quote_periods: Optional[float] = None) -> List[BTTrade]:
    """Nur bei bekanntem Geld/Brief (Kalshi) gilt ein Zeitpunkt als nicht handelbar, wenn
    - der Spread über max_spread liegt,
    - die Seite kein Angebot hat (Briefkurs über MAX_TRADABLE, z. B. 1,00),
    - der letzte gültige Kurs älter ist als max_quote_periods Kerzenperioden.
    Das Signal verfällt dann, die Strategie darf beim nächsten Rasterpunkt wieder."""
    if getattr(strategy, "live_only", False):
        raise ValueError(f"{strategy.name} ist nur live prüfbar")
    trades: List[BTTrade] = []
    for market, history in dataset:
        if market.outcome not in (0, 1) or not history:
            continue
        info = MarketInfo.from_market(market)
        ts = [p.t for p in history]
        resolved = market.resolved_ts or trading_end(market, history)
        period = _period(ts)
        for t in decision_times(market, history, grid_hours, start_offset_hours):
            view = MarketView.from_sorted(info, history, ts, t)
            if view.price() is None:
                continue
            sig = strategy.evaluate(view)
            if sig is None:
                continue
            last = view.last_point()
            quoted = last.side_ask(sig.side) if last is not None else None
            if quoted is not None:
                if quoted > MAX_TRADABLE + 1e-9:
                    continue                           # kein Angebot auf dieser Seite
                if max_spread is not None and last.spread > max_spread:
                    continue
                if (max_quote_periods is not None and period
                        and t - last.t > max_quote_periods * period):
                    continue                           # Kurs veraltet
            trades.append(BTTrade(
                strategy=strategy.name, market_id=market.market_id, question=market.question,
                category=market.category, entry_ts=t, resolved_ts=max(resolved, t),
                side=sig.side, side_price=sig.price, prob=sig.prob, outcome=int(market.outcome),
                quoted_cost=quoted, event_id=market.event_id,
            ))
            break
    return trades


def _period(ts: Sequence[int]) -> Optional[int]:
    """Kerzenperiode eines Marktes = kleinster Abstand zweier Punkte (None bei < 2 Punkten)."""
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    return min(gaps) if gaps else None


def trades_frame(trades: Iterable[BTTrade], cost: CostModel) -> pd.DataFrame:
    rows = [{
        "strategy": t.strategy, "market_id": t.market_id, "question": t.question,
        "category": t.category, "entry_ts": t.entry_ts, "resolved_ts": t.resolved_ts,
        "side": t.side, "side_price": t.side_price,
        "quoted_cost": float("nan") if t.quoted_cost is None else t.quoted_cost,
        "event_id": t.event_id,
        "prob": float("nan") if t.prob is None else t.prob, "outcome": t.outcome,
        "won": t.won, "hold_days": t.hold_days, "ret": t.ret(cost),
    } for t in trades]
    return pd.DataFrame(rows)


def simulate_bankroll(trades: Sequence[BTTrade], cost: CostModel, cfg: BotConfig) -> pd.DataFrame:
    """Spielt die Trades chronologisch mit echtem Startkapital und den Risiko-Regeln nach.

    Einsatz: fester Anteil der Equity (Bargeld + Einstandswert offener Positionen),
    mindestens die Mindestgröße, höchstens max_stake_frac. Ohne genug Bargeld
    oder bei vollen Limits (Anzahl, gesamt, je Kategorie) wird der Trade
    ausgelassen. Die Notbremse wird hier NICHT nachgespielt.
    """
    events = []
    for i, t in enumerate(trades):
        events.append((t.entry_ts, 1, i))
        events.append((t.resolved_ts, 0, i))   # bei Gleichstand erst auszahlen, dann kaufen
    events.sort()
    cash = cfg.bankroll
    open_cost: dict = {}
    rows = []
    taken = skipped = 0
    for ts, kind, i in events:
        t = trades[i]
        if kind == 1:
            equity = cash + sum(open_cost.values())
            c = cost.cost_per_share(t.side_price, t.category, t.quoted_cost)
            min_notional = cfg.min_order_shares * c
            cap = cfg.max_stake_frac * equity
            stake = min(cfg.stake_frac * equity, cap)
            if stake < min_notional:
                stake = min_notional if min_notional <= cap else 0.0
            cat = (t.category or "unbekannt").lower()
            in_cat = sum(v for j, v in open_cost.items()
                         if (trades[j].category or "unbekannt").lower() == cat)
            ok = (stake > 0 and stake <= cash + 1e-9
                  and len(open_cost) < cfg.max_open_positions
                  and sum(open_cost.values()) + stake <= cfg.max_exposure_frac * equity
                  and in_cat + stake <= cfg.max_category_frac * equity)
            if ok:
                cash -= stake
                open_cost[i] = stake
                taken += 1
            else:
                skipped += 1
        elif i in open_cost:
            stake = open_cost.pop(i)
            cash += stake * (1.0 + t.ret(cost))
        rows.append({"ts": ts, "equity": cash + sum(open_cost.values()), "cash": cash,
                     "open": len(open_cost)})
    df = pd.DataFrame(rows)
    df.attrs.update(taken=taken, skipped=skipped)
    return df


def market_calibration_samples(dataset: Dataset, max_per_market: int = 10,
                               grid_hours: int = 24) -> Tuple[np.ndarray, np.ndarray]:
    """(Preis, Ergebnis)-Paare zum Lernen einer Kalibrierungskurve.

    Pro Markt höchstens `max_per_market` gleichmäßig verteilte Rasterpunkte,
    damit lange Märkte die Kurve nicht dominieren.
    """
    prices, outcomes = [], []
    for market, history in dataset:
        if market.outcome not in (0, 1) or not history:
            continue
        ts = [p.t for p in history]
        grid = list(decision_times(market, history, grid_hours))
        if not grid:
            continue
        idx = np.unique(np.linspace(0, len(grid) - 1, num=min(max_per_market, len(grid))).astype(int))
        info = MarketInfo.from_market(market)
        for k in idx:
            p = MarketView.from_sorted(info, history, ts, grid[k]).price()
            if p is not None:
                prices.append(p)
                outcomes.append(int(market.outcome))
    return np.asarray(prices, dtype=float), np.asarray(outcomes, dtype=int)
