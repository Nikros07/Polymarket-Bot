# Hypothesen (vor dem Backtest festgelegt)

Eingetragen am 2026-10-22, **bevor** irgendein Backtest gelaufen ist. Nachträglich
werden hier keine Schwellen geändert. Neue Ideen bekommen einen neuen Eintrag
mit eigenem Datum.

## Regeln für alle Tests

- **Daten:** aufgelöste binäre Märkte (Ergebnis nur YES oder NO, keine
  annullierten). Manifold Markets als Ersatz, solange Polymarket im lokalen Netz
  gesperrt ist. Polymarket-Daten, sobald verfügbar, als eigentlicher Test.
- **Kein Blick in die Zukunft:** Entscheidung zum Zeitpunkt *t* nur mit Preisen
  ≤ *t*. Auflösungszeitpunkt und Ergebnis sind für die Strategie unsichtbar.
  Entscheidungszeitpunkte liegen auf einem festen 24-h-Raster ab Marktstart.
- **Ein Einstieg pro Markt und Strategie** (das erste Signal), gehalten bis zur
  Auflösung.
- **Kosten:** Kauf zum Preis + halber Spread (Standard 1 Cent) + Gebühr.
  Sensitivität mit 0, 1, 2 und 3 Cent.
- **Aufteilung:** chronologisch nach Markterstellung. Die ersten 60 % sind
  In-Sample: Dort wird pro Hypothese genau eine Variante gewählt. Die letzten
  40 % sind Out-of-Sample: Dort wird diese eine Variante einmal bestätigt oder
  verworfen.
- **Mehrfachtests:** 9 Strategie-Varianten (H1–H4). Signifikanz nur mit
  Bonferroni-Korrektur (α = 0,05 / 9).
- **Pflicht-Vergleiche:** zufällige Seite und „immer YES“ mit denselben
  Einstiegszeitpunkten wie die geprüfte Strategie.
- **Bekannte Schwäche:** Die Auswahl der Märkte nach Endvolumen bzw. Anzahl
  Teilnehmer nutzt Wissen vom Marktende. Das lässt sich bei historischen
  Daten nicht vermeiden und wird im Bericht genannt.
- **Kennzahlen:** Rendite pro eingesetztem Euro (ROI), Trefferquote,
  Brier-Score, Rendite pro Kapital-Tag, 95-%-Bootstrap-Intervall (über Märkte).

## H1: Favoriten-Ernte (Favorite-Longshot-Bias)

- **Idee:** Wahrscheinliche Ausgänge sind in Prognosemärkten leicht unterbewertet,
  Außenseiter überbewertet. Kauf der Seite, deren Preis im Band liegt.
- **Varianten:** Band [0,80; 0,95], [0,85; 0,97], [0,90; 0,98].
- **Erwartung:** kleiner positiver ROI vor Kosten (1–3 %), nach 1 Cent Kosten
  nahe null.
- **Abbruch:** ROI Out-of-Sample nach Kosten ≤ 0 oder untere Grenze des
  95-%-Intervalls ≤ 0 → verworfen.
- **Bekanntes Risiko:** seltene große Verluste (Auflösungsstreit, Überraschung).
  Der größte Einzelverlust wird mitberichtet.

## H2: Momentum

- **Idee:** Preise unterreagieren auf Nachrichten und laufen weiter.
- **Varianten:** Bewegung ≥ 10 bzw. ≥ 20 Prozentpunkte in 3 Tagen → Kauf in
  Bewegungsrichtung.
- **Erwartung:** kein Vorteil (ROI ≈ 0 oder negativ nach Kosten).
- **Abbruch:** wie H1.

## H3: Mean Reversion

- **Idee:** Preise überreagieren kurzfristig.
- **Varianten:** Bewegung ≥ 15 bzw. ≥ 25 Prozentpunkte in 1 Tag → Kauf gegen
  die Bewegung.
- **Erwartung:** kein Vorteil.
- **Abbruch:** wie H1.

## H4: Kalibrierungs-Korrektur (Nachtrag 2026-10-22, vor dem ersten Backtest)

- **Idee:** Marktpreise sind systematisch leicht falsch kalibriert. Eine
  isotonische Kurve „Preis → tatsächliche Trefferquote“ wird nur auf
  Trainingsdaten gelernt. Gekauft wird, wenn die korrigierte
  Wahrscheinlichkeit den Kaufpreis inklusive Kosten um mindestens die
  Mindest-Edge übersteigt.
- **Varianten:** Mindest-Edge 2 bzw. 4 Prozentpunkte.
- **Ablauf:** Kurve auf der ersten Hälfte des In-Sample lernen, Variante auf
  der zweiten Hälfte wählen, dann Kurve auf dem ganzen In-Sample neu lernen
  und einmal Out-of-Sample prüfen.
- **Erwartung:** kleiner Vorteil, der weitgehend H1 entspricht.
- **Abbruch:** wie H1.

Damit sind es 9 Varianten. Die Bonferroni-Schwelle wird auf α = 0,05 / 9
verschärft.

## Nicht per Backtest prüfbar

- **LLM-Prognose (bestehende 10-Agenten-Pipeline):** Ein Sprachmodell kennt
  Ausgänge vergangener Ereignisse, und die Websuche liefert Artikel von nach der
  Auflösung. Ein Backtest wäre wertlos. Prüfung nur live im Papiermodus über das
  Prognose-Log (Brier-Score gegen Marktpreis, ab 100 aufgelösten Märkten).
- **Arbitrage in Mehrfach-Märkten:** braucht historische Orderbücher, die es
  nicht gibt. Nur live messbar.
