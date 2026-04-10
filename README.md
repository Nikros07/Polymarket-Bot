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
│    [ResearchAgent] ← Web/API sources                        │
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

- **Memory Layer**: SQLite persistence, cross-session pattern detection
- **Market Movement Layer**: Odds parsing, implied probability calculation
- **Confidence Calibration**: Outcome tracking, historical accuracy metrics
- **Scenario Simulation**: Full probability distribution modeling

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

Decision Thresholds:
  BET   → edge > 10%  AND confidence > 65%  AND risk < 70%
  WATCH → edge > 3%   OR interesting pattern
  SKIP  → insufficient edge or high risk
```

---

## Quick Start

### 1. Setup

```bash
./scripts/setup.sh
```

### 2. Configure

Edit `.env`:

```env
# Required for live mode:
ANTHROPIC_API_KEY=your_key_here

# OR run without API keys:
DEMO_MODE=true
```

### 3. Start

```bash
./scripts/start.sh
```

Open **http://localhost:8000**

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
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `LLM_MODEL` | `claude-opus-4-6` | Model identifier |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DEMO_MODE` | `false` | Run without API keys |
| `SERPER_API_KEY` | — | Google Search (Serper.dev) |
| `TAVILY_API_KEY` | — | Tavily AI Search |
| `BET_EDGE_THRESHOLD` | `0.10` | Minimum edge for BET |
| `BET_CONFIDENCE_THRESHOLD` | `0.65` | Minimum confidence for BET |

---

## Decision Output

Every analysis produces:

```json
{
  "decision": "BET | WATCH | SKIP",
  "predicted_probability": 0.0-1.0,
  "confidence_score": 0.0-1.0,
  "edge": -1.0 to 1.0,
  "risk": { "level": "low|medium|high|extreme", "warnings": [...] },
  "score_breakdown": { ... },
  "bull_case": "...",
  "bear_case": "...",
  "scenarios": [...],
  "conflicts": ["agents disagreed on..."],
  "key_insights": [...],
  "reasoning_summary": "..."
}
```

---

## Design Principles

- **Disagreement is required**: The Skeptic agent MUST challenge every prediction
- **Conflicts are preserved**: Agent disagreements are visible, not hidden
- **Transparency first**: Full reasoning chain is auditable
- **Semi-automated**: AI suggests → human confirms → human acts
- **Universal architecture**: Extensible to any decision domain

---

## Extending

### Add a new domain (e.g. Polymarket)

1. Create a new scanner variant in `backend/agents/`
2. Add a market data fetcher in `backend/services/`
3. Adjust scoring weights in `backend/core/scoring.py`

### Add a new agent

1. Create `backend/agents/my_agent.py` extending `OASISBaseAgent`
2. Register in `backend/core/orchestrator.py`
3. Add to the pipeline stages

---

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **AI Framework**: OASIS (Camel-AI) compatible agent architecture
- **LLM**: Anthropic Claude (primary) / OpenAI GPT-4 (alternative)
- **Storage**: SQLite via aiosqlite
- **Streaming**: Server-Sent Events (SSE)
- **Frontend**: Vanilla JS trading dashboard
