#!/usr/bin/env bash
# ============================================================
# AI Decision System — Start Script
# ============================================================
set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cd "$(dirname "$0")/.."

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Load .env
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs -d '\n' 2>/dev/null || true)
fi

PORT="${APP_PORT:-8000}"
HOST="${APP_HOST:-0.0.0.0}"

echo -e "${BLUE}
╔═══════════════════════════════════════════╗
║      AI Decision System Starting          ║
╚═══════════════════════════════════════════╝${NC}"
echo -e "  LLM:  ${LLM_PROVIDER:-anthropic} / ${LLM_MODEL:-claude-opus-4-6}"
echo -e "  Mode: ${DEMO_MODE:+DEMO}${DEMO_MODE:-LIVE}"
echo -e "  URL:  http://localhost:${PORT}"
echo ""

exec uvicorn backend.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --reload \
  --log-level info
