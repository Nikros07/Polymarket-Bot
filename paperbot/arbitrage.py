"""
Arbitrage-Scanner (nur Messung, kein Handel).

Idee aus Saguillo et al., arXiv 2508.03474: Kostet ein YES-Anteil plus ein
NO-Anteil zusammen weniger als 1 $, ist der Gewinn bei Auflösung sicher.
Die Studie misst ~40 Mio. $ entnommene Gewinne, sagt aber nicht, wie lange
solche Lücken offen bleiben. Genau das protokolliert dieser Scanner:
wann, wie groß, wie viele Anteile zur besten Kursstufe verfügbar waren.

Bewusst KEINE Papier-Käufe: Ohne Geschwindigkeit und gleichzeitige
Ausführung beider Seiten wäre ein Papier-Gewinn hier geschönt.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from paperbot.fees import FeeModel
from paperbot.models import Book, Market


@dataclass(frozen=True)
class ArbOpportunity:
    ts: int
    market_id: str
    question: str
    ask_yes: float
    ask_no: float
    fee_pair: float
    margin: float            # 1 − (ask_yes + ask_no + Gebühren) pro Paar
    max_pairs: float         # Anteile, die zur jeweils besten Stufe beider Seiten gehen
    profit_at_best: float    # margin × max_pairs


def check_pair(market: Market, yes: Optional[Book], no: Optional[Book], fee: FeeModel,
               ts: int, min_margin: float) -> Optional[ArbOpportunity]:
    if yes is None or no is None or not yes.asks or not no.asks or yes.synthetic or no.synthetic:
        return None
    ay, an = yes.asks[0], no.asks[0]
    fee_pair = fee.per_share(ay.price, market.category) + fee.per_share(an.price, market.category)
    margin = 1.0 - (ay.price + an.price + fee_pair)
    if margin < min_margin:
        return None
    pairs = min(ay.size, an.size)
    return ArbOpportunity(ts=ts, market_id=market.market_id, question=market.question[:200],
                          ask_yes=ay.price, ask_no=an.price, fee_pair=fee_pair, margin=margin,
                          max_pairs=pairs, profit_at_best=margin * pairs)


def append_opportunities(path: Path, opps: List[ArbOpportunity]) -> None:
    if not opps:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for o in opps:
            f.write(json.dumps(asdict(o), ensure_ascii=False) + "\n")
