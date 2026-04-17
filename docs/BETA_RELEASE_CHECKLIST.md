# MoJoAssistant Beta Release Checklist

> **Rule**: Every feature implementation must be followed by updating this document.
> Add, update, or remove smoke test cases that touch the changed workflow.
> Tests that no longer reflect reality must be removed immediately — stale tests are worse than no tests.

---

## Urgent / Important Before Release

| Priority | Item | Status |
|---|---|---|
| URGENT | Cron tasks never notify user — `created_by: system` fallback silently drops push | Fixed (add `notify_on_completion` to role) |
| URGENT | `add_conversation` crashes with `asyncio not defined` — agents cannot save to knowledge store | Fixed (import added) |
| URGENT | Briefing output written nowhere persistent — output dies in session file | Fixed (write_file added to tools) |
| HIGH | No smoke test coverage for cron→notify path | Pending |
| HIGH | No smoke test coverage for capability tool dispatch (import errors invisible) | Pending |
| HIGH | `memory` category in agent_defaults resolves to zero tools — dead default | Fixed |
| HIGH | Config doctor missing from CI — silent drift goes undetected | Pending |
| MEDIUM | Role overlays had hardcoded tool names — drift when tool names change | Fixed |
| MEDIUM | Coder missing dimensions block — Nine Chapter score unvalidatable | Fixed |
| MEDIUM | Christmas writing pipeline: `alex_writing_profile.md` never written to disk | Fixed |
| MEDIUM | `http_agent`, `get_verge_tech_news`, `curl_request` — test roles/tools polluting catalog | Partially cleaned |
| LOW | Orphaned role dirs from old installs — stale personal configs may need cleanup | Pending cleanup |

---

## Implemented Features

### 1. MCP Server
- HTTP mode (port 8000) + STDIO mode (Claude Desktop)
- OAuth 2.1 with PKCE — client registration, authorization, token issuance, JWT validation
- SSE streaming (`GET /events/tasks`) — real-time task lifecycle events
- HITL reply endpoint (`POST /api/hitl`) — unblocks waiting_for_input tasks
- Dashboard (`/dashboard`)

### 2. Memory System
- **4-tier architecture**: working → active → archival → knowledge
- **Multi-model embeddings**: bge-m3 (1024d), gemma (768d), gemma (256d) in parallel
- **Role-scoped knowledge isolation**: `~/.memory/roles/{role_id}/` — agents cannot cross-read
- **User memory**: global, user-owned, populated by dreaming or explicit save
- **Memory paging**: eviction threshold configurable
- **Dreaming pipeline (A→B→C→D)**: raw session → chunks → synthesized clusters → versioned archive
- **Inbox distillation**: summarize and compress working memory

### 3. Scheduler
- **Persistent task queue**: JSON-backed, atomic writes, survives restart
- **Task types**: `assistant` (agentic LLM), `dreaming`, `custom`, `agent` (coding agent)
- **Cron triggers**: standard 5-field cron, reschedule on completion and failure
- **One-shot scheduled tasks**: `schedule` datetime field
- **Concurrent execution**: semaphore-based (default max_concurrent=3)
- **Task resume**: iteration budget exhaustion → `waiting_for_input` → reply yes/no
- **HITL questions**: any task can pause and ask user a question mid-execution
- **Automatic dreaming**: agentic task completion auto-creates dreaming task
- **Default task seeding**: `scheduler_config.json` seeds recurring tasks on startup (skips existing)
- **Notification routing**: `notify_on_completion` — task config > role default > created_by fallback
- **Zombie detection**: tasks stuck in RUNNING can be force-failed

### 4. Agentic Executor
- **Think-act loop**: iterates until `<FINAL_ANSWER>` or budget exhausted
- **Resource pool**: tier-based LLM selection (free/free_api/paid), round-robin within tier
- **Rate limiting + budget tracking**: per-resource, persisted across restarts
- **Tool use**: capability-resolved tools injected into LLM prompt as schemas
- **Session persistence**: full message history at `~/.memory/task_sessions/{task_id}.json`
- **Iteration budget**: configurable `max_iterations`, resumable after exhaustion
- **Context trimming**: oldest messages evicted when approaching context limit

