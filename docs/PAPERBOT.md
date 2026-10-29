# paperbot: automatischer Papier-Handel

`paperbot/` läuft neben der bestehenden KI-Pipeline (`backend/`). Es handelt
**nur mit Papiergeld**: keine Orders, kein Wallet, kein Echtgeld-Schalter.
`tests/test_paper_only.py` bricht jeden Testlauf ab, sobald Order- oder
Wallet-Code auftaucht.

## Befehle

```bash
python -m paperbot cycle --source polymarket     # ein Zyklus: abrechnen, scannen, Papier-Käufe
python -m paperbot cycle --source manifold       # dasselbe auf Manifold (Spielgeld, als Ersatz)
python -m paperbot cycle --source kalshi         # Spezialisierung: Kalshi-Tageshöchsttemperatur
python -m paperbot serve --source kalshi         # Dauerbetrieb + Statusseite (siehe docs/HOSTING.md)
python -m paperbot backtest --source kalshi --limit 6000   # H5–H8 mit echten Geld-/Briefkursen
python -m paperbot status --source polymarket    # schreibt reports/STATUS_<quelle>.md
python -m paperbot backtest --source manifold    # Versuchsprotokoll aus docs/HYPOTHESEN.md
python -m paperbot gate --source polymarket      # Freigabe-Prüfung (nur Auskunft)
streamlit run streamlit_app.py                   # Seite "Papier-Portfolio" in der Seitenleiste
```

Notaus: `PAPERBOT_ENABLED=false`. Alle Einstellungen in `paperbot/config.py`,
überschreibbar mit `PAPERBOT_<NAME>`.

## Wie ein Zyklus abläuft

1. **Abrechnen:** Offene Papier-Positionen werden geprüft. Aufgelöste Märkte
   zahlen 1 € pro Gewinner-Anteil aus. Annullierte Märkte erstatten den Einsatz.
2. **Scannen:** bis zu 200 aktive Märkte. Filter: Volumen, Liquidität, Ende in
   6 Stunden bis 45 Tagen, keine Stichworte für strittige Auflösungen (z. B.
   „say“, „mention“, „suit“).
3. **Strategie-Turnier:** Jede Strategie hat ein eigenes Konto mit 50 €
   Papiergeld. Eine Zufallskontrolle kauft zu denselben Zeitpunkten wie die
   Favoriten-Strategie, wählt die Seite aber per Münzwurf.
4. **Kauf simulieren:** gegen das echte Orderbuch (Polymarket) bzw. AMM-Kurs
   ± 1 Cent (Manifold), mit Gebühren je Kategorie und Mindestgröße 5 Anteile.
5. **Risiko:** max. 12 % pro Markt, 85 % gesamt, 40 % je Kategorie, 10 offene
   Positionen. Notbremse bei −30 % gegenüber dem Hoch der letzten 30 Tage,
   danach 7 Tage Pause und neu messen.
6. **Arbitrage-Messung:** Für bis zu 60 Märkte werden beide Orderbücher
   geprüft. YES + NO + Gebühren < 1 $ wird in `arbitrage.jsonl` protokolliert,
   aber nicht gehandelt.
7. **Speichern:** atomar in `data/paperbot/<quelle>/ledgers.json`, Ereignisse
   nur angehängt in `events.jsonl`.

## Strategien

| Name | Idee | Beleglage | Backtest |
|---|---|---|---|
| `favorite` | Seite mit Preis 0,90–0,98 kaufen (Favorite-Longshot-Bias) | Polymarket-Studie: +0,3 bis +0,8 % pro $ vor Gebühren | ja |
| `calibration` | gelernte Kurve „Preis → echte Trefferquote“, kauft bei ≥ 4 Cent Abweichung | Verallgemeinerung von `favorite` | ja |
| `momentum` | Bewegung ≥ 10 Punkte in 3 Tagen → mitlaufen | kein Beleg | ja |
| `reversion` | Bewegung ≥ 15 Punkte an 1 Tag → dagegen | gemischte Belege | ja |
| `random_control` | Zufallsseite zu den Zeitpunkten von `favorite` | Kontrolle | ja |
| `llm_blend` | ⅔ Marktpreis + ⅓ Prognose der 10-Agenten-Pipeline | LLMs schlagen liquide Märkte bisher nicht | nein (nur live, standardmäßig aus) |

## Betrieb ohne Server

`.github/workflows/paperbot.yml` startet alle 6 Stunden einen Zyklus auf
GitHub Actions (kostenlos). Vorher laufen alle Tests. Der Zustand liegt auf
dem Branch `paperbot-state`, Berichte in `reports/`. Aktiv wird das erst,
wenn das Repo gepusht ist.

## Warum es keinen Echtgeld-Modus gibt

- Kein Backtest und kein Papierkonto hat bisher einen belegten Vorteil gezeigt.
- Polymarket ist in Deutschland laut Berichten gesperrt oder eingeschränkt.
- `python -m paperbot gate` zeigt, was erfüllt sein müsste: mindestens 100
  aufgelöste Papier-Trades, 95-%-Untergrenze des Ertrags über null, besser
  als die Zufallskontrolle, Backtest auf ungesehenen Daten bestätigt. Auch
  dann bleibt es eine Auskunft, kein Schalter.
