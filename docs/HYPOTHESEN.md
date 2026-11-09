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

## Kalshi-Runde (eingetragen 2026-10-27, vor dem ersten Kalshi-Backtest)

Anlass: Die Manifold-Runde hat alle vier Hypothesen verworfen. Manifold ist
Spielgeld. Kalshi ist ein regulierter Echtgeld-Markt mit öffentlicher
Daten-API (ohne Login, nur lesend) und, anders als die Polymarket-Historie,
mit **echten Geld- und Briefkursen** je Stunde. Damit lassen sich die Kosten
messen statt annehmen. Bis zu diesem Eintrag wurde kein Kalshi-Ergebnis
angesehen, nur Datenformate (Felder, Endpunkte, Datenmenge).

### Regeln für alle Kalshi-Tests

- **Daten:** abgerechnete binäre Kalshi-Märkte mit Ergebnis `yes` oder `no`
  (andere fallen weg). Kerzen je Stunde (Märkte ≤ 14 Tage Laufzeit) oder je
  Tag (länger). Ein Preispunkt liegt am **Ende** der Kerzenperiode, also erst
  sichtbar, wenn die Periode vorbei ist.
- **Preis für die Strategie:** Mitte aus Geld- und Briefkurs (Schluss der
  Kerze), wenn beide gültig sind. Sonst kein Preispunkt.
- **Kosten:** gekauft wird zum **echten Briefkurs** zur Entscheidungszeit
  (YES: `yes_ask`, NO: `1 − yes_bid`), plus Kalshi-Taker-Gebühr
  0,07 · P · (1 − P) pro Kontrakt (ohne Cent-Aufrundung, also für größere
  Orders). Sensitivität: zusätzlicher Schlupf 0, 1, 2, 3 Cent. Liegt der
  Spread über 10 Cent, gilt der Zeitpunkt als nicht handelbar.
- **Aufteilung:** wie bisher chronologisch nach Markteröffnung 60/40 mit
  Sperrzone.
- **Abhängigkeit:** Märkte desselben Events (z. B. alle Temperatur-Spannen
  eines Tages) hängen zusammen. Bootstrap-Intervall und p-Wert werden deshalb
  **über Events** gezogen, nicht über Märkte.
- **Mehrfachtests:** 8 Varianten in dieser Runde (H5: 3, H6: 2, H7: 1, H8: 2).
  Bonferroni α = 0,05 / 8. Das Register `results/trials.json` zählt sie unter
  `kalshi`.
- **Stichprobe breit (H5–H7):** Kategorien Politics, Elections, Economics,
  Financials, Crypto, Climate and Weather, Sports, Entertainment, Commodities,
  Companies, Science and Technology, World, Mentions. Je Kategorie die Serien
  in fester Reihenfolge nach SHA-256 des Serien-Tickers, je Serie höchstens 20
  Märkte mit Volumen ≥ 1000 Kontrakten und Laufzeit ≥ 2 Tagen, höchstens 400
  Märkte und 150 Serien je Kategorie. Bekannte Schwäche wie bisher: Volumen
  ist Wissen vom Marktende.
- **Kategorie-Tabelle:** Die Ergebnisse von H5 je Kategorie werden berichtet,
  sind aber **explorativ** (kein Urteil, keine Auswahl daraus in dieser Runde).

### H5: Favorite-Longshot auf Kalshi (Taker)

- **Idee:** Bürgi, Deng, Whelan (2026): Kontrakte ab 70 Cent gewinnen auf
  Kalshi etwas öfter als ihr Preis, Außenseiter deutlich seltener.
- **Varianten:** Seite mit Mittelkurs im Band [0,70; 0,95], [0,80; 0,97],
  [0,90; 0,98], erstes Signal je Markt.
- **Erwartung:** vor Kosten leicht positiv, nach echtem Briefkurs und
  Taker-Gebühr nahe null oder negativ (das Paper findet den Vorteil vor allem
  für Maker).
- **Abbruch:** wie H1.

### H6: Unterkonfidenz in Politik-Märkten

- **Idee:** Le (2026, arXiv:2602.19520): Politik-Märkte auf Kalshi und
  Polymarket liegen dauerhaft zu nah an 50 %. Der Favorit ist zu billig.
- **Universum:** nur Kategorien Politics und Elections.
- **Varianten:** Kauf des Favoriten, wenn sein Mittelkurs in [0,60; 0,85]
  bzw. [0,55; 0,80] liegt.
- **Erwartung:** kleiner positiver Ertrag vor Kosten; nach Kosten unklar.
- **Abbruch:** wie H1.

### H7: Gegenbewegung (Nachprüfung der Manifold-Variante)

- **Idee:** `reversion_25_1d` hatte auf Manifold den einzigen unkorrigierten
  p-Wert unter 0,05. Eine Nachprüfung auf Echtgeld-Daten klärt, ob das ein
  Spielgeld-Effekt war.
- **Variante:** genau eine, `reversion_25_1d` (≥ 25 Punkte Bewegung in 1 Tag →
  dagegen).
- **Erwartung:** kein Vorteil.
- **Abbruch:** wie H1.

### H8: Wetter-Spezialisierung — Tageshöchsttemperatur mit Vorhersagemodell

- **Idee:** Statt eines Preis-Musters ein echtes Informationsmodell. Kalshi
  handelt täglich die Höchsttemperatur in US-Städten in 2-°F-Spannen.
  Wettermodelle sagen das 1–2 Tage vorher mit wenigen Grad Fehler voraus.
