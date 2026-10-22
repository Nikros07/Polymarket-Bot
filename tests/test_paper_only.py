"""
Harte Regel: paperbot handelt nur mit Papiergeld.

Der Test durchsucht den Quelltext nach Bausteinen, die echte Orders oder
Wallets bräuchten. Taucht einer auf, schlägt der Test fehl, bevor der
GitHub-Actions-Lauf startet (pytest läuft dort vor jedem Zyklus).
"""
import re
from pathlib import Path

import paperbot

FORBIDDEN = [
    r"py_clob_client", r"\bClobClient\b", r"post_order", r"create_order", r"place_order",
    r"private[_ ]?key", r"\bmnemonic\b", r"eth_account", r"web3", r"sign_transaction",
    r"POLYMARKET_PRIVATE", r"api_secret", r"passphrase",
]


def test_flag():
    assert paperbot.PAPER_ONLY is True


def test_no_order_or_wallet_code():
    root = Path(paperbot.__file__).parent
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if re.search(pat, text, flags=re.IGNORECASE):
                hits.append(f"{path.relative_to(root)}: {pat}")
    assert not hits, "Order-/Wallet-Code gefunden:\n" + "\n".join(hits)


def test_no_live_switch_in_config():
    from dataclasses import fields
    from paperbot.config import BotConfig
    names = {f.name for f in fields(BotConfig)}
    assert not names & {"live", "live_mode", "real_money", "dry_run"}
