"""Canonical LLM smoke suite manifest.

Single source of truth for the minimal operator-facing LLM smoke checks.
Use scripts/run_llm_smoke.sh to execute this suite.
"""

LLM_SMOKE_NODEIDS = [
    # Core agent loop behavior (no network, stubbed LLM)
    "tests/smoke/test_agent_loop.py",
    # Tool-calling reliability guards
    "tests/unit/test_tool_call_reliability.py",
    # Strict no-fallback enforcement in execution paths
    "tests/unit/test_no_execution_fallbacks.py",
    # Contract-first resource/role capability checks
    "tests/unit/test_smoke_contracts.py",
]
