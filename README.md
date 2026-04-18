# Polymarket Bot — OASIS AI Decision System

> A multi-agent AI system for sports betting and prediction markets.  
> 10 specialized AI agents debate every prediction before you see a result.

---

## What is this?

Polymarket Bot is a **semi-automated decision engine** that helps you evaluate bets on [Polymarket](https://polymarket.com) and traditional sports markets. You give it a question like *"Will Bayern Munich beat Dortmund?"*, and it runs the query through 10 AI agents that research, debate, challenge, and score the prediction — then returns a clear **BET / WATCH / SKIP** recommendation with full reasoning.

The system never bets for you. It is a research and analysis tool: **AI suggests → you decide → you act.**

---

## How it works — the 8-stage pipeline

Every query runs through a fixed sequence of agents:

```
Stage 1   SCAN & PARSE
          ScannerAgent      →  extract teams, sport, event type
          InputParserAgent  →  normalize the query into a structured format

Stage 2   RESEARCH  (parallel with Stage 2b)
          ResearchAgent     →  search the web (Tavily / Serper) for stats,
                               recent form, injuries, and news

Stage 2b  MARKET DATA  (runs in parallel with research)
          PolymarketService →  find live Polymarket markets for this event,
                               fetch implied probabilities and trading volume

Stage 3   PREDICT
          PredictorAgent    →  estimate an initial probability (0.0 – 1.0)

Stage 4   ANALYST vs SKEPTIC  (parallel)
          AnalystAgent      →  build the strongest possible bull case
          SkepticAgent      →  MUST find at least 3 genuine flaws or risks
                               (hardcoded to disagree — not optional)

Stage 4.5 DEBATE
          DebateAgent       →  forces both sides to respond to each other,
                               extract concessions, produce a verdict

Stage 5   SCENARIOS
          ScenarioAgent     →  simulate 4-5 alternative outcomes with
                               individual probabilities and impact levels

Stage 6   VALIDATE
          ValidatorAgent    →  check logic consistency, flag data quality
                               issues and cognitive biases

Stage 7   SYNTHESIZE
          SynthesizerAgent  →  merge all perspectives into a coherent
                               narrative; preserve any unresolved conflicts

Stage 8   SCORE & DECIDE
          ScoringAgent      →  compute composite score, Kelly fraction,
                               adjusted edge, and final decision
```

---

## Decision logic

### Edge calculation

```
Gross edge        =  predicted_probability  −  implied_market_probability
Fee-adjusted edge =  gross_edge  −  2%  (Polymarket fee)
Adjusted edge     =  fee_adjusted_edge  ×  confidence_score
```

### Decision thresholds

| Decision | Condition |
|----------|-----------|
| **BET**  | adjusted edge ≥ 10% AND confidence ≥ 65% AND risk < 70% AND Kelly > 0 |
| **WATCH** | net edge ≥ 3% OR composite score > 58% |
| **SKIP** | insufficient edge, high risk, or negative Kelly |

A **negative Kelly fraction automatically blocks BET** — no positive expected value means no bet.

### Composite scoring (weighted)

| Component | Weight |
|-----------|--------|
| Predicted probability | 25% |
| Confidence score | 20% |
| Data quality | 15% |
| Argument strength (bull case) | 15% |
| Counter-argument impact (bear case) | 10% |
| Validation score | 10% |
| Market signal | 5% |

### Risk levels

| Risk score | Level | Effect |
|------------|-------|--------|
| < 0.30 | LOW | Normal |
| 0.30 – 0.55 | MEDIUM | Caution advised |
| 0.55 – 0.75 | HIGH | Kelly capped at 0.5× |
| > 0.75 | EXTREME | Do not bet |

Risk score is built up from penalties: low data quality (+0.15), strong bear case (+0.20), validation failures (+0.20), detected cognitive biases (+0.10 each), negative Kelly (+0.20), and others.

### Position sizing — Quarter Kelly

```
Kelly fraction  =  (b × p − q) / b
  p  =  predicted probability
  q  =  1 − p
  b  =  decimal odds − 1

Recommended stake  =  Kelly fraction × 0.25   (conservative quarter-Kelly)
```

---

## Output structure

Every analysis returns a JSON decision object:

```json
{
  "decision": "BET | WATCH | SKIP",
  "predicted_probability": 0.62,
  "confidence_score": 0.71,
  "edge": 0.05,
  "risk": {
    "level": "medium",
    "warnings": ["Small sample size (5 games)", "Dortmund away form underrated"],
    "max_exposure_recommendation": "2.1% of bankroll"
  },
  "score_breakdown": {
    "composite_score": 0.63,
    "edge": 0.05,
    "adjusted_edge": 0.036,
    "kelly_fraction": 0.021
  },
  "bull_case": "Bayern's recent form (4W-1D), home advantage ...",
  "bear_case": "Market efficiency, Dortmund's undervalued road record ...",
  "debate_summary": "Analyst conceded sample size risk; Skeptic conceded form data is strong ...",
  "scenarios": [
    {"name": "Dominant win", "probability": 0.35, "outcome": "WIN", "impact": "high"},
    {"name": "Narrow win",   "probability": 0.27, "outcome": "WIN", "impact": "medium"},
    {"name": "Draw",         "probability": 0.22, "outcome": "LOSS", "impact": "medium"},
    {"name": "Upset loss",   "probability": 0.16, "outcome": "LOSS", "impact": "high"}
  ],
  "conflicts": ["Analyst and Skeptic disagreed on Dortmund's away record reliability"],
  "key_insights": ["Bayern have won last 4 home games by 2+ goals", "..."],
  "reasoning_summary": "62% probability estimate, moderate confidence ...",
  "sports_predictions": {
    "home_win_probability": 0.62,
    "draw_probability": 0.22,
    "away_win_probability": 0.16,
    "over_2_5_probability": 0.58,
    "btts_yes_probability": 0.44
  },
  "polymarket_markets": [
    {
      "id": "...",
      "question": "Bayern Munich to win vs Dortmund?",
      "yes_prob": 0.57,
      "no_prob": 0.43,
      "volume_usd": 12400
    }
  ]
}
```

---

## Quick start

### Requirements

- Python 3.8+
- Internet connection (for LLM API calls, web research, Polymarket API)
- At least one of: OpenRouter API key (free), Anthropic API key, or OpenAI API key

### Setup

```bash
# Clone
git clone https://github.com/Nikros07/Polymarket-Bot.git
cd Polymarket-Bot

# Install dependencies
./scripts/setup.sh        # Linux / macOS
setup.bat                 # Windows

# Configure
cp .env.example .env
# Edit .env — add your API key (see options below)
```

### Run the Streamlit UI

```bash
./scripts/start_streamlit.sh
# → http://localhost:8501
```

### Run the REST API

```bash
uvicorn backend.main:app --reload --port 8000
# → http://localhost:8000/docs  (Swagger UI)
```

---

## API key options

### Option A — OpenRouter (free, no credit card)

```env
LLM_PROVIDER=openrouter
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

Get a free key at [openrouter.ai/keys](https://openrouter.ai/keys).

**Recommended free models:**

| Model | Quality |
|-------|---------|
| `meta-llama/llama-3.3-70b-instruct:free` | Best free option |
| `meta-llama/llama-3.1-8b-instruct:free` | Fast, lightweight |
| `qwen/qwen-2.5-7b-instruct:free` | Good reasoning |

Set `LLM_MAX_TOKENS=2048` when using free models.

### Option B — Anthropic or OpenAI

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-7
ANTHROPIC_API_KEY=your_key_here
```

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
OPENAI_API_KEY=your_key_here
```

### Option C — Demo mode (no API key needed)

```env
DEMO_MODE=true
```

Returns simulated responses. Useful for testing the UI and pipeline without any API costs.

---

## Full configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openrouter` | `anthropic` / `openai` / `openrouter` |
| `LLM_MODEL` | `meta-llama/llama-3.3-70b-instruct:free` | Model identifier |
| `LLM_MAX_TOKENS` | `2048` | Max output tokens per agent call |
| `AGENT_TEMPERATURE` | `0.7` | Global LLM temperature |
| `OPENROUTER_API_KEY` | — | OpenRouter key |
| `ANTHROPIC_API_KEY` | — | Anthropic key |
| `OPENAI_API_KEY` | — | OpenAI key |
| `DEMO_MODE` | `false` | Use simulated responses |
| `TAVILY_API_KEY` | — | Tavily web search (1000 free req/month) |
| `SERPER_API_KEY` | — | Serper Google Search fallback |
| `TAVILY_MAX_RESULTS` | `4` | Results per search query |
| `TAVILY_SEARCH_DEPTH` | `basic` | `basic` (1 credit) or `advanced` (2 credits) |
| `RESEARCH_CACHE_TTL_SECONDS` | `300` | Cache TTL for research results |
| `POLYMARKET_FEE_RATE` | `0.02` | Fee deducted from edge (2%) |
| `POLYMARKET_MIN_VOLUME` | `500` | Min USD volume to include a market |
| `POLYMARKET_MAX_MARKETS` | `5` | Max markets returned per search |
| `BET_EDGE_THRESHOLD` | `0.10` | Min adjusted edge for BET |
| `BET_CONFIDENCE_THRESHOLD` | `0.65` | Min confidence for BET |
| `WATCH_EDGE_THRESHOLD` | `0.03` | Min edge for WATCH |
| `MAX_RISK_FOR_BET` | `0.70` | Max risk score to allow BET |
| `KELLY_FRACTION` | `0.25` | Quarter-Kelly multiplier |
| `ENABLE_MEMORY` | `true` | Cross-session learning via SQLite |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/decisions.db` | Database path |
| `APP_HOST` | `0.0.0.0` | API bind address |
| `APP_PORT` | `8000` | API port |
| `DEBUG` | `true` | FastAPI auto-reload |

---

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze` | POST | Start a new analysis session |
| `/api/analyze/{id}/stream` | GET | SSE stream of live agent progress |
| `/api/analyze/{id}` | GET | Get the completed result |
| `/api/history` | GET | Paginated analysis history |
| `/api/outcome/{id}` | POST | Record the actual outcome after the event |
| `/api/health` | GET | Health check |
| `/api/stats` | GET | System statistics |
| `/docs` | GET | Swagger UI |

### Example request

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Will Bayern Munich win their next Bundesliga match?",
    "bet_type": "match_winner",
    "implied_probability": 0.57,
    "market_odds": "1.75"
  }'