- **Daten:** Serien KXHIGHNY, KXHIGHCHI, KXHIGHMIA, KXHIGHLAX, KXHIGHAUS,
  KXHIGHDEN, KXHIGHPHIL. Events mit Datum ab 2022-06-01; je Stadt jedes Event,
  dessen Tag im Jahr durch 3 teilbar ist (feste Ausdünnung, spart Abrufe).
- **Vorhersage:** Open-Meteo Previous-Runs-API, stündliche
  `temperature_2m_previous_day2` (Lauf mindestens 48 h vor der jeweiligen
  Stunde) an den Koordinaten der Messstation, Maximum über den lokalen Tag.
  Alle Läufe liegen damit vor 00:00 Ortszeit des Vortags und vor jeder
  Entscheidung. Events ohne vollständige Vorhersage fallen weg.
- **Modell:** Höchstwert ~ Normal(μ + b, σ). Spanne „zwischen a und c“ =
  [a − 0,5; c + 0,5], „größer als a“ = [a + 0,5; ∞), „kleiner als c“ =
  (−∞; c − 0,5]. b und σ werden per Maximum-Likelihood nur auf
  Trainingsmärkten geschätzt (Ablauf wie H4: erste Hälfte In-Sample lernen,
  Variante auf zweiter Hälfte wählen, dann ganzes In-Sample lernen, einmal
  Out-of-Sample prüfen).
- **Entscheidung:** 24-h-Raster ab Markteröffnung + 6 h. Kauf der Seite, deren
  Modell-Wahrscheinlichkeit den Kaufpreis (Briefkurs + Gebühr) um mindestens
  die Mindest-Edge übersteigt.
- **Varianten:** Mindest-Edge 5 bzw. 10 Prozentpunkte.
- **Erwartung:** ehrlich offen. Händler auf Kalshi nutzen dieselben
  Vorhersagen; ein Vorteil, wenn überhaupt, ist klein. Die Kontrollen
  (Zufallsseite, immer YES) laufen wie bei allen Hypothesen mit.
- **Abbruch:** wie H1.

### Nachtrag 2026-10-29: Ergebnis des ersten Kalshi-Laufs und Datenfehler

- Lauf vom 2026-10-27 (`results/BACKTEST_kalshi.md`): H5, H7, H8 verworfen,
  H6 hatte zu wenige Trades (nur 7 Politik-Märkte In-Sample). Das Register
  zählt den Lauf (`trials.json`).
- **H8 ist damit nicht aussagekräftig geprüft:** Der Batch-Kerzen-Endpunkt
  liefert für archivierte Märkte nichts. Nur 924 von ~15.300 ausgewählten
  Wettermärkten hatten Kerzen, alle aus dem 22.08.–24.10.2026 (statt ab
  2022-06-01). Behoben: Einzelabruf aus dem Archiv als Rückfall
  (`KalshiClient.archived_candles`, Test in `tests/test_kalshi.py`).
- Auch die breite Stichprobe ist klein (1.143 Märkte, 346 nach Sperrzone
  im Training).
- Die Wiederholung prüft **dieselben** Hypothesen mit denselben Schwellen.
  Sie zählt als neue Runde (+8 im Register); das Urteil des ersten Laufs
  wird nicht überschrieben, sondern danebengestellt.
- Kalshi war am 2026-10-29 im lokalen Netz gesperrt (TLS-Fehler wie bei
  Polymarket). Die Wiederholung läuft deshalb auf einem anderen Netz
  (z. B. VPS per Docker), nicht durch Umgehen der Sperre.

### Nachtrag 2026-11-09: Korrekturen vor der Wiederholung (Code-Review)

Gefunden durch zwei unabhängige Prüfungen, **vor** jedem neuen Lauf behoben.
Hypothesen, Varianten und Schwellen bleiben unverändert; geändert ist nur,
was als ausführbarer Kauf zählt:

- **Briefkurs 1,00 = kein Angebot.** Bisher wurde er auf 0,99 gedeckelt und
  als Kauf verbucht (26 von 174 H5-Trades im ersten Lauf, alle gewonnen,
  Mittel −2,83 % statt −2,27 %). Jetzt: nicht handelbar, echter Briefkurs
  wird nie gedeckelt.
- **Veraltete Kurse:** Ist der letzte gültige Kurs älter als 2
  Kerzenperioden, ist der Zeitpunkt nicht handelbar.
- **Datenqualität:** Bricht ab, wenn > 20 % der Märkte ohne Preise oder
  > 1 % mit Abruffehlern wegfallen oder eine Serie ausfällt; H8 ist „nicht
  prüfbar“, wenn < 90 % der Testmärkte eine Vorhersage haben.
- Ein verworfenes oder nicht prüfbares H8-Modell wird live nur als
  Papier-Vorwärtstest mit Warnung genutzt bzw. gelöscht.

## Nicht per Backtest prüfbar

- **LLM-Prognose (bestehende 10-Agenten-Pipeline):** Ein Sprachmodell kennt
  Ausgänge vergangener Ereignisse, und die Websuche liefert Artikel von nach der
  Auflösung. Ein Backtest wäre wertlos. Prüfung nur live im Papiermodus über das
  Prognose-Log (Brier-Score gegen Marktpreis, ab 100 aufgelösten Märkten).
- **Arbitrage in Mehrfach-Märkten:** braucht historische Orderbücher, die es
  nicht gibt. Nur live messbar.
