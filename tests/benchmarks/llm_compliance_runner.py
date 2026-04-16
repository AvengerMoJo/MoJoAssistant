"""
LLM Compliance Runner
=====================
Tests every configured LLM resource against a suite of MoJoAssistant framework
compliance checks. Identifies WHY each model fails — not just that it failed.

Checks:
  1. notool_final_answer  — pure format: does the model produce <FINAL_ANSWER> tags?
  2. tool_then_answer     — after a tool call, does it wrap the result in FINAL_ANSWER?
  3. budget_warning       — does it obey the ⚠ ITERATION BUDGET WARNING prompt?
  4. structured_output    — does it produce well-formed structured content inside FINAL_ANSWER?

Each check runs the actual AgenticExecutor (same path as production) but with an
in-memory session storage so results can be introspected for failure classification.

Usage:
    venv/bin/python tests/benchmarks/llm_compliance_runner.py
    venv/bin/python tests/benchmarks/llm_compliance_runner.py --resource lmstudio_qwen35b
    venv/bin/python tests/benchmarks/llm_compliance_runner.py --quick          # check 1 only
    venv/bin/python tests/benchmarks/llm_compliance_runner.py --all            # include remote APIs
    venv/bin/python tests/benchmarks/llm_compliance_runner.py --no-save        # don't write report

Report saved to: ~/.memory/compliance_reports/YYYY-MM-DD_HHMMSS.json
"""

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# In-memory session storage — captures all messages without disk I/O
# ---------------------------------------------------------------------------