```

---

## Project structure

```
Polymarket-Bot/
├── .env.example              # Configuration template
├── streamlit_app.py          # Streamlit UI (port 8501)
├── requirements.txt          # Frontend deps
│
├── backend/
│   ├── main.py               # FastAPI entry point
│   ├── config.py             # Settings loader
│   ├── requirements.txt      # Backend deps
│   │
│   ├── agents/               # The 10 AI agents
│   │   ├── base_agent.py         # Abstract base class, LLM client
│   │   ├── scanner_agent.py
│   │   ├── input_parser_agent.py
│   │   ├── research_agent.py
│   │   ├── predictor_agent.py
│   │   ├── analyst_agent.py
│   │   ├── skeptic_agent.py
│   │   ├── debate_agent.py
│   │   ├── scenario_agent.py
│   │   ├── validator_agent.py
│   │   ├── synthesizer_agent.py
│   │   └── scoring_agent.py
│   │
│   ├── core/
│   │   ├── orchestrator.py   # Runs the 8-stage pipeline
│   │   ├── decision_engine.py # Assembles the final decision object
│   │   ├── scoring.py        # Weighted composite scoring formula
│   │   └── memory.py         # SQLite persistence & pattern detection
│   │
│   ├── services/
│   │   ├── market_service.py     # Odds parsing (decimal/american/fractional)
│   │   ├── polymarket_service.py # Polymarket Gamma API client
│   │   └── research_service.py   # Tavily / Serper web search
│   │
│   └── api/
│       ├── models.py         # Pydantic request/response models
│       └── routes.py         # FastAPI route definitions
│
└── scripts/
    ├── setup.sh
    ├── setup.bat
    └── start_streamlit.sh
