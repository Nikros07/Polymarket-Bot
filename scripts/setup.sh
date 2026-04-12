#!/usr/bin/env bash
# ============================================================
# AI Decision System — Setup Script
# ============================================================
set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}
╔═══════════════════════════════════════════╗
║      AI Decision System — Setup           ║
║      OASIS Multi-Agent Engine             ║
╚═══════════════════════════════════════════╝${NC}"

# ── Check Python ─────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo -e "${RED}✗ Python 3 not found. Please install Python 3.10+${NC}"
  exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} found${NC}"

# ── Create Virtual Environment ────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo -e "${BLUE}→ Creating virtual environment...${NC}"
  python3 -m venv .venv
  echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

source .venv/bin/activate

# ── Install Dependencies ──────────────────────────────────────────────────
echo -e "${BLUE}→ Installing dependencies (FastAPI + Streamlit + AI)...${NC}"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓ Dependencies installed${NC}"

# ── Environment File ──────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo -e "${YELLOW}→ Creating .env from template...${NC}"
  cp .env.example .env
  echo -e "${YELLOW}
⚠ IMPORTANT: Edit .env and add your API key(s):
  - OPENROUTER_API_KEY=sk-or-v1-...   ← Free tier at openrouter.ai (recommended)
  - ANTHROPIC_API_KEY=your_key         ← Claude models
  - OPENAI_API_KEY=your_key            ← OpenAI models
  - Or set DEMO_MODE=true to run with simulated responses
${NC}"
else
  echo -e "${GREEN}✓ .env file exists${NC}"
fi

# ── Create Data Directory ─────────────────────────────────────────────────
mkdir -p backend/data backend/logs
echo -e "${GREEN}✓ Data directories ready${NC}"

echo -e "${GREEN}
╔═══════════════════════════════════════════╗
║           Setup Complete!                 ║
╚═══════════════════════════════════════════╝

Next steps:
  1. Edit .env and set your API key:
       OPENROUTER_API_KEY=sk-or-v1-...  ← free at openrouter.ai
       LLM_PROVIDER=openrouter
       LLM_MODEL=meta-llama/llama-3.1-8b-instruct:free
     (or set DEMO_MODE=true for testing without a key)

  2. Start the Streamlit UI:
       ./scripts/start_streamlit.sh

  3. Open your browser:
       http://localhost:8501

  Optional — also start the FastAPI backend:
       ./scripts/start.sh  →  http://localhost:8000/docs
${NC}"
