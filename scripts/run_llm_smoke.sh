#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NODEIDS=$(python3 - <<'PY'
from tests.smoke.llm_smoke_suite import LLM_SMOKE_NODEIDS
print(" ".join(LLM_SMOKE_NODEIDS))
PY
)

echo "[llm-smoke] running: $NODEIDS"
pytest -q $NODEIDS