```

---

## Key design decisions

**Mandatory disagreement** — The Skeptic agent is instructed to always challenge the prediction and find at least 3 genuine concerns. If the disagreement level is too low, the risk score is increased automatically.

**Conflicts are surfaced, not hidden** — When agents reach different conclusions, the conflict is included in the output so you can judge it yourself.

**Fee-aware edge** — Every edge calculation subtracts Polymarket's 2% fee. A 2% raw edge is worth nothing after fees.

**Kelly Criterion gating** — The system will never output BET when the Kelly fraction is zero or negative. No positive expected value = no bet.

**Cross-session memory** — Past decisions and their outcomes are stored in SQLite. The system tracks calibration (how often predictions at 60% confidence actually win ~60% of the time) and can surface patterns.

**No API key required for market data** — Polymarket market data is fetched from the public Gamma API without authentication.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| UI | Streamlit (dark theme, real-time agent cards) |
| API | FastAPI + Uvicorn + Server-Sent Events |
| AI agents | Custom OASIS-compatible pipeline |
| LLM providers | OpenRouter / Anthropic Claude / OpenAI GPT |
| Web research | Tavily AI Search + Serper fallback |
| Market data | Polymarket Gamma API (public, no key) |
| Database | SQLite via aiosqlite |
| Validation | Pydantic v2 |
| Resilience | tenacity (retry logic) + structlog |
