"""
Paper-Trading-Log
=================
Protokolliert Prognosen VOR Marktschluss, löst sie später auf und misst,
ob die eigene Prognose besser war als der Marktpreis. Kein Geld, keine
Orders, kein API-Key nötig (nur die öffentliche Gamma-API).

Befehle:
  python scripts/paper_log.py add <slug> --p 0.62 [--note "..."]
  python scripts/paper_log.py check
  python scripts/paper_log.py report

Die Auswertung ist erst ab ~100 aufgelösten Märkten aussagekräftig.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA_URL = "https://gamma-api.polymarket.com"
FEE_RATE = 0.02  # wie POLYMARKET_FEE_RATE in backend/config.py
MIN_RESOLVED_FOR_VERDICT = 100

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "paper_trades.csv"
FIELDS = [
    "id", "created_at", "slug", "market_id", "question", "side",
    "my_prob", "market_prob", "edge_after_fee", "note",
    "resolved_at", "outcome_yes",
]


# ── Gamma-API ─────────────────────────────────────────────────────────────

def _get_json(url: str):
    req = Request(url, headers={"User-Agent": "PolymarketBot-PaperLog/1.0"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_market_by_slug(slug: str) -> dict | None:
    data = _get_json(f"{GAMMA_URL}/markets?{urlencode({'slug': slug})}")
    return data[0] if data else None


def fetch_market_by_id(market_id: str) -> dict | None:
    return _get_json(f"{GAMMA_URL}/markets/{market_id}")


def yes_price(market: dict) -> float | None:
    """Marktpreis für 'Yes' (0..1) aus outcomePrices. Gamma liefert JSON-Text."""
    raw = market.get("outcomePrices")
    if not raw:
        return None
    prices = json.loads(raw) if isinstance(raw, str) else raw
    return float(prices[0])


# ── CSV-Speicher ──────────────────────────────────────────────────────────

def load_rows() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Befehle ───────────────────────────────────────────────────────────────

def cmd_add(args) -> int:
    market = fetch_market_by_slug(args.slug)
    if market is None:
        print(f"Kein Markt mit slug '{args.slug}' gefunden.")
        return 1

    market_prob = yes_price(market)
    if market_prob is None:
        print("Markt hat keinen Preis – abgebrochen.")
        return 1

    my_prob = args.p
    if not 0.0 < my_prob < 1.0:
        print("--p muss zwischen 0 und 1 liegen (z. B. 0.62).")
        return 1

    # Seite, auf die man setzen würde, und Edge nach Gebühr (wie scoring.py)
    if my_prob >= market_prob:
        side, gross = "YES", my_prob - market_prob
    else:
        side, gross = "NO", market_prob - my_prob
    edge_after_fee = gross - FEE_RATE

    rows = load_rows()
    row = {
        "id": str(len(rows) + 1),
        "created_at": now_iso(),
        "slug": args.slug,
        "market_id": str(market.get("id", "")),
        "question": market.get("question", ""),
        "side": side,
        "my_prob": f"{my_prob:.4f}",
        "market_prob": f"{market_prob:.4f}",
        "edge_after_fee": f"{edge_after_fee:.4f}",
        "note": args.note or "",
        "resolved_at": "",
        "outcome_yes": "",
    }
    rows.append(row)
    save_rows(rows)

    print(f"Protokolliert #{row['id']}: {row['question']}")
    print(f"  Markt {market_prob:.1%} | eigene Prognose {my_prob:.1%} | "
          f"Seite {side} | Edge nach Gebühr {edge_after_fee:+.1%}")
    if edge_after_fee < 0.03:
        print("  Hinweis: Edge unter 3 % nach Gebühr – laut Bot-Logik eher SKIP.")
    return 0


def cmd_check(_args) -> int:
    rows = load_rows()
    open_rows = [r for r in rows if not r["outcome_yes"]]
    if not open_rows:
        print("Keine offenen Prognosen.")
        return 0

    newly = 0
    for row in open_rows:
        try:
            market = (fetch_market_by_id(row["market_id"]) if row["market_id"]
                      else fetch_market_by_slug(row["slug"]))
        except Exception as exc:  # Netzwerkfehler nicht den ganzen Lauf abbrechen lassen
            print(f"#{row['id']}: Abruf fehlgeschlagen ({exc})")
            continue
        if not market or not market.get("closed"):
            continue
        price = yes_price(market)
        if price is None or 0.02 < price < 0.98:
            continue  # geschlossen, aber noch nicht eindeutig aufgelöst
        row["outcome_yes"] = "1" if price >= 0.98 else "0"
        row["resolved_at"] = now_iso()
        newly += 1
        print(f"#{row['id']} aufgelöst: {'YES' if row['outcome_yes'] == '1' else 'NO'} – {row['question']}")

    save_rows(rows)
    print(f"{newly} neu aufgelöst, {len(open_rows) - newly} weiterhin offen.")
    return 0


def _brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def cmd_report(_args) -> int:
    rows = [r for r in load_rows() if r["outcome_yes"]]
    total = len(load_rows())
    if not rows:
        print(f"{total} Prognosen protokolliert, noch keine aufgelöst.")
        return 0

    my_brier, mkt_brier, pnl = [], [], []
    for r in rows:
        outcome = int(r["outcome_yes"])
        my_p, mkt_p = float(r["my_prob"]), float(r["market_prob"])
        my_brier.append(_brier(my_p, outcome))
        mkt_brier.append(_brier(mkt_p, outcome))
        # Papier-PnL pro 1 € Einsatz auf die gewählte Seite, nach Gebühr
        side_price = mkt_p if r["side"] == "YES" else 1 - mkt_p
        won = (outcome == 1) == (r["side"] == "YES")
        gain = (1 - side_price) / side_price if won else -1.0
        pnl.append(gain - FEE_RATE)

    n = len(rows)
    my_avg = sum(my_brier) / n
    mkt_avg = sum(mkt_brier) / n
    avg_pnl = sum(pnl) / n

    print(f"Aufgelöst: {n} von {total} protokollierten Prognosen")
    print(f"Brier-Score eigene Prognose: {my_avg:.4f}  (niedriger = besser)")
    print(f"Brier-Score Marktpreis:      {mkt_avg:.4f}")
    print(f"Papier-Ergebnis pro 1 €:     {avg_pnl:+.3f} €  (nach {FEE_RATE:.0%} Gebühr)")

    if n < MIN_RESOLVED_FOR_VERDICT:
        print(f"\nZu früh für ein Urteil: mindestens {MIN_RESOLVED_FOR_VERDICT} aufgelöste Märkte nötig.")
    elif my_avg < mkt_avg and avg_pnl > 0:
        print("\nErgebnis: eigene Prognose schlägt den Markt – erst dann über echtes Geld nachdenken.")
    else:
        print("\nErgebnis: eigene Prognose schlägt den Markt nicht. Kein Grund für echtes Geld.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Paper-Trading-Log für Polymarket-Prognosen")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Prognose protokollieren")
    p_add.add_argument("slug", help="Markt-Slug aus der Polymarket-URL")
    p_add.add_argument("--p", type=float, required=True, help="eigene Wahrscheinlichkeit für YES (0..1)")
    p_add.add_argument("--note", default="", help="kurze Begründung")
    p_add.set_defaults(func=cmd_add)

    p_check = sub.add_parser("check", help="offene Prognosen auf Auflösung prüfen")
    p_check.set_defaults(func=cmd_check)

    p_report = sub.add_parser("report", help="Auswertung: Brier-Score und Papier-Ergebnis")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