### 5. Capability System
- **Capability catalog** (`capability_catalog.json`): tool names organized into categories
- **3-layer resolution**: system defaults → role capabilities → runtime override (`available_tools`)
- **Categories**: browser, comms, exec, file, google, knowledge, memory, orchestration, terminal, web
- **knowledge category**: role-private tools (add_conversation, memory_search, task_report_read, task_session_read)
- **memory category**: reserved — user store, not agent-writable directly
- **mcp_external flag**: skips registry check for CLI-installed MCP tools (e.g., google_calendar_*)
- **always_available**: `ask_user` injected for every agent unconditionally
- **Overlay behavioral guidance**: role overlays contain only behavior, never tool names

### 6. Role System
- **Role JSON profiles**: id, archetype, purpose, system_prompt, capabilities, dimensions
- **Nine Chapter scoring**: weighted average of 5 dimensions (core_values 30%, emotional 25%, cognitive 20%, social 15%, adaptability 10%)
- **Role manager**: loads from `~/.memory/roles/{id}.json`, merges system + personal
- **Owner context injection**: `owner_profile.json` slice injected into every agent context
- **Role-private knowledge stores**: `~/.memory/roles/{role_id}/`
- **notify_on_completion**: per-role override for push notification behavior
- **Role overlays**: behavioral injection per task type (scheduler_agentic_task, etc.)

### 7. Policy / Safety
- **Safety policy**: sandboxes file ops to `~/.memory/`, blocks dangerous tool names, danger level enforcement
- **Policy monitor**: behavioral pattern matching on tool calls (content, sensitive domain, data boundary)
- **Event log**: all tool executions logged with timestamp, role, result, block reason
- **Security gate**: pre-execution check before every tool call in agentic loop

### 8. Built-in Capability Tools
- `read_file`, `write_file`, `list_files`, `search_in_files` — sandboxed file ops
- `bash_exec` — sandboxed shell with safe-command whitelist
- `memory_search` — semantic search across role-private knowledge
- `add_conversation` — write dialog exchange to role-private knowledge store
- `web_search` — Google Custom Search API
- `fetch_url`, `curl_request` — HTTP fetch
- `dispatch_subtask` — spawn child agentic task
- `scheduler_add_task` — add task to scheduler queue
- `task_report_read`, `task_session_read` — read own past task output
- `ask_user` — HITL pause for user input

### 9. External MCP Tools (CLI-installed)
- `playwright__browser_*` — 20+ browser automation tools (via browser capability)
- `tmux__*` — terminal session management (via terminal capability)
- `google_calendar_list`, `google_calendar_create` — Google Calendar (via google capability)

### 10. Coding Agent Integration
- **OpenCode manager**: N:1 architecture, multi-project, process lifecycle
- **Claude Code manager**: session state, HITL bridge
- **Agent registry**: unified dispatch for opencode and claude_code backends
- **SSH deploy key management**: per-project ED25519 auto-generation
- **Worktree manager**: git worktree isolation per coding session

### 11. Config System
- **Config doctor**: validates resources, roles (Nine Chapter), tasks, policy, memory, scheduler, capabilities
- **Hot-reload hooks**: config changes trigger live re-initialization
- **3-layer merge**: system config → personal `~/.memory/config/` override
- **Scheduler config seeding**: default_tasks in scheduler_config.json auto-seeded on start

### 12. Notifications
- **ntfy push adapter**: HTTP push to ntfy.sh or self-hosted
- **SSE streaming**: real-time browser/client event stream
- **Event types**: task_started, task_completed, task_failed, task_waiting_for_input, system_notification
- **Filters**: min_severity, notify_user_only, event_types whitelist

---

## High-Level Smoke Test Workflows

> Each test describes a workflow that crosses subsystem boundaries.
> **On every feature change**: run through affected test cases manually or in CI.
> **On every new feature**: add the workflow test case(s) it introduces here.

---

### S-01 · One-shot task dispatches and completes
**Covers**: scheduler queue, agentic executor, session persistence, resource pool

1. Add a task with no schedule (immediate) via `scheduler(action=add)`
2. Verify status transitions: `pending → running → completed`
3. Verify `~/.memory/task_sessions/{task_id}.json` exists with message history
4. Verify `final_answer` is non-empty in the result

---

### S-02 · Cron task fires, completes, reschedules, and notifies
**Covers**: cron trigger, task reschedule, notify_on_completion, ntfy adapter

1. Add a task with `cron_expression` and role that has `notify_on_completion: true`
2. Tick past the scheduled time
3. Verify task dispatched (status → running)
4. Verify on completion: `schedule` advances to next cron window, `started_at` reset to None
5. Verify ntfy receives a push notification for the completion event

