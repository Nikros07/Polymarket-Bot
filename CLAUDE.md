# Polymarket-Bot — AI Decision System (OASIS Multi-Agent)

10-Agenten-Pipeline (camel-ai/OASIS-kompatibel, Fallback auf direkte Anthropic/OpenAI/OpenRouter-Calls) für Wett-/Prediction-Market-Analysen. **Semi-automatisiert: das System schlägt vor (BET/WATCH/SKIP), es platziert nie selbst eine Wette.** Kein automatischer Fund-Transfer, kein Order-Execution-Code im Repo.

## Pipeline (siehe `backend/core/orchestrator.py`)
Scanner → InputParser → Research (Tavily/Serper) → Predictor ‖ Analyst ‖ Skeptic (parallel) → Scenario → Validator → Synthesizer → Scoring

- **SkepticAgent MUSS widersprechen** — das ist Design, kein Bug. Beim Ändern der Agent-Prompts in `backend/agents/` nicht versehentlich in Zustimmung umbiegen.
- Konflikte zwischen Agenten werden bewusst sichtbar gehalten (`conflicts`-Feld), nicht aufgelöst.

## Scoring/Risk-Invarianten (siehe `backend/core/scoring.py`, `backend/config.py`)
- `net_edge = gross_edge - POLYMARKET_FEE_RATE` (2%) — Edge ist immer fee-adjusted.
- `BET` ist Kelly-gated: blockiert bei negativem Kelly-Wert, selbst wenn Edge/Confidence stimmen.
- Schwellen (`BET_EDGE_THRESHOLD`, `BET_CONFIDENCE_THRESHOLD`, `KELLY_FRACTION` etc.) sind bewusst konservativ gesetzt — nicht ohne Rückfrage lockern.

## Secrets
`.env` enthält echte API-Keys (Anthropic/OpenAI/OpenRouter/Tavily/Serper) — ist korrekt in `.gitignore`. Inhalte nie in Chat, Logs oder Commits ausgeben.

## Tests
`tests/` deckt nur `paperbot/` ab (`python -m pytest tests -q`). Für `backend/` gibt es weiterhin **keine** Tests. Bei neuer Logik in `backend/agents/` oder `backend/core/` nach Testbarkeit fragen statt stillschweigend ungetestete Pfade zu erweitern.

## paperbot (automatischer Papier-Handel, siehe `docs/PAPERBOT.md`)
- **Nur Papiergeld.** Kein Order-, Wallet- oder Signatur-Code, kein Echtgeld-Schalter in `BotConfig`. `tests/test_paper_only.py` erzwingt das.
- **Kein Blick in die Zukunft:** Strategien sehen nur `MarketView` (auf die Entscheidungszeit gekürzt, ohne Ergebnis). Neue Strategien bekommen einen Kausalitätstest wie in `tests/test_core.py`.
- **Hypothese vor Test:** neue Strategie-Ideen zuerst mit Datum, Erwartung und Abbruchkriterium in `docs/HYPOTHESEN.md`, dann `N_VARIANTS` in `paperbot/backtest/experiment.py` erhöhen. `results/trials.json` zählt alle geprüften Varianten.
- **NO TRADE ist Standard:** kein Codepfad darf einen Kauf erzwingen (`test_no_signal_means_no_trade`).
- Geldrechnung (fees, broker, risk, ledger, backtest/engine) nur mit Tests ändern. Der Selbsttest (`tests/test_backtest_selftest.py`) muss einen eingebauten Vorteil finden und bei fairen Märkten keinen bestätigen.
- Polymarket **und seit 2026-10-29 auch Kalshi** sind im lokalen Netz per Firewall gesperrt (Sophos, Kategorie Glücksspiel; Kalshi zeigt sich als TLS-Zertifikatsfehler). Nicht umgehen, keine Zertifikatsprüfung abschalten. Live-Tests lokal mit `--source manifold`; Kalshi-Läufe auf GitHub Actions (`paperbot-backtest.yml`) oder einem VPS.
- **Spezialisierung Kalshi-Wetter** (`paperbot/data/kalshi.py`, `paperbot/weather.py`, `paperbot/backtest/kalshi_experiment.py`): Hypothesen H5–H8 in `docs/HYPOTHESEN.md`. Backtest kauft zum echten Briefkurs + Kalshi-Gebühr, Bootstrap über Events. Die Vorhersage für Tag D gilt erst ab D−1 06:00 Ortszeit (`ForecastBook.get` wirft sonst `LookaheadError`).
- **Betrieb:** `python -m paperbot serve --source kalshi` (Statusseite + `/health`), `Dockerfile`/`docker-compose.yml`, Anleitung `docs/HOSTING.md`. Architektur und Optimierungsfahrplan: `docs/ARCHITEKTUR.md`.
- Lokales venv: `.venv` (Python 3.11). Das `python` im PATH gehört zu Hermes und hat kein pytest.

## Dev-Server
`.claude/launch.json` startet FastAPI-Backend (Port 8000) und Streamlit-UI (Port 8501).