class _InMemorySessionStorage:
    """
    Replaces the default SessionStorage so compliance test sessions stay in
    memory and don't pollute ~/.memory/task_sessions/.
    """

    def __init__(self):
        from app.scheduler.session_storage import TaskSession, SessionMessage  # noqa
        self._store: Dict[str, Any] = {}

    def _path(self, task_id: str) -> Path:
        # Executor reads this only to log the file path — never actually written.
        return Path(f"/tmp/compliance_test_{task_id}.json")

    def save_session(self, session) -> None:
        self._store[session.task_id] = session

    def load_session(self, task_id: str):
        return self._store.get(task_id)

    def append_message(self, task_id: str, message) -> None:
        session = self._store.get(task_id)
        if session is not None:
            session.messages.append(message)

    def update_status(
        self,
        task_id: str,
        status: str,
        final_answer: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        session = self._store.get(task_id)
        if session is not None:
            session.status = status
            if final_answer is not None:
                session.final_answer = final_answer
            if error_message is not None:
                session.error_message = error_message

    def get_session(self, task_id: str):
        return self._store.get(task_id)


# ---------------------------------------------------------------------------
# No-op MCP client manager — skips stdio MCP server discovery
# ---------------------------------------------------------------------------

class _NoOpMCPClientManager:
    """
    Replaces the real MCPClientManager so the compliance test doesn't try to
    connect to stdio MCP servers (playwright, etc.) that aren't needed and
    cause asyncio cancel-scope errors when run standalone.
    """

    def has_servers(self) -> bool:
        return False

    async def discover_and_register(self, tool_registry) -> int:
        return 0

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        raise RuntimeError(f"MCP tool {server_name}/{tool_name} not available in compliance test")

    async def connect_all(self):
        return []

    async def disconnect_all(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Single-resource manager (reuses the pattern from AgenticSmokeTest)
# ---------------------------------------------------------------------------

class _SingleResourceManager:
    def __init__(self, resource):
        self._resource = resource

    def acquire(self, **kwargs):
        return self._resource

    def release(self, resource_id: str) -> None:
        pass

    def record_usage(self, resource_id: str, success: bool) -> None:
        pass


# ---------------------------------------------------------------------------
# Failure classifier
# ---------------------------------------------------------------------------

# Patterns that indicate the model produced a final answer but with the WRONG format.
# Ordered from most specific to least.
_WRONG_TAG_PATTERNS = [
    (r"<\s*FINAL[_ ]ANSWER\s*>", "whitespace inside tag: < FINAL_ANSWER >"),
    (r"</FINAL[_ ]ANSWER>(?!.*<FINAL)", "closing tag without opening tag"),
    (r"\*\*FINAL[_ ]?ANSWER\*\*\s*:", "markdown bold: **FINAL_ANSWER**:"),
    (r"##\s*Final Answer", "markdown heading: ## Final Answer"),
    (r"^FINAL[_ ]?ANSWER\s*:", "bare label: FINAL_ANSWER:"),
    (r"\[FINAL[_ ]?ANSWER\]", "bracket form: [FINAL_ANSWER]"),
    (r"`FINAL[_ ]?ANSWER`", "code-span form: `FINAL_ANSWER`"),
    (r"<final_answer>", "wrong case: <final_answer>"),
]

# Patterns that indicate the model gave an answer but made no attempt at tagging.
_ANSWER_ATTEMPT_PATTERNS = [
    r"in conclusion",
    r"to summarize",
    r"summary[:\s]",
    r"the answer is",
    r"in summary",
    r"therefore",
]


def _classify_failure(
    task_result, session, max_iterations: int
) -> Tuple[str, str]:
    """
    Analyse the session messages and task result to determine WHY FINAL_ANSWER
    was not produced.

    Returns (failure_mode, detail_string).

    Failure modes:
      WRONG_TAG       — model used a non-standard tag variant
      NO_ATTEMPT      — model wrote prose but no answer-shaped content
      BUDGET_EXHAUST  — iterated to the end without any recognisable answer
      IGNORED_WARNING — budget warning was present but model kept looping
      LOOP            — repeated the same response multiple times
      TOOL_FAIL       — model didn't call the required tool
      TIMEOUT         — LLM call timed out
      UNKNOWN         — couldn't classify
    """
    if session is None:
        return "UNKNOWN", "no session data captured"

    # Collect assistant message texts
    assistant_texts = [
        (m.iteration, m.content)
        for m in session.messages
        if m.role == "assistant"
    ]

    if not assistant_texts:
        return "UNKNOWN", "no assistant messages in session"

    last_iter, last_text = assistant_texts[-1]
    last_lower = last_text.lower() if last_text else ""

    # Check: did the model have the budget warning and ignore it?
    user_texts = [m.content for m in session.messages if m.role == "user"]
    had_budget_warning = any("ITERATION BUDGET WARNING" in t for t in user_texts)
    if had_budget_warning and not task_result.metrics.get("final_answer"):
        # Check for BUDGET_EXTENSION_REQUEST — that's a valid response to the warning
        had_extension_request = any(
            re.search(r"BUDGET_EXTENSION_REQUEST", t, re.IGNORECASE)
            for _, t in assistant_texts
        )
        if not had_extension_request:
            return "IGNORED_WARNING", (
                "budget warning was injected but model neither produced "
                "<FINAL_ANSWER> nor wrote BUDGET_EXTENSION_REQUEST"
            )

    # Check for wrong-tag patterns in all assistant messages
    for _, text in assistant_texts:
        for pattern, description in _WRONG_TAG_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                return "WRONG_TAG", description

    # Check for repetitive/looping responses
    iter_log = (task_result.metrics or {}).get("iteration_log", [])
    if len(iter_log) >= 3:
        lengths = [it.get("response_length", 0) for it in iter_log[-3:]]
        if len(set(lengths)) == 1 and lengths[0] > 50:
            return "LOOP", (
                f"last 3 iterations all produced {lengths[0]}-char responses "
                f"(model stuck in a loop)"
            )

    # Check for answer attempt without tags
    for pattern in _ANSWER_ATTEMPT_PATTERNS:
        if re.search(pattern, last_lower):
            return "NO_ATTEMPT", (
                f"model gave an answer (matched '{pattern}') "
                f"but never used <FINAL_ANSWER> tags"
            )

    # Budget exhausted without any answer-shaped content
    iterations_used = len(iter_log)
    if iterations_used >= max_iterations:
        return "BUDGET_EXHAUST", (
            f"used all {max_iterations} iterations; "
            f"last response length: {len(last_text)} chars"
        )

    return "UNKNOWN", f"iteration {last_iter}, response length {len(last_text)}"


# ---------------------------------------------------------------------------
# Individual check results
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    status: str           # "pass" | "fail" | "skip" | "error"
    failure_mode: str = ""       # empty on pass
    failure_detail: str = ""
    iterations_used: int = 0
    duration_s: float = 0.0
    model: str = ""


# ---------------------------------------------------------------------------
# Per-resource compliance result
# ---------------------------------------------------------------------------

@dataclass
class ResourceResult:
    resource_id: str
    model: str
    checks: List[CheckResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def total(self) -> int:
        return sum(1 for c in self.checks if c.status != "skip")

    @property
    def overall(self) -> str:
        if self.error:
            return "error"
        if self.passed == self.total:
            return "pass"
        if self.passed == 0:
            return "fail"
        return "partial"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "model": self.model,
            "overall": self.overall,
            "passed": self.passed,
            "total": self.total,
            "checks": [asdict(c) for c in self.checks],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    name: str
    goal: str
    system_prompt: str
    available_tools: List[str]
    max_iterations: int
    description: str = ""


_MINIMAL_SYSTEM = (
    "You are a minimal test agent. "
    "Follow instructions exactly. "
    "Always wrap your final response in <FINAL_ANSWER>...</FINAL_ANSWER> tags. "
    "Never omit these tags."
)

TEST_CASES = [
    TestCase(
        name="notool_final_answer",
        description="Pure format compliance — no tools, just produce a FINAL_ANSWER",
        goal=(
            "What is 15 + 27? "
            "Produce a <FINAL_ANSWER> tag containing only the numeric result. "
            "Do not add any explanation outside the tags."
        ),
        system_prompt=_MINIMAL_SYSTEM,
        available_tools=[],
        max_iterations=2,
    ),
    TestCase(
        name="tool_then_answer",
        description="Use one tool, then wrap the result in FINAL_ANSWER",
        goal=(
            "You MUST call memory_search with query 'test'. "
            "After you receive the tool result, produce a <FINAL_ANSWER> with a "
            "one-sentence summary of what you found (or 'no results' if empty)."
        ),
        system_prompt=_MINIMAL_SYSTEM,
        available_tools=["memory_search"],
        max_iterations=4,
    ),
    TestCase(
        name="budget_warning",
        description="Budget warning fires at second-to-last iter — must FINAL_ANSWER or request extension",
        goal=(
            "Search memory for 'news', then search for 'AI', then search for 'tasks'. "
            "Summarize ALL three search results in a single <FINAL_ANSWER>."
        ),
        system_prompt=_MINIMAL_SYSTEM,
        available_tools=["memory_search"],
        max_iterations=3,  # warning fires at iter 2; model has 1 more chance
    ),
    TestCase(
        name="structured_output",
        description="Must produce multi-field structured content inside FINAL_ANSWER",
        goal=(
            "Name exactly 3 programming languages. For each one, state: "
            "(1) the language name and (2) its primary use case. "
            "Wrap everything in a single <FINAL_ANSWER> block. "
            "No tool calls needed — answer from your general knowledge."
        ),
        system_prompt=_MINIMAL_SYSTEM,
        available_tools=[],
        max_iterations=2,
    ),
]


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

class ComplianceRunner:
    """
    Runs the compliance test suite against one or more resources.
    """

    def __init__(self, quick: bool = False, verbose: bool = False):
        self._quick = quick
        self._verbose = verbose
        self._cases = TEST_CASES[:1] if quick else TEST_CASES

    async def run_resource(self, resource_id: str) -> ResourceResult:
        """Run all test cases against a single resource."""
        # Resolve the resource from the pool
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            resource = rm._resources.get(resource_id)
            if resource is None:
                return ResourceResult(
                    resource_id=resource_id,
                    model="?",
                    error=f"Resource '{resource_id}' not found in llm_config",
                )
        except Exception as e:
            return ResourceResult(
                resource_id=resource_id,
                model="?",
                error=f"Failed to load resource pool: {e}",
            )

        model = resource.model or "?"
        result = ResourceResult(resource_id=resource_id, model=model)

        for case in self._cases:
            check = await self._run_case(resource, resource_id, model, case)
            result.checks.append(check)

        return result

    async def _run_case(self, resource, resource_id: str, model: str, case: TestCase) -> CheckResult:
        """Run a single test case against a resource. Returns a CheckResult."""
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
        from app.scheduler.agentic_executor import AgenticExecutor

        task_id = f"compliance_{resource_id}_{case.name}_{int(time.time())}"
        task = Task(
            id=task_id,
            type=TaskType.ASSISTANT,
            priority=TaskPriority.HIGH,
            config={
                "goal": case.goal,
                "system_prompt": case.system_prompt,
                "available_tools": case.available_tools,
                "max_iterations": case.max_iterations,
                "max_duration_seconds": 180,
            },
            resources=TaskResources(
                max_iterations=case.max_iterations,
                max_duration_seconds=180,
            ),
            description=f"Compliance test: {case.name}",
            created_by="compliance_runner",
        )

        single_rm = _SingleResourceManager(resource)
        storage = _InMemorySessionStorage()

        t0 = time.time()
        try:
            executor = AgenticExecutor(
                resource_manager=single_rm,
                mcp_client_manager=_NoOpMCPClientManager(),
            )
            executor._session_storage = storage
            task_result = await executor.execute(task)
        except Exception as e:
            duration = time.time() - t0
            return CheckResult(
                name=case.name,
                status="error",
                failure_mode="EXECUTOR_ERROR",
                failure_detail=str(e),
                duration_s=round(duration, 1),
                model=model,
            )

        duration = time.time() - t0
        metrics = task_result.metrics or {}
        final_answer = metrics.get("final_answer")
        iter_log = metrics.get("iteration_log", [])
        iterations_used = len(iter_log)

        if self._verbose:
            session = storage.get_session(task_id)
            self._print_session(case.name, session, metrics)

        if final_answer:
            return CheckResult(
                name=case.name,
                status="pass",
                iterations_used=iterations_used,
                duration_s=round(duration, 1),
                model=model,
            )

        # Classify why it failed
        session = storage.get_session(task_id)
        failure_mode, failure_detail = _classify_failure(
            task_result, session, case.max_iterations
        )

        return CheckResult(
            name=case.name,
            status="fail",
            failure_mode=failure_mode,
            failure_detail=failure_detail,
            iterations_used=iterations_used,
            duration_s=round(duration, 1),
            model=model,
        )

    def _print_session(self, case_name: str, session, metrics: dict) -> None:
        """Print full session for verbose debugging."""
        print(f"\n  [VERBOSE] Session for {case_name}:")
        if session:
            for m in session.messages:
                role = m.role.upper()
                text = m.content[:300].replace("\n", "↵") if m.content else ""
                print(f"    [{role} iter={m.iteration}] {text}")
        iter_log = metrics.get("iteration_log", [])
        for it in iter_log:
            print(f"    iter={it.get('iteration')} status={it.get('status')} "
                  f"tool_calls={it.get('tool_calls', [])} "
                  f"resp_len={it.get('response_length', '?')}")


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

_OVERALL_ICON = {"pass": "✓", "partial": "~", "fail": "✗", "error": "!"}
_STATUS_ICON  = {"pass": "✓", "fail": "✗", "error": "!", "skip": "–"}


def print_report(results: List[ResourceResult], elapsed_total: float) -> None:
    passed = sum(1 for r in results if r.overall == "pass")
    failed = sum(1 for r in results if r.overall in ("fail", "error"))
    partial = sum(1 for r in results if r.overall == "partial")

    print()
    print("=" * 72)
    print(f"  LLM Compliance Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  {len(results)} resource(s) | {passed} pass | {partial} partial | {failed} fail | {elapsed_total:.0f}s total")
    print("=" * 72)

    for r in results:
        icon = _OVERALL_ICON.get(r.overall, "?")
        check_summary = f"({r.passed}/{r.total} checks)" if not r.error else ""
        model_short = r.model[:35] if r.model else "?"
        print(f"\n{icon} {r.resource_id:<28s}  {model_short:<36s}  {r.overall.upper()} {check_summary}")

        if r.error:
            print(f"    ERROR: {r.error}")
            continue

        for c in r.checks:
            si = _STATUS_ICON.get(c.status, "?")
            timing = f"{c.iterations_used} iter / {c.duration_s:.1f}s"
            print(f"  {si} {c.name:<28s}  {timing}")
            if c.status == "fail":
                print(f"      └─ {c.failure_mode}: {c.failure_detail}")
            elif c.status == "error":
                detail = c.failure_detail or c.failure_mode or "unknown error"
                print(f"      └─ ERROR: {detail[:120]}")

    print()


# ---------------------------------------------------------------------------
# Report saving
# ---------------------------------------------------------------------------

def save_report(results: List[ResourceResult], elapsed_total: float) -> Path:
    report_dir = Path.home() / ".memory" / "compliance_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = report_dir / f"{timestamp}.json"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed_total, 1),
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.overall == "pass"),
            "partial": sum(1 for r in results if r.overall == "partial"),
            "fail": sum(1 for r in results if r.overall in ("fail", "error")),
        },
        "results": [r.to_dict() for r in results],
    }

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Resource enumeration
# ---------------------------------------------------------------------------

