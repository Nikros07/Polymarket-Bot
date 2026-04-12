#!/usr/bin/env bash
# ============================================================
# AI Decision System — Streamlit UI Launcher (Linux / Mac)
# ============================================================
set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Change to repo root regardless of where the script is called from
cd "$(dirname "$0")/.."

# ── Activate virtual environment ──────────────────────────────────────────
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo -e "${YELLOW}[WARN] No .venv found — using system Python.${NC}"
    echo -e "${YELLOW}       Run ./scripts/setup.sh first to create the venv.${NC}"
fi

# ── Load .env into environment ────────────────────────────────────────────
if [ -f ".env" ]; then
    # Export non-comment, non-empty lines
    set -o allexport
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    set +o allexport
fi

echo -e "${BLUE}
╔═══════════════════════════════════════════╗
║      AI Decision System — Streamlit       ║
╚═══════════════════════════════════════════╝${NC}"
echo -e "  LLM:  ${LLM_PROVIDER:-openrouter} / ${LLM_MODEL:-meta-llama/llama-3.1-8b-instruct:free}"
echo -e "  Mode: ${DEMO_MODE:+DEMO}${DEMO_MODE:-LIVE}"
echo -e "  URL:  ${GREEN}http://localhost:8501${NC}"
echo ""

exec streamlit run streamlit_app.py \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false