**Regression target**: cron tasks with `created_by: system` and no role default silently drop notification.

---

### S-03 · Cron task reschedules after permanent failure
**Covers**: failure path, cron reschedule, last_error preservation

1. Add a cron task whose goal will always fail (bad tool name)
2. Let it exhaust retries → status = FAILED (temporarily)
3. Verify: rescheduled to next cron window, `last_error` preserved, `retry_count` reset to 0
4. Verify: task is PENDING again with updated schedule

---

### S-04 · Task exhausts iteration budget → waiting_for_input → resumes
**Covers**: HITL flow, iteration budget, task resume, pending_question

1. Add a task with `max_iterations: 2` and a goal requiring more work
2. Verify status → `waiting_for_input`, `pending_question` populated
3. Reply `yes` via `reply_to_task`
4. Verify task resumes (status → running again), eventually completes

---

### S-05 · Capability resolution — role capabilities produce correct tool schemas
**Covers**: capability catalog, 3-layer resolution, tool schema injection

1. Load a role with capability `["file", "knowledge"]`
2. Resolve tools via `CapabilityResolver`
3. Verify resolved tool names match catalog entries for those categories
4. Verify `ask_user` is always present (always_available)
5. Verify no tools from `memory` or `browser` category appear (not declared)

---

### S-06 · Runtime override (available_tools) narrows resolved tools
**Covers**: Layer 3 runtime override, capability restriction

1. Role declares `["exec", "file", "web"]` (broad)
2. Task dispatched with `available_tools: ["read_file", "ask_user"]`
3. Verify executor only injects `read_file` and `ask_user` into LLM tool schemas

---

### S-07 · add_conversation writes to role-private store, not shared memory
**Covers**: knowledge isolation, add_conversation, role-scoped store

1. Dispatch task as role `role_a`, call `add_conversation` with test content
2. Verify file written under `~/.memory/roles/role_a/`
3. Verify content is NOT findable via `memory_search` from a different role (`role_b`)
4. Verify content IS findable via `memory_search` from `role_a`

**Regression target**: `asyncio not defined` crash in `_add_conversation`.

---

### S-08 · Safety policy blocks out-of-sandbox file access
**Covers**: safety policy, security gate, event log

1. Dispatch task that calls `read_file` with path `/etc/passwd`
2. Verify tool call is blocked (policy_block event in EventLog)
3. Verify task continues (blocked tool ≠ task failure)
4. Verify event logged with `tool_name`, `pattern_name`, `role_id`

---

### S-09 · Dreaming auto-triggered after agentic task completion
**Covers**: dreaming automation, task lifecycle, session compaction

1. Complete any assistant task successfully
2. Verify a `dreaming` task is automatically added to the queue
3. Verify dreaming task references the completed task's session
4. Let dreaming run → verify `~/.memory/dreams/` updated

---

### S-10 · Nightly dreaming consolidates memory correctly
**Covers**: dreaming pipeline A→B→C→D, versioned archives

1. Add test conversations to memory
2. Trigger dreaming task manually
3. Verify all 4 stages complete (chunks → synthesized → archived)
4. Verify `archive_v<N>.json` created under `~/.memory/dreams/`
5. Verify original conversations marked as processed

---

### S-11 · Role-private knowledge survives scheduler restart
**Covers**: knowledge persistence, queue reload, embedding initialization

1. Dispatch task as `reporter`, call `add_conversation` with unique content
2. Stop and restart the scheduler
3. Dispatch task as `reporter`, call `memory_search` for the unique content
4. Verify content is found after restart

---

### S-12 · Resource pool tier preference selects correct LLM
**Covers**: resource pool, tier-based selection, rate limiting

1. Dispatch task with `tier_preference: ["free"]`
2. Verify resource selected is from the free tier (local model)
3. Dispatch task with `tier_preference: ["paid"]`
4. Verify resource selected is from the paid tier (API model)
5. Exhaust a resource's rate limit → verify fallback to next resource in tier

---

### S-13 · OAuth flow issues and validates token
**Covers**: OAuth 2.1, PKCE, JWT validation, middleware

1. Register a new client
2. Complete authorization code flow (with PKCE challenge)
3. Exchange code for access token
4. Make an authenticated MCP request → verify accepted
5. Use an expired/malformed token → verify 401 rejected

---

