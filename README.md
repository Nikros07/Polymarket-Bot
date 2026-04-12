# AI Decision System
### OASIS-Powered Multi-Agent Decision Engine

A production-ready AI decision system for sports betting, prediction markets,
and event-based probabilistic decisions — built on a 10-agent OASIS collaborative architecture.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OASIS Agent Society                       │
│                                                             │
│  Stage 1: Scan & Parse                                      │
│    [ScannerAgent] → [InputParserAgent]                      │
│                                                             │
│  Stage 2: Research                                          │
│    [ResearchAgent] ← Web/API sources (Tavily / Serper)      │
│                                                             │
│  Stage 3: Predict + Analyze (parallel)                      │
│    [PredictorAgent] │ [AnalystAgent] ║ [SkepticAgent]       │
│                                                             │
│  Stage 4–7: Scenarios → Validate → Synthesize → Score      │
│    [ScenarioAgent] → [ValidatorAgent] → [SynthesizerAgent] │
│    → [ScoringAgent]                                         │
└─────────────────────────────────────────────────────────────┘
```

### 10 Specialized Agents

| Agent | Role |
|-------|------|
| **ScannerAgent** | Entity extraction, event identification |
| **InputParserAgent** | Canonical query structuring |
| **ResearchAgent** | Intelligence gathering & synthesis |
| **PredictorAgent** | Initial probability estimate |
| **AnalystAgent** | Bull case construction |
| **SkepticAgent** | Challenge & counter-argument (MUST disagree) |
| **ScenarioAgent** | Alternative outcome simulation |
| **ValidatorAgent** | Logic & consistency checking |
| **SynthesizerAgent** | Multi-perspective integration |
| **ScoringAgent** | Final weighted scoring |

### Intelligence Layers

- **Memory Layer**: SQLite persistence, cross-session pattern detection, calibration tracking
- **Market Movement Layer**: Multi-format odds parsing (decimal/american/fractional)
- **Polymarket Integration**: Live prediction market data via public Gamma API (no key needed)
- **Quantitative Scoring**: Fee-adjusted edge, confidence-weighted signals, Kelly Criterion sizing

### Scoring System

```
Composite Score = Σ(component × weight)

Weights:
  Predicted Probability    25%
  Confidence Score         20%
  Data Quality             15%
  Argument Strength        15%
  Counter-Argument Impact  10%
  Validation Score         10%
  Market Signal             5%

Quantitative Edge:
  Gross edge   = predicted_prob − implied_prob
  Net edge     = gross_edge − POLYMARKET_FEE_RATE   (default 2%)
  Adjusted edge = net_edge × confidence_score        (used for BET gate)

Decision Thresholds (applied to adjusted edge):
  BET   → adj_edge ≥ 10%  AND confidence ≥ 65%  AND risk < 70%  AND Kelly > 0
  WATCH → net_edge ≥ 3%   OR composite score > 58%
  SKIP  → insufficient edge, high risk, or negative Kelly
```

---

## Quick Start

### Option A — OpenRouter (free, no credit card)

```bash
# 1. Clone & setup
git clone https://github.com/Nikros07/Polymarket-Bot.git
cd Polymarket-Bot
./scripts/setup.sh        # creates venv, installs all deps

# 2. Edit .env
LLM_PROVIDER=openrouter
LLM_MODEL=meta-llama/llama-3.1-8b-instruct:free
OPENROUTER_API_KEY=sk-or-v1-your-key-here   # free at openrouter.ai

# 3. Launch Streamlit UI
./scripts/start_streamlit.sh
# → http://localhost:8501
```

**Windows:**
```bat
setup.bat
REM Edit .env (see above)
start_streamlit.bat
```

### Option B — Anthropic / OpenAI

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-6
ANTHROPIC_API_KEY=your_key_here
```

### Option C — Demo mode (no API key at all)

```env
DEMO_MODE=true
```

---

## Free OpenRouter Models

