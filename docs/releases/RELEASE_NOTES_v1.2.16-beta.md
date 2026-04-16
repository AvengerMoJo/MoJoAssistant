# Release Notes — v1.2.16-beta

**Date:** 2026-04-16  
**Branch:** wip_v1.2.16 → main  
**Tag:** v1.2.16-beta  
**Commits since v1.2.14-beta:** 39

---

## Theme: Role Maturity, Execution Robustness, and Framework Learning

v1.2.16 focuses on three areas: making agents more reliable when running on local models (execution robustness), making the system smarter over time without manual intervention (framework learning), and making the infrastructure observable and self-healing (config doctor, capability pipeline, benchmarks).

---

## New Features

### Two-Tier Role Growth Architecture

Roles now accumulate learning in two distinct tiers, each with different scope.

**Framework knowledge** (`scope="framework"`) — shared across all agents:
- `add_conversation(scope="framework")` writes to a shared `__framework__` store
- `_orient_from_memory` now searches both role-private (5 hits) and framework (3 hits) at every task start — every agent sees framework patterns automatically
- `_reflect_to_memory` auto-detects workflow problems (≥2 empty responses, ≥2 final-answer rejections) and writes a framework pattern entry with diagnosis and mitigation hints
- ABCD dreaming archives are now indexed back into the searchable knowledge base — previously the pipeline ran but its output was invisible to agents

**Personal knowledge** (`scope="role"`, default) — role-private, unchanged behavior:
- `add_conversation()` with no scope writes to the role's private store only

Design rationale: `docs/architecture/two_tier_growth_design.md`

### ConfigHealer — Runtime-Data-Driven Config Improvement

`doctor(action="improve")` or `config(action="doctor_improve")` analyses running system health and proposes concrete config fixes — not just diagnostics.

Improvement categories:
- Unreachable resources detected → inline `api_key` fix suggested
- Stale `agentic_capable` values → reset proposed
- Missing role capabilities → catalog-driven fix generated
- Model-tier mismatches → rebalance suggested

### 3-Layer Capability Resolution (`CapabilityResolver`)

Tool names resolved automatically at dispatch time — no client guesswork.

Resolution order:
1. **System defaults** — `ask_user` always present; `knowledge` + `orchestration` for every agent
2. **Role capabilities** — `role.capabilities[]` expanded via catalog + registry
3. **Runtime override** — `available_tools` with modifier syntax (`"+terminal"`, `"-web"`, or full replace)

`ask_user` is re-applied after all overrides and cannot be removed.

### Role System Prompt Engine (`RoleTemplateEngine`)

System prompts generated dynamically from role definition at dispatch time. Roles no longer need a hard-coded `system_prompt` string — persona, boundaries, tool guidance, and behavior rules are assembled from role fields.

### SecurityGate Per-Task `danger_budget` Override

Tasks can now set `danger_budget` in config to override the role default for a single run. Useful for high-privilege provisioning tasks without permanently raising the role's budget.

### MCP Health Checks in Config Doctor

`doctor(action="check")` now includes MCP connectivity checks alongside resource pool health. Reports which MCP servers are unreachable and why.

### daemon_restart Module Reload

`daemon_restart` now reloads core modules (`benchmark_store`, `agentic_executor`, `doctor`, scheduler core) without a full service restart. `tools.py` itself (the MCP server) still requires `systemctl --user restart mojoassistant`.

### Knowledge Isolation Hardened

- `knowledge_search` is role-scoped in code, not just prompt — a role cannot read another role's private store even if it tries
- `memory_search` remains global/user-owned
- `role_chat` was searching user personal memory — fixed to use role-scoped knowledge
- ORIENT/REFLECT phases search agent's own knowledge only, never user memory
- Shared docs no longer leak into role-scoped searches

### Systemd Service Scripts

`scripts/install_service.sh` and `scripts/mojoassistant.service` for persistent 24/7 operation as a Linux systemd user service.

---

## Bug Fixes

### Empty Response Loop (Critical)

**Root cause:** Qwen (and other thinking models) sometimes put their entire response inside `<think>` tags. After stripping, `response_text` becomes `""`. The executor was appending an empty assistant message to context, burning an iteration, and injecting a generic continue prompt — further confusing the model.

**Fix:** Detect empty-after-strip with raw content present. Inject targeted nudge ("your response was empty after thinking — provide a tool call or FINAL_ANSWER now"). Log as `status="empty_response"`. Continue without advancing the drift counter or appending the empty message to history.

**Bonus:** `<think>` block content is now preserved as `metadata.reasoning` on the `SessionMessage` record — available for debugging, `task_session_read`, and the dreaming pipeline. `session_compactor` includes reasoning at 600 chars under `[model reasoning (think)]` so the ABCD pipeline has chain-of-thought context for richer C-cluster synthesis.

