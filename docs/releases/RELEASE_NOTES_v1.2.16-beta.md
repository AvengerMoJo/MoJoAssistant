# Release Notes — v1.2.16-beta

## Theme: Dynamic Capability Pipeline

The executor no longer relies on clients knowing the right `available_tools` list or
hard-coded system prompts. Role capabilities, tool resolution, and system prompts are
now generated dynamically at dispatch time from three independent, composable layers.

---

## Features

### 3-Layer Capability Resolution (`CapabilityResolver`)

Tool names resolved automatically before every task — no client guesswork required.

**Resolution order:**
1. **System defaults** — `config/capability_defaults.json`: `ask_user` always injected; `memory` + `orchestration` categories for every agent regardless of role.
2. **Role capabilities** — `role.capabilities[]` expanded via `capability_catalog.json` + `CapabilityRegistry`. Category names (`"terminal"`, `"web"`) expand to concrete tool names.
3. **Runtime override** — `available_tools` from task dispatch, with modifier syntax:
   - `"+terminal"` — add terminal tools on top of role defaults
   - `"-web"` — remove web tools for this run
   - Plain list without `+/-` — replaces the role capability layer (system defaults still preserved)

`ask_user` is always re-applied after all overrides — it cannot be removed.

**Before:** Client had to know and list every tool explicitly or the agent ran blind.  
**After:** `scheduler(action='add', type='assistant', role_id='researcher', goal='...')` — works out of the box.

### Role System Prompt Engine (`RoleTemplateEngine`)

Character blocks generated from role definition at dispatch time. No more fragile
static string concatenation in the executor.

**Assembly order:**
1. Identity block — `role.system_prompt` (legacy) or structured generation from `name`, `archetype`, `purpose`
2. Nine Chapter behavioral directives — from `dimensions` scores
3. Task context — `success_patterns` + `escalation_rules`
4. Capability summary — what categories this role can use (never specific tool names)

Growth path: character evolves through ORIENT/REFLECT memory, not prompt re-authoring.

### Pre-Task Capability Gap Check (`CapabilityGapChecker`)

Runs before the agentic loop starts on fresh tasks. Keyword heuristics on the goal text
detect required capabilities and compare against the resolved tool set.

**Gap types:**
- **BLOCKER** — goal explicitly requires a capability the role cannot use (e.g. `"git clone"` with no terminal). Returns `WAITING_FOR_INPUT` before the loop starts — user can add capabilities or proceed anyway.
- **WARNING** — goal may benefit from a capability that isn't present. Logged only; loop proceeds.

No LLM call — fast and cheap keyword matching only.

### Scheduler Cleanup (`action='cleanup'`)

New scheduler action to recover from stuck and failed tasks.

```
scheduler(action='cleanup')                          # default thresholds
scheduler(action='cleanup', zombie_minutes=60)       # stricter zombie detection
scheduler(action='cleanup', failed_days=3, dry_run=true)  # preview only
```

**Zombie detection:** Tasks stuck in `running` status longer than `zombie_minutes` (default: 120)
are force-failed with a descriptive error explaining the cleanup reason.

**Stale failed removal:** Tasks in `failed` status older than `failed_days` (default: 7) are removed.

**`dry_run=true`** reports what would change without modifying anything.

---

## Changes

### Scheduler MCP Description Redesigned

The `scheduler` tool description was rewritten to make client dispatch smooth without
requiring deep knowledge of the capability system.

Key changes:
- Leads with the minimal dispatch pattern — `role_id` + `goal` is all that's required
- `available_tools` clearly marked as **optional** with modifier syntax documented inline
- `type='assistant'` (not `'agentic'`) consistently correct throughout
- `cleanup` action added with its parameters
- Task type table clarified: `assistant` / `custom` / `dreaming` / `agent`

### Client System Prompt Updated (`config/client_system_prompt.md`)

- Replaced old `scheduler_add_task`-style examples with hub pattern
- Corrected `task_type: "agentic"` → `type: 'assistant'`
- `available_tools` documented as optional
- `get_context` at session start (replacing deprecated `get_memory_context`)
- `cleanup` added to the scheduler action reference table

### Config Genericisation

Personal account names removed from all tracked config files. System configs now
ship as clean examples; real accounts belong in `~/.memory/config/` (personal override layer).

**Files updated:**
- `config/llm_config.json` — `avengermojo/elmntri/tinyi/yiai` → `account_a/b/c/d`
- `config/resource_pool.json` — same rename + added `_example_note` comment
- `config/resource_pool_config.json` — moved to `config/examples/resource_pool_config.example.json` (was orphaned — never loaded by runtime)

**Example roles genericised** (`config/roles/`):
- `researcher.json` — removed "Rebecca" persona name throughout
- `network_admin.json` — removed "Ahman" persona name throughout
- `code_reviewer.json` — removed "Carl" persona name throughout
- `developer.json` — removed gendered pronouns (she/her → neutral)

Personal config in `~/.memory/config/` is unaffected and takes precedence at runtime
via `load_layered_json_config` deep-merge.

---

## Infrastructure

### `agentic_executor.py` cleanup

- Removed ad-hoc `_resolve_capabilities()` method (superseded by `CapabilityResolver`)
- Removed static `ninechapter_overlay` / `task_context` / `capability_summary` assembly (superseded by `RoleTemplateEngine`)
- Removed `role_prefix` string variable (superseded by `RoleTemplateEngine.build()`)
- Gap check inserted before resume logic — only runs on fresh starts

### New files

| File | Purpose |
|------|---------|
| `app/scheduler/capability_resolver.py` | 3-layer tool resolution |
| `app/scheduler/role_template_engine.py` | System prompt generation from role character |
| `app/scheduler/capability_gap_checker.py` | Pre-task capability gap detection |
| `config/capability_defaults.json` | System-level always_available + agent_defaults |

---

## Bug Fixes

### Role Chat Memory Isolation (`role_chat.py`)

`memory_search` in role chat sessions was querying the **global** LlamaIndex
`knowledge_manager` — returning results from the user's personal memory instead
of the role's own knowledge.

**Root cause:** `_execute_tool()` fell through to `CapabilityRegistry.execute_tool()`,
which calls `MemoryService._search_knowledge_base_async()` — a method with no
`role_id` parameter that queries the shared vector store.

**Fix:** `memory_search` is now intercepted locally in `_execute_tool()` (same
pattern as `knowledge_search` and `task_search`) and routed through
`_search_knowledge()`, which reads directly from:
- `~/.memory/roles/{role_id}/knowledge_units/` — role-distilled knowledge
- `~/.memory/task_reports/*.json` filtered by `role_id`

User personal conversation history is never accessible from a role chat session.