| Model | Quality | Context |
|-------|---------|---------|
| `meta-llama/llama-3.1-8b-instruct:free` | ★★★★ | 128K |
| `mistralai/mistral-7b-instruct:free` | ★★★ | 32K |
| `google/gemma-2-9b-it:free` | ★★★ | 8K |
| `qwen/qwen-2.5-7b-instruct:free` | ★★★ | 128K |

Set `LLM_MAX_TOKENS=2048` when using free models (recommended default).

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze` | POST | Start analysis session |
| `/api/analyze/{id}/stream` | GET | SSE stream of agent progress |
| `/api/analyze/{id}` | GET | Get session results |
| `/api/history` | GET | Paginated history |
| `/api/outcome/{id}` | POST | Record actual outcome |
| `/api/health` | GET | System health check |
| `/api/stats` | GET | System statistics |
| `/docs` | GET | Swagger API docs |

### Example Request

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "Will Bayern Munich win their next match?", "market_odds": "1.75"}'
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openrouter` | `anthropic` \| `openai` \| `openrouter` |
| `LLM_MODEL` | `meta-llama/llama-3.1-8b-instruct:free` | Model ID |
| `LLM_MAX_TOKENS` | `2048` | Max output tokens (keep ≤2048 for free models) |
| `OPENROUTER_API_KEY` | — | Free key at openrouter.ai |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DEMO_MODE` | `false` | Run without API keys |
| `TAVILY_API_KEY` | — | Tavily AI Search (1000 free req/month) |
| `SERPER_API_KEY` | — | Google Search fallback (serper.dev) |
| `POLYMARKET_FEE_RATE` | `0.02` | Fee deducted from edge (2%) |
| `POLYMARKET_MIN_VOLUME` | `500` | Min USD volume for market results |
| `KELLY_FRACTION` | `0.25` | Position sizing multiplier (0.25 = quarter-Kelly) |
| `BET_EDGE_THRESHOLD` | `0.10` | Min adjusted edge for BET |
| `BET_CONFIDENCE_THRESHOLD` | `0.65` | Min confidence for BET |

---

## Decision Output

Every analysis produces:

```json
{
  "decision": "BET | WATCH | SKIP",
  "predicted_probability": 0.0-1.0,
  "confidence_score": 0.0-1.0,
  "edge": -1.0-1.0,
  "risk": { "level": "low|medium|high|extreme", "warnings": [...] },
  "score_breakdown": {
    "composite_score": 0.0-1.0,
    "edge": 0.0,
    "adjusted_edge": 0.0,
    "kelly_fraction": 0.0
  },
  "bull_case": "...",
  "bear_case": "...",
  "scenarios": [...],
  "conflicts": ["agents disagreed on..."],
  "key_insights": [...],
  "reasoning_summary": "...",
  "polymarket_markets": [...]
}
```

---

## Design Principles

- **Disagreement is required**: The Skeptic agent MUST challenge every prediction
- **Conflicts are preserved**: Agent disagreements are visible, not hidden
- **Fee-aware**: Edge is always net of Polymarket's 2% fee
- **Kelly-gated**: BET is blocked when Kelly Criterion is negative (no positive EV)
- **Semi-automated**: AI suggests → human confirms → human acts
- **Universal architecture**: Extensible to any decision domain

---

## Extending

### Add a new domain

1. Create a new scanner variant in `backend/agents/`
2. Add a market data fetcher in `backend/services/`
3. Adjust scoring weights in `backend/core/scoring.py`

### Add a new agent

1. Create `backend/agents/my_agent.py` extending `OASISBaseAgent`
2. Register in `backend/core/orchestrator.py`
3. Add to the pipeline stages

---

## Tech Stack

- **UI**: Streamlit (dark theme, real-time agent cards) — `http://localhost:8501`
- **API**: FastAPI + Uvicorn + SSE — `http://localhost:8000`
- **AI Framework**: OASIS (Camel-AI) compatible + OpenRouter/Anthropic/OpenAI fallback
- **LLM**: OpenRouter free models / Anthropic Claude / OpenAI GPT-4
- **Research**: Tavily AI Search (cost-controlled) + Serper fallback
- **Prediction Markets**: Polymarket Gamma API (no key needed)
- **Storage**: SQLite via aiosqlite