### Qwen XML Tool Call Leakage

**Root cause:** Qwen (and some local models) output tool call markup as plain text in the response body instead of via the function-call API. The smoke test missed this because it only tested `memory_search` (read-only, single step) — the XML bug surfaces on `write_file` in multi-step tasks.

**Executor fix:** `_extract_xml_tool_calls()` detects both formats:
- Pattern A: `<tool_call><function=name>...</function></tool_call>` (Qwen jinja template leak)
- Pattern B: bare `<tool_name>...</tool_name>` for known tools

Detected calls are converted to real function calls transparently. The XML markup is stripped from visible response_text so it doesn't accumulate in context.

**Smoke test fix:** New `write_workflow` check requires `write_file` to be called AND verifies the file exists on disk afterward. A model that describes the write in text instead of calling the function will fail and get `agentic_capable=False`.

### agentic_capable TTL

**Root cause:** Smoke test results were stored as `{resource_id: bool}` with no timestamp. A single failed test permanently blocked a working model with no expiry.

**Fix:** Storage format changed to `{resource_id: {"value": bool, "tested_at": ISO timestamp}}`. Results older than 7 days (`AGENTIC_CAPABLE_TTL_DAYS`) are treated as `None` — the next smoke test runs rather than the old result blocking the resource. `_load_meta()` migrates legacy bool format transparently.

### Startup Recovery

- PENDING tasks on startup now retry (previously silently dropped)
- Zombie task cleanup on startup drain with configurable timeout
- One-shot interrupted tasks detected and re-queued

### HITL Executor Fixes

- `ask_user` pause correctly saves task state and resumes from exact iteration
- Budget extension granted via HITL reply (`BUDGET_EXTENSION_REQUEST`) persists across resume
- Empty HITL question no longer creates orphan waiting state

### scheduler(action="get") Response Trimming

Full `task.to_dict()` output replaced with compact view:
- `goal`, `conversation_text`, `system_prompt` truncated to 200 chars
- `pending_question` surfaced at top level (no longer buried in config)
- Null/empty fields omitted
- Result text fields truncated to 300 chars

### Other Fixes

- `deep_merge` clobbering lists: merge by `id` field instead of replace
- Tilde path expansion in file tools: `~` expanded after sandbox check
- Auto-sync clobbering personal config priority overrides
- `scheduler` hub dropping `cron` param on cron task creation
- Missing `asyncio` import in `_add_conversation`
- Role dispatch to unknown `role_id` now escalates to user via `ask_user` instead of silent failure

---

## MCP Tool Description Audit (Fold 1 + Fold 2)

All 14 MCP hub tools audited and updated:
- Every param has a description and type
- Enums declared on action fields
- Defaults documented
- `add_conversation`: new `scope` param (`"role"` | `"framework"`) with clear guidance
- `config`: `api_key` inline param discoverable for resource editing
- `read_file`, `write_file`: corrected false claims, sandbox boundary explicit
- `memory_search`: `max_items` param now visible in schema

Best practices guide: `docs/guides/MCP_TOOL_DESCRIPTION_BEST_PRACTICES.md`

---

## Benchmark System

Full evaluation harness added under `tests/benchmarks/` and `docs/benchmarks/`:

| Benchmark | What it measures |
|-----------|-----------------|
| LOCOMO | Long-context memory retrieval (conversation QA) |
| LongMemEval | Multi-session memory fidelity |
| ABCD e2e | Full dreaming pipeline quality |
| Role memory | Role-scoped knowledge isolation and retrieval accuracy |

First results: `results/locomo_abcd_bc_d1.jsonl`

---

## Architecture Decisions

**Gap 4 (chat→dream bridge) deferred** — ships together with the owner one-on-one interface. The bridge connects chat sessions to the dreaming pipeline; without the one-on-one UI there is nothing to bridge. See `docs/architecture/two_tier_growth_design.md`.

**Think blocks as metadata** — `<think>` content is signal, not noise. Preserved per-iteration for debugging and dreaming enrichment rather than discarded entirely.

**agentic_capable TTL = 7 days** — chosen to be long enough to not trigger unnecessary re-testing, short enough that a recovered model isn't blocked for weeks.

---

## Upgrade Notes

No breaking schema changes. The `agentic_capable` meta file migrates automatically on first load. No manual intervention required.

If you pinned `available_tools` explicitly in task configs, behaviour is unchanged — the override layer still applies. The new capability resolution only changes the default (no `available_tools` specified) path.

---

## What's Next (v1.2.17)

- Owner one-on-one interface + Gap 4 chat→dream bridge
- Validator/ProviderProbe system role for bulk resource pool validation
- Hybrid search (BM25 + embedding) for research roles
- Two-layer catalog: system default + user personal (MCP_DESIGN.md §20)
