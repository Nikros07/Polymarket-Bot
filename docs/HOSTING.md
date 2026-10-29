# paperbot hosten (nur Papiergeld)

Der Bot braucht **keine API-Schlüssel**: Kalshi-Marktdaten und Open-Meteo-
Vorhersagen sind öffentlich. Er sendet keine Orders. Spezialisierung:
Kalshi-Tageshöchsttemperatur (7 US-Städte, Auflösung nach einem Tag).

## Vorher einmal: Modell lernen

```bash
python -m paperbot backtest --source kalshi --limit 6000
```

Lädt die Daten (ca. 30–60 min beim ersten Mal, danach aus dem Cache), prüft
H5–H8 aus `docs/HYPOTHESEN.md`, schreibt `results/BACKTEST_kalshi.md` und
speichert das Wettermodell in `data/paperbot/kalshi/weather_model_kalshi.json`.
Ohne diese Datei kauft die Strategie `weather` nichts (NO TRADE ist Standard).
Für den Container: die Datei ins Volume kopieren
(`docker cp … paperbot:/app/data/paperbot/kalshi/`).

## Variante A: Docker auf einem kleinen VPS (empfohlen)

Jeder Server mit Docker reicht (z. B. Hetzner CX22, ca. 4 €/Monat).

```bash
docker compose up -d --build
```

- Statusseite: `http://<server>:8080/`, Health-Check: `/health` (JSON, 503
  wenn seit drei Intervallen kein Zyklus geklappt hat).
- Zustand liegt im Volume `paperbot-data` (überlebt Neustarts und Updates).
- Notaus: `PAPERBOT_ENABLED=false` in `docker-compose.yml`, dann
  `docker compose up -d`.
- Das Image baut nur, wenn alle Tests grün sind (inkl. Nur-Papiergeld-Test).

## Variante B: Plattform mit Docker-Unterstützung (Fly.io, Railway, Render)

Das `Dockerfile` funktioniert dort unverändert. Wichtig:
- Einen **persistenten Datenträger** unter `/app/data` einhängen, sonst
  beginnt das Papierkonto nach jedem Neustart von vorn.
- Port kommt aus `$PORT` (Standard 8080), Health-Check-Pfad `/health`.
- Genau **eine** Instanz laufen lassen (sonst zwei Zyklen am selben Zustand).

## Variante C: ohne Server (GitHub Actions)

`.github/workflows/paperbot.yml` startet alle 6 Stunden einen Zyklus für
Polymarket **und** Kalshi. Kostenlos, aber nur 4 Zyklen am Tag. Für die
Wettermärkte (Entscheidung am Vortag) ist das ausreichend, eine
Statusseite gibt es dort nicht (Berichte liegen in `reports/`).

## Lokal

```bash
python -m paperbot serve --source kalshi --interval 30
```

## Was nicht dazugehört

Kein Echtgeld-Schalter, keine Wallet, keine Order-Endpunkte. Ob und wie man
aus Deutschland auf Kalshi handeln dürfte, ist **nicht geprüft** (Kalshi ist
eine US-regulierte Börse). `python -m paperbot gate --source kalshi` zeigt, was
ein Papierkonto mindestens zeigen müsste, bevor man überhaupt darüber
nachdenkt.