### S-14 · Config doctor runs clean on baseline
**Covers**: doctor, capability catalog↔registry sync, Nine Chapter scores, task validation

1. Run `ConfigDoctor().run_all_checks()`
2. Verify zero `error` results in capability category
3. Verify zero `warn` results in nine_chapter category
4. Verify all scheduler tasks reference valid role_ids
5. Verify all cron expressions are parseable

**Regression target**: silent catalog/registry drift, missing dimensions blocks, dead tool names in task configs.

---

### S-15 · Scheduler seeds default tasks on fresh start, skips existing
**Covers**: `_seed_tasks_from_config`, cron first-run calculation, idempotency

1. Delete a seeded task from the queue
2. Restart the scheduler
3. Verify task is re-seeded with `schedule` = next future cron window (not past)
4. Restart again without deleting
5. Verify task is NOT duplicated (existing entry preserved)

---

### S-16 · HITL ask_user pauses task and delivers question to user
**Covers**: ask_user tool, waiting_for_input, pending_question, ntfy

1. Dispatch task whose goal requires user input
2. Task calls `ask_user` with a question
3. Verify status → `waiting_for_input`, `pending_question` set
4. Verify ntfy push fired for `task_waiting_for_input` event
5. Reply via HITL endpoint → task resumes

---

### S-17 · Notify_on_completion respects 3-layer priority
**Covers**: `_should_notify_completion`, task config > role > fallback

1. Task config has `notify_on_completion: false` → no push, regardless of role
2. Task config absent, role has `notify_on_completion: true`, `created_by: system` → push fires
3. Task config absent, role absent, `created_by: user` → push fires
4. Task config absent, role absent, `created_by: system` → no push

---

### S-18 · Multi-model semantic search returns ranked results
**Covers**: multi-model embeddings, hybrid search, knowledge retrieval

1. Write 5 knowledge entries with known content
2. Search with a semantically related (not exact) query
3. Verify correct entries returned in top 3
4. Verify results come from the role-private store (not shared)

---

### S-19 · Dispatch subtask creates child task linked to parent
**Covers**: dispatch_subtask, parent_task_id, concurrent execution

1. Dispatch parent task that calls `dispatch_subtask`
2. Verify child task created with `parent_task_id` set
3. Verify child runs concurrently (parent still running)
4. Verify child completion does not block parent

---

### S-20 · mcp_external tools available via browser/google capability without registry entry
**Covers**: mcp_external flag, external MCP server resolution, capability doctor

1. Verify `google_calendar_list` has `mcp_external: true` in catalog
2. Verify doctor skips registry check for it (no error)
3. Verify role with `google` capability resolves to include it in tool list
4. Verify actual tool call routes to the CLI-installed MCP server

---

## Workflow Test → Feature Matrix

| Smoke Test | Scheduler | Executor | Capability | Role | Memory | Policy | Notify | Dreaming |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| S-01 One-shot dispatch | ✓ | ✓ | | | ✓ | | | |
| S-02 Cron fire + notify | ✓ | ✓ | | ✓ | | | ✓ | |
| S-03 Cron reschedule on fail | ✓ | ✓ | | | | | | |
| S-04 HITL budget/resume | ✓ | ✓ | | | | | ✓ | |
| S-05 Capability resolution | | | ✓ | ✓ | | | | |
| S-06 Runtime override | | ✓ | ✓ | | | | | |
| S-07 add_conversation isolation | | ✓ | ✓ | ✓ | ✓ | | | |
| S-08 Safety policy block | | ✓ | | | | ✓ | | |
| S-09 Dreaming auto-trigger | ✓ | ✓ | | | | | | ✓ |
| S-10 Nightly dreaming pipeline | ✓ | | | | ✓ | | | ✓ |
| S-11 Knowledge survives restart | ✓ | | | | ✓ | | | |
| S-12 Resource pool tier select | | ✓ | | | | | | |
| S-13 OAuth flow | | | | | | | | |
| S-14 Config doctor baseline | | | ✓ | ✓ | | | | |
| S-15 Seed idempotency | ✓ | | | | | | | |
| S-16 ask_user HITL | ✓ | ✓ | ✓ | | | | ✓ | |
| S-17 notify_on_completion layers | ✓ | | | ✓ | | | ✓ | |
| S-18 Multi-model search | | | | | ✓ | | | |
| S-19 Dispatch subtask | ✓ | ✓ | | | | | | |
| S-20 mcp_external tools | | | ✓ | | | | | |
