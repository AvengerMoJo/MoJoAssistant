# Release Notes — v1.2.8-beta

## Theme: Hardening — Reliability, Resilience, and Housekeeping

v1.2.8 closes the remaining rough edges from v1.2.7: tool-call failure modes that
were silent, optional dependencies that crashed on absent packages, deprecation
warnings that polluted every test run, and a root directory that had accumulated
stale files. No new features — just a cleaner, more reliable foundation.

Test suite: **245 passed, 0 warnings, 0 failures.**

---

## 1. Tool-Call Reliability (`agentic_executor.py`, `role_chat.py`)

### Malformed JSON arguments → error feedback to model

When a model emits a tool call with invalid JSON in the `arguments` field the
executor previously fell back silently to `{}` and ran the tool anyway. The model
received a response as if the call succeeded — no feedback, no chance to self-correct.

**Fix:** parse failure now returns a structured error to the model:

```json
{
  "error": "Your tool call arguments for 'memory_search' were not valid JSON (…).
            Please call the tool again with properly formatted JSON arguments."
}
```

`_execute_single_tool` is not called at all for the malformed entry.

### Consecutive no-tool drift forcing

When the model responds with prose (no tool calls, no final answer) for two
consecutive iterations while tools are available, the executor injects a forcing
nudge listing the available tool names:

> "You have responded 2 times without calling any tools. You have the following
> tools available: ['memory_search', …]. Call a tool now to make progress, or
> provide your `<FINAL_ANSWER>` if the task is complete."

Counter resets after the nudge and on any actual tool call.

### Role chat tool-loop budget

When `MAX_CHAT_ITERATIONS` tool calls exhaust the budget, `role_chat.py` now
forces one final text-only LLM call (`tools=None`) so the user gets an answer
instead of an empty/partial response. Residual `<think>` tokens stripped from
that final answer.

---

## 2. ConfigDoctor — v1.2.6/v1.2.7 Checks (`app/config/doctor.py`)

Four new check categories added to `scripts/config_doctor.py`:

| Category | What it catches |
|----------|----------------|
| `policy` | Missing or invalid `policy_patterns.json` / `behavioral_patterns.json`; personal overlay load errors |
| `memory` | `MEMORY_PATH` not writable; dreaming storage path resolving outside `MEMORY_PATH` (catches the v1.2.6 `JsonFileBackend` bug class) |
| `scheduler` | `scheduler_config.json` missing or invalid JSON; jobs referencing unknown roles; supports both `"jobs"` and `"default_tasks"` key names |
| `role/local_only` | Role has `local_only: true` but no `free`-tier resource is configured — role can never run |

**Bug caught and fixed:** `security_sentinel` role had `model_preference: "lmstudio"`
(a resource ID, not a model name). The executor would have passed `"lmstudio"` as
the model string to the API, causing every sentinel run to fail. Field removed —
`local_only: true` already constrains to free-tier local resources.

Doctor now exits with **0 errors** on a correctly configured install.

---

## 3. Dependency Resilience (`app/memory/simplified_embeddings.py`)

`numpy` was a hard top-level import. On a clean install without numpy, the entire
embeddings module failed to import — breaking memory search silently.

**Fix:**
- `numpy` wrapped in `try/except`; `_numpy_available` flag controls all `np.` call sites
- `cosine_similarity` falls back to pure-Python `math` when numpy is absent
- `np.ndarray` isinstance checks guarded by `_numpy_available`
- `np.random.normal` replaced with `random.gauss` (no numpy dependency)

`sentence_transformers` was already soft-imported. Both optional deps now degrade
gracefully — embeddings fall back to random vectors, which is the existing
behaviour when no model is configured.

---

## 4. `datetime.utcnow()` Deprecation — 9 Files, 20 Call Sites

Python 3.12 deprecated `datetime.utcnow()`. Every test run generated 13 deprecation
warnings from the affected files.

**Fix:** `datetime.utcnow()` → `datetime.now(timezone.utc)` across all call sites.
`timezone` added to `from datetime import …` where missing. Callers that appended
`"Z"` manually now use `.isoformat().replace("+00:00", "Z")` to preserve the
existing wire format.

**Files patched:**
- `app/scheduler/executor.py`
- `app/mcp/adapters/audit_log.py`
- `app/mcp/mcp_service.py`
- `app/mcp/opencode/manager.py`, `state_manager.py`, `config_manager.py`, `models.py`
- `app/mcp/claude_code/manager.py`, `models.py`

---

## 5. Root Directory Cleanup

| File | Action | Destination |
|------|--------|------------|
| `release_notes.md` | Moved | `docs/releases/RELEASE_NOTES_v1.1.5-beta.md` |
| `gap_1.2.6` | Moved | `docs/releases/GAP_ANALYSIS_v1.2.6.md` |
| `README_zh_TW.md` | Moved | `docs/README_zh_TW.md` |
| `demo_tool_based_config.py` | Moved | `scripts/` |
| `run_mcp.sh`, `run_dev.sh`, `run_dev_watch.sh`, `run_cli.sh` | Moved | `scripts/` (paths updated) |
| `final_state.json`, `interrupt_state.json` | Deleted | stale temp state |
| `mcp_new.log`, `mcp_server.log`, `server.log`, `server_output.log` | Deleted | log files (gitignored) |

Run scripts updated to resolve paths relative to project root (`SCRIPT_DIR/..`).
`.gitignore` updated to unblock `run_cli.sh` and `run_mcp.sh` (were excluded as
auto-generated; now checked-in under `scripts/`).

---

## 6. Roadmap — v2.0.0 Rename + Full Planned Schedule

- Public release milestone renamed from `v1.0` → `v2.0.0` throughout
- Priority matrix updated with `Status` column — all completed items marked ✅
- Full planned release schedule added (v1.2.8 → v2.0.0) covering all previously
  undated ideas: coding agent bridge, per-source routing, resource pool unification,
  terminal tools, HttpAgentExecutor, Policy Enforcement Agent, PII/sanitization,
  hybrid memory search

**v2.0.0 remaining gates (3 open):**
1. Smoke suite (`tests/smoke/`) — does not exist yet
2. First-run installer polish + demo roles/tasks + privacy report view
3. `INSTALL.md` — supported OS/Python/model, required vs optional env vars

---

## Upgrade Notes

No config changes required. `scripts/run_mcp.sh` and friends moved to `scripts/` —
update any shortcuts or aliases pointing to the old root-level paths.
