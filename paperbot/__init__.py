"""
paperbot — automatischer Papier-Handel und Backtest für Prognosemärkte.

Harte Regel: Dieses Paket handelt NUR mit Papiergeld. Es enthält keinen Code,
der Orders an eine Börse sendet, keine Wallet-Schlüssel und keine
Geldtransfers. `tests/test_paper_only.py` prüft das bei jedem Testlauf.
"""

PAPER_ONLY = True

__version__ = "0.1.0"