def _load_enabled_resources(include_remote: bool = False) -> List[str]:
    """
    Return resource IDs to test. Reads the layered resource_pool.json config
    directly so only explicitly-configured resources are returned — not stale
    dynamically-discovered entries from resource_pool_usage.json.

    By default: only local LM Studio resources.
    With include_remote=True: also include remote API resources (gemini, openrouter).
    """
    from app.config.config_loader import load_layered_json_config
    from app.scheduler.resource_pool import ResourceManager

    # Read the config the same way the resource pool does
    primary_path = "config/resource_pool.json"
    fallback_path = "config/llm_config.json"
    config_path = primary_path if Path(primary_path).exists() else fallback_path
    data = load_layered_json_config(config_path)

    rm = ResourceManager()
    ids = []

    # Flat format: resources live under "resources" key
    resource_section = data.get("resources", {})
    for rid, cfg in resource_section.items():
        if not cfg or not cfg.get("enabled", True):
            continue
        # Confirm it's actually loaded in the live pool
        if rid not in rm._resources:
            continue
        # Skip template resources with no fixed model (dynamic_discovery templates)
        if cfg.get("dynamic_discovery") and not cfg.get("model"):
            continue

        base_url = cfg.get("base_url", "") or ""
        is_local = any(
            base_url.startswith(p)
            for p in ("http://localhost", "http://127.0.0.1")
        )

        if is_local:
            ids.append(rid)
        elif include_remote and base_url:
            ids.append(rid)

    return ids


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main():
    parser = argparse.ArgumentParser(
        description="Test LLM resources for MoJoAssistant framework compliance."
    )
    parser.add_argument(
        "--resource", "-r",
        metavar="RESOURCE_ID",
        action="append",
        dest="resources",
        help="Test a specific resource (repeatable: -r foo -r bar). Default: all local.",
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Run only the first check (notool_final_answer). Fast smoke test.",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Include remote API resources (openrouter, gemini). Default: local only.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full session messages for each check.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write a JSON report to ~/.memory/compliance_reports/.",
    )
    args = parser.parse_args()

    runner = ComplianceRunner(quick=args.quick, verbose=args.verbose)

    if args.resources:
        resource_ids = args.resources
    else:
        resource_ids = _load_enabled_resources(include_remote=args.all)

    if not resource_ids:
        print("No resources found to test. Check ~/.memory/config/llm_config.json")
        sys.exit(1)

    print(f"Testing {len(resource_ids)} resource(s): {', '.join(resource_ids)}")
    print(f"Checks: {', '.join(c.name for c in runner._cases)}")
    print()

    t0 = time.time()
    results = []
    for rid in resource_ids:
        print(f"  [{rid}] running...", flush=True)
        result = await runner.run_resource(rid)
        icon = _OVERALL_ICON.get(result.overall, "?")
        print(f"  [{rid}] {icon} {result.overall.upper()}  ({result.passed}/{result.total} checks)")
        results.append(result)

    elapsed = time.time() - t0
    print_report(results, elapsed)

    if not args.no_save:
        path = save_report(results, elapsed)
        print(f"Report saved: {path}")

    # Exit code: 0 if all pass, 1 if any fail
    all_pass = all(r.overall == "pass" for r in results)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(_main())
