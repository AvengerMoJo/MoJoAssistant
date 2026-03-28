# MoJoAssistant Future Roadmap

## Direction

MoJoAssistant is building toward a **local-first privacy proxy** — a trusted
intermediary where a local thinking LLM processes sensitive data before it
touches any external service. Each release adds one layer of that architecture.

```
User / External World
        ↕  (controlled, audited, sanitized)
  MoJoAssistant Gateway
        ↕  (local only, never leaves device)
  Local LLM + Memory + Tools
```

---

## v1.2.0-beta (shipped)
Role safety, HITL, extensible tools, config validation, smoke test.
Foundation layer — the infrastructure exists, guardrails are opt-in.

## v1.2.1-beta (current)
Attention Layer + MCP consolidation + scheduler improvements.
- AttentionClassifier + EventLog hitl_level at every event write
- Wake-up hook in `get_context()` — LLM wakes aware, not blind
- 49 tools → 12 visible (5 top-level + 7 action hubs)
- `get_context` unified read (replaces 4 separate tools)
- Scheduler wake signal (zero-latency task dispatch)
- Config-driven default tasks (`scheduler_config.json`)
- SSE standard event envelope

## v1.2.2-beta (next)
Interactive coding agent integration (OpenCode + Claude Code) + per-source attention routing.

**Coding agent HITL bridge:**
- New MCP tool `external_agent(action="ask_user", task_id, question, options?)` — lets external
  coding agents (OpenCode, Claude Code) inject questions into the HITL inbox directly
- Coding agent task driver in scheduler — spawns agent process, manages task_id lifecycle,
  bridges process I/O to/from the inbox
- Reply delivery — `reply_to_task()` routes answers back to the waiting coding agent
- Any MCP client (ChatMCP, Claude Code, OpenCode) sees waiting questions via `get_context()`
  attention.blocking and can answer with `reply_to_task()`

**Per-source attention routing:**
- Config-driven escalation rules so security failures surface higher than dreaming noise.
  See "Per-Source Routing Rules" below.

## v1.2.3-beta
Resource pool + tool registry catalog architecture.
Agents should be able to use the right resource and discover the right tools
without hardcoding either in role profiles or task configs.

**Resource pool unification:**
- Merge `llm_config.json` + `resource_pool_config.json` → single `resource_pool.json`
- Two layers only: system default + `~/.memory/config/resource_pool.json` (user personal)
- Roles declare `resource_requirements` (tier, context size) — not a specific resource ID
- User adds accounts in personal layer; pool auto-discovers and selects best match

**Tool registry catalog:**
- `config/tool_catalog.json` (system pre-defined) + `~/.memory/config/tool_catalog.json` (user custom)
- Pre-defined: `memory_search`, `web_search`, `bash`, file ops, MCP proxies
- User drops a JSON entry to add custom scripts/tools — no code changes
- Roles declare `tool_access` categories (`["memory", "web", "file", "custom"]`) — not tool names
- `list_tools()` meta-tool always injected — agent discovers full catalog at runtime
- `ask_user` always injected — agent escalates blockers without being told to in the prompt

## v1.2.4-beta — LOCKED SCOPE
**Theme: Trust Layer — Know Exactly What Your Agent Did**

Capability is table stakes. The differentiator is trust. When a user can open
an audit log and see exactly what crossed their local boundary — task by task,
tool by tool — that's a guarantee no cloud-first agent can make by design.
Their architecture requires the data to leave. Ours doesn't.

This release makes MoJoAssistant *auditable*: every external call logged,
every agent behavior enforceable, and every interaction remembered.

**1. §21 enforcement — Role ID required, behavior_rules active**
- `role_id` required at `scheduler_add_task` — inline `system_prompt` rejected
- `behavior_rules.exhausts_tools_before_asking` enforced in `AgenticExecutor`
  (fixes the Rebecca ask_user loop: agent must try all tools before surfacing a question)
- `urgency` + `importance` fields on tasks, matrix drives attention level routing
- `config doctor` validates `nine_chapter_score` derivation from dimensions

**2. Audit trail — Every external boundary crossing logged**
- Every call to a non-local resource (any `tier != "free"`) logged with:
  `task_id`, `role_id`, `resource_id`, `resource_type`, timestamp, token count
  (content never logged — metadata only)
- New MCP tool `audit_get(task_id?)` — shows what external resources a task touched
- Stored in `~/.memory/audit_log.jsonl` (append-only, never purged)
- MCP client shows audit summary in `get_context(type="orientation")`

**3. Inbox → Dreaming distillation — Interactions become institutional knowledge**
- New dreaming pipeline stage runs nightly on the previous day's EventLog
- Pairs `task_waiting_for_input` + `task_completed` events by `task_id`
- Extracts: role, problem, context at time, resolution, outcome
- Produces structured `resolved_interaction` memory units stored in archival memory
- Surfaces automatically via `search_memory()` — agents learn from past resolutions
- Dreaming LLM identifies patterns: "Ahman always needs subnet clarification"
  → becomes a role-level hint injected into future task prompts

**4. Task session compaction — Long sessions become retrievable knowledge**

Problem: Long-running agent tasks (coding agents, research tasks) accumulate raw
session logs of 500K+ characters. Reading them raw is impractical; they are too
large to pass to any LLM context and too unstructured for retrieval.

Design:
- After `task_completed` or `task_failed`, a background compaction job runs on the
  raw session log (`~/.memory/task_sessions/<task_id>.json`)
- Chunking pass: session log split into semantic chunks (by iteration boundary or
  ~2K token windows)
- Local LLM summarization: each chunk condensed to key facts; chunks merged into a
  single structured `task_summary` record:
  ```json
  {
    "type": "task_summary",
    "task_id": "popo_kingsum_admin_flutter_plan_001",
    "role": "popo",
    "goal": "...",
    "approach_summary": "...",
    "key_decisions": [...],
    "artifacts_created": ["KingSum2E/docs/FLUTTER_ADMIN_APP.md"],
    "outcome": "completed",
    "error": null,
    "iterations": 3,
    "compacted_at": "2026-03-22T..."
  }
  ```
- Stored in archival memory — surfaces via `search_memory()`
- `get_context(type="task_session")` returns the compacted summary by default;
  `full=true` returns the raw session log for debugging
- Raw session log kept on disk permanently (audit trail), never purged

**Files:** New `app/dreaming/session_compactor.py`,
`app/scheduler/core.py` (trigger compaction on task completion),
`app/mcp/core/tools.py` (`task_session` read — summary vs full mode)

## v1.2.5-beta
PII classification + sanitization layer. Pattern-based scanner flags
sensitive data before it crosses a boundary. Configurable per role:
redact, abstract, or summarise before external exposure.

## v1.2.6-beta
Policy enforcement + agentic executor hardening.

**What was originally planned vs what was built:**

The original spec called for a separate `PolicyAgent` process subscribing to
the inbox event stream and blocking operations pre-execution. After design
review, an inline `PolicyMonitor` checker pipeline was chosen instead. The
architectural reasons: synchronous inline checks have zero message-passing
latency, no separate process to crash/stall, and are composable without an
event-stream dependency. The inbox-based PolicyAgent is a valid future
enhancement but is not a prerequisite for safety — inline checkers cover
all the same blocking/auditing outcomes.

**What was actually shipped:**
- `app/scheduler/policy/` package: `StaticPolicyChecker`, `ContentAwarePolicyChecker`,
  `DataBoundaryChecker`, `ContextAwarePolicyChecker` — pluggable ordered pipeline
- Role-level `data_boundary` config: `allow_external_mcp`, `allowed_tiers`
- `_emit_policy_violation` in executor → EventLog → ntfy + dashboard on every block
- Per-task tmux socket isolation (`/tmp/mojo-task-{id}.sock`)
- MCPClientManager race-condition fixes (connect lock, stale flag reset, wait_for timeout)
- Bidirectional ntfy HITL reply flow

**Gaps that remain open (deferred to v1.2.7 or later):**
- ✅ `"local_only": true` task/role flag — shipped in v1.2.6; syntactic sugar over
  `data_boundary: {allow_external_mcp: false, allowed_tiers: ["free"]}`.
  Explicit `data_boundary` values take precedence over `local_only` defaults.
- ✅ Automated tests for all policy checkers — 32 unit tests in
  `tests/unit/test_policy_checkers.py` cover `StaticPolicyChecker`,
  `ContentAwarePolicyChecker`, `DataBoundaryChecker`, `ContextAwarePolicyChecker`,
  `PolicyMonitor` pipeline, and `local_only` shorthand.
- Inbox-subscribing `PolicyAgent` (separate process) — still valuable for
  cross-agent policy enforcement and audit reasoning; target v1.3.x.

**Infrastructure routing — superseded (2026-03-24):**
The original goal ("high-priority events reach user when no MCP client is open")
is now fully covered by three independent channels: ntfy push (phone/desktop,
works without any client), the read-only dashboard (browser), and MCP
`get_content` polling. A dedicated file/terminal adapter adds nothing a user
would reach for. Bidirectional ntfy (reply from notification) is tracked as a
good-to-have in v1.3.x if urgency demands it.

**Technical debt from v1.2.5 (Carl review):**
- ✅ Race condition in MCPClientManager eager connection — fixed (connect lock, stale flag reset, wait_for timeout)
- ✅ Missing input validation for urgency/importance routing fields — bounds/type checking added
- ✅ Duplicated `["free", "free_api"]` default tier preference — extracted to `DEFAULT_TIER_PREFERENCE` constant
- ✅ Per-task tmux session isolation — unique `/tmp/mojo-task-{id}.sock` per task
- ✅ Overly broad `except Exception` in ResourcePoolLLMInterface — removed; transport errors caught by name, unexpected errors propagate naturally
- ✅ Non-atomic stop/reconnect in MCPServerManager — fixed in v1.2.7; rollback retry on failed
  reconnect; honest `"partial"` status when sibling server can't be recovered.

## v1.2.7 ✅ shipped 2026-03-27/28
Tech debt + Security Sentinel foundation + Role Chat Interface.

- ✅ **MCPServerManager rollback** — `stop_project()` closes all sessions atomically (AsyncExitStack
  limitation), reconnects siblings, retries each failed reconnect once, returns `"partial"` status
  with `failed` list rather than lying with `"success"`. `restart_project()` surfaces rollback
  warnings and `failed_siblings` from stop phase.
- ✅ **Security Sentinel role** — `~/.memory/roles/security_sentinel.json`; nightly cross-session
  behavioral analysis using EventLog; `local_only: true`, no external calls; outputs structured
  security digest to memory at key `security/digest_YYYY-MM-DD`. Scheduled nightly 03:00 via
  `config/scheduler_config.json` (`security_sentinel_nightly` task).
- ✅ **`behavioral_patterns.json`** — 23 behavioral security patterns in four categories:
  credential file access (ssh, .aws, .gnupg, .netrc, kubeconfig), C2/reverse-shell (/dev/tcp,
  netcat -e, python/perl socket shells, mkfifo, socat EXEC), exfiltration (base64 large payload,
  curl/wget POST to external, scp/rsync outbound), privilege escalation (SUID chmod, crontab -ei,
  LD_PRELOAD injection). `ContentAwarePolicyChecker._load_patterns()` merges policy + behavioral
  layers (system + personal overlay each); total 32 patterns at startup.
- ✅ **Atomic fact extraction (document dreaming path)** — `process_document()` pipeline converts
  research reports into `KnowledgeUnit` records (atomic propositions + source quotes + inter-unit
  links). Auto-triggered after agent task if `final_answer ≥ 500 chars`. KUs stored in
  `~/.memory/roles/{role_id}/knowledge_units/`. See `docs/architecture/ROLE_CHAT_INTERFACE.md`.
- ✅ **Role Chat Interface** — `dialog(role_id, message, session_id?)` MCP tool; talk directly
  to any assistant in conversational mode (not agentic executor). Role's personality + private
  KU memory + recent task activity as context. Mini agentic loop (max 5 iterations) with
  `memory_search` and `task_search` tools. Session history persisted at
  `~/.memory/roles/{role_id}/chat_history/{session_id}.json`. Dashboard "Chat" tab with session
  sidebar, "+ New Chat" button, and bubble-style history. Uses LMStudio local server with
  dynamic model discovery (`/v1/models` probe when `model=None`); falls back to FREE_API tier.
  Design doc: `docs/architecture/ROLE_CHAT_INTERFACE.md`

---

## v1.3.0 — Behavioral Security Layer

**Theme: Trusted-but-Compromised — Catching What Policy Rules Miss**

Inline policy checkers (v1.2.6) protect against known bad. This release adds a
parallel behavioral layer that catches agents behaving outside their declared scope
— the Trivy attack class, and the dominant AI supply chain attack surface going
forward.

Design doc: `docs/architecture/SECURITY_BEHAVIORAL_MONITOR.md`

### Layer 2: BehavioralMonitor (parallel, silent observer)

Runs alongside every `AgenticExecutor` session without blocking or modifying
execution. The agent has no awareness of it.

- Maintains per-role behavioral baseline (typical tools, call counts, credential
  access rate, external network rate) updated via exponential moving average
- Scores each tool call against baseline: credential path access, scope drift,
  exfiltration chains, volume anomalies, timing anomalies, C2 pattern matches
- Accumulates session-level suspicion score, signals ContainmentEngine at thresholds

### Layer 3: ContainmentEngine (three-tier response)

| Suspicion | Response | Agent Awareness |
|-----------|----------|-----------------|
| LOW (30–60) | Silent ntfy push to user, session flagged | None |
| MEDIUM (60–85) | Redirect to **SandboxRuntime** — honeypot containment | None |
| HIGH (85+) | Hard halt + HITL level 5 alert | Yes — task stops |

### SandboxRuntime (honeypot)

When MEDIUM threshold is crossed, `AgenticExecutor` transparently swaps its
execution backend. The agent continues running and receives plausible responses —
but nothing touches real resources:

- `bash_exec` → isolated container (Docker/bubblewrap), ephemeral filesystem, monitored network
- File writes → fake filesystem overlay at `/tmp/mojo-sandbox-{task_id}/`
- Network calls → transparent monitoring proxy, calls logged + optionally blocked
- MCP writes → silently no-op with plausible success responses

While sandboxed, the ContainmentEngine records the full attack sequence: credential
paths targeted, network destinations, data assembled, encryption attempted. Written
to `~/.memory/security/containment_{task_id}.json` — forensic intelligence for
future pattern updates.

**Why honeypot over immediate block:** Blocking reveals detection. Silent containment
lets the attack complete in a controlled environment, gives full forensic visibility,
and allows the user to decide on response with complete information.

### Security Sentinel role (nightly cross-session analysis)

Scheduled role running after dreaming (04:00). Reads EventLogs and behavioral
profiles. Catches what per-session scoring misses: slow baseline drift over weeks,
patterns innocuous individually but suspicious collectively, emerging attack
signatures. Outputs security digest to EventLog. Local-only, no external calls,
no bash — cannot be compromised by supply chain attack on external dependencies.

### New files
- `app/scheduler/security/behavioral_monitor.py`
- `app/scheduler/security/containment_engine.py`
- `app/scheduler/security/sandbox_runtime.py`
- `app/scheduler/security/forensics.py`
- `config/behavioral_patterns.json`

---

## v1.3.1 — Agent Learning Loop

**Theme: Agents That Learn From Their Own Mistakes**

Design doc: `docs/architecture/AGENT_LEARNING_LOOP.md`

The current model requires a human to be the learning loop: agent fails → human
notices → human fixes code or config → agent tries again. This release closes
that loop so common failure patterns are resolved by the agents themselves.
Human attention is reserved for genuinely new problems.

### Per-agent silo memory

Each role gets a private memory store at `~/.memory/roles/{role_id}/`:
- `task_history/` — structured failure/success records written by executor after every task
- `lessons/` — synthesized lesson knowledge units produced by the role's dream pass
- `capabilities/` — what this role knows it can and cannot do

### Failure → lesson pipeline

On task incomplete or failed, `AgenticExecutor` writes a structured `task_lesson`
record: what was tried, what failed, root cause, what would unblock, suggested
alternatives. Failure taxonomy tags each record (missing resource, wrong tool for
platform, missing permission, ambiguous goal, external unavailability, knowledge gap).

The role's nightly dream pass reads `task_history/`, synthesizes durable
`agent_lesson` units into `lessons/`. Lessons have confidence scores that
strengthen with repeated reinforcement.

### Memory context injection at task start

Before the first iteration, the executor queries the role's lesson memory for
entries relevant to the current task goal. Relevant lessons are prepended to
context as "Memory notes" — the agent already knows what failed last time and
tries the alternative approach without being told.

### Cross-agent memory reference

Any agent can query another agent's lesson memory:
```
search_memory(query="git clone codebase access", role_id="ahman")
```
Agents discover what other agents know without hardcoding role capabilities.
Write access to a role's private memory is restricted to that role and the system.

### Sub-agent dispatch (foundational piece)

`scheduler_add_task` becomes available as a tool for assistant roles — not just
humans via MCP. An agent that hits a wall it can't solve alone can dispatch a
sub-task to the right role and wait for the result:
- Rebecca needs codebase access → dispatches to Ahman → Ahman clones → Rebecca reads report
- Sub-tasks inherit parent data_boundary policy
- Sub-task depth limited to 2 levels (prevent runaway recursion)
- All dispatched sub-tasks visible in EventLog with parent linkage

### Priority matrix update

| Item | Urgent | Important |
|------|--------|-----------|
| Failure → task_lesson write (executor) | 🟡 | 🔴 |
| Memory context injection at task start | 🟡 | 🔴 |
| Per-role dream pass on private memory | 🟡 | 🔴 |
| Cross-agent search_memory(role_id) | 🟢 | 🔴 |
| scheduler_add_task as agent tool | 🟢 | 🔴 |
| list_agent_capabilities() discovery tool | 🟢 | 🟡 |

---

## v1.3.2
**Agent Type Classification + Pluggable Workflow Templates** (§25)
- `agent_type` field in role JSON (provisioner, researcher, reviewer, executor, monitor, orchestrator)
- `scheduler_add_task` as a dispatchable agent tool — agents queue each other's work without human relay
- Workflow templates in `config/workflow_templates/{type}.json` (two-layer: system + user override)
- Template auto-injected into system prompt at task start
- `schedule_consumer` handoff: provisioner completion auto-queues the consumer agent
- User-defined custom agent types via `~/.memory/config/agent_types.json`

**Role Chat — Full Version** (§24, builds on v1.2.7 foundation)
- OpenAI-compatible proxy API (`/v1/models`, `/v1/chat/completions`) — any LLM client (OpenWebUI, Cursor) talks to any role directly
- Explicit memory capture ("remember: X") writes to role private lesson store from chat
- Post-dialog NineChapter dimension refinement via dream pipeline — personality evolves from extended conversations
- Cross-role referral — "Ahman would know more about this" hands off chat context to another role

## v1.2.5-beta
Terminal tools + HttpAgentExecutor + config cleanup — complete the computer-use
story and close the remaining trust-layer gaps.

- **Terminal tools** — `terminal_exec`, `terminal_read` via persistent tmux sessions.
  Agents can run commands, see live output, maintain shell state across iterations.
- **HttpAgentExecutor** — drive ZeroClaw and other HTTP agents via MAP protocol (§17/§18).
  Design is complete; code is ~300 lines. One config entry per agent in the fleet.
- **Hybrid memory search** — BM25 + embedding for research roles. Rebecca finds
  structural/domain connections that pure semantic similarity misses.
- **Urgency + importance → attention routing** — task fields drive attention level
  via urgency×importance matrix (deferred from v1.2.4).
- **Config doctor NineChapter score validation** — validate `nine_chapter_score`
  derivation from five dimensions (deferred from v1.2.4).
- **Config tool coverage for `mcp_servers.json`** — add/remove external MCP servers
  via the `config` MCP tool (currently requires manual file edit).
- **`llm_config.json` → `resource_pool.json` migration** — make `executor.py`
  dreaming pipeline pull LLM from `ResourceManager`; update installer to write
  `resource_pool.json`. Eliminates split-brain config risk.

## Priority Matrix — Urgent / Important

_Last updated: 2026-03-28 (wip_1.2.8)_

| Item | Urgent | Important | Target | Status | Why |
|------|--------|-----------|--------|--------|-----|
| Audit trail + §21 enforcement | 🔴 High | 🔴 High | v1.2.4 | ✅ Done | `audit_log.jsonl` append-only, `audit_get` MCP tool, §21 `role_id` required + inline `system_prompt` rejected in `scheduler_add_task` |
| Tool-calling reliability (Qwen/LMStudio) | 🔴 High | 🔴 High | v2.0.0 gate | ✅ Done v1.2.8 | Malformed JSON args → error feedback to model; consecutive no-tool drift forcing; role chat tool-loop budget |
| MCPServerManager rollback | 🟡 Medium | 🟡 Medium | v1.2.7 | ✅ Done | Stop/restart hardened; partial status on sibling failure |
| Security Sentinel role + behavioral_patterns.json | 🟡 Medium | 🔴 High | v1.2.7 | ✅ Done | 23 behavioral patterns (4 categories); sentinel role scheduled nightly |
| Atomic fact extraction (KnowledgeUnit pipeline) | 🟡 Medium | 🟡 Medium | v1.2.7 | ✅ Done | Document dreaming path; KUs stored per role |
| Role Chat Interface (dialog tool + dashboard) | 🔴 High | 🔴 High | v1.2.7 | ✅ Done | `dialog` tool; session persistence; dashboard Chat tab |
| Sub-agent dispatch (`dispatch_subtask`) | 🟢 Low | 🔴 High | v1.2.7 | ✅ Done | Depth-limited (max 3); graceful loop prevention |
| HITL iteration budget exhaustion | 🟡 Medium | 🔴 High | v1.2.7 | ✅ Done | Budget exhaustion → HITL question instead of hard fail |
| MEMORY_PATH consistency | 🟡 Medium | 🔴 High | v1.2.7 | ✅ Done | `JsonFileBackend` all call sites pass `storage_path`; doctor verifies |
| ConfigDoctor v1.2.6/v1.2.7 checks | 🟡 Medium | 🟡 Medium | v1.2.8 | ✅ Done | Policy patterns, MEMORY_PATH writability, scheduler config, `local_only` resource check |
| Urgency + importance → attention routing | 🟡 Medium | 🔴 High | v1.2.4 | ✅ Done | Fields on task model; drive `hitl_level` floor via urgency×importance |
| Dependency resilience (optional imports) | 🔴 High | 🔴 High | v2.0.0 gate | 🟡 Partial | `sentence_transformers` soft-import fixed; `prompt_toolkit` skipped in CI; full audit of optional deps needed |
| Smoke suite — one command, clean install | 🔴 High | 🔴 High | v2.0.0 gate | ❌ Open | `tests/smoke/` directory does not exist; blocks public release |
| First-run experience / installer (Gate 7) | 🟡 Medium | 🔴 High | v2.0.0 gate | 🟡 Partial | `app/interactive-cli.py` exists; needs wizard polish, demo roles (Alex/Rebecca/Ahman/Carl), 5 demo tasks, privacy report view |
| Release definition — documented supported path | 🟡 Medium | 🔴 High | v2.0.0 gate | 🟡 Partial | README rewritten v1.2.7; INSTALL.md with supported OS/Python/model/env-var table still needed |
| ConfigDoctor NineChapter score validation | 🟢 Low | 🟡 Medium | v1.2.4 | ❌ Open | Validate `nine_chapter_score` matches dimension average; deferred from v1.2.4 |
| Hybrid memory search (BM25 + embedding) | 🟢 Low | 🔴 High | v1.2.5 | ❌ Open | Semantic-only search misses structural/domain connections for research roles |
| BehavioralMonitor + ContainmentEngine | 🟢 Low | 🔴 High | v1.3.0 | ❌ Open | Critical for autonomous AI world; not urgent until pre-public |
| Agent learning loop (failure→lesson→injection) | 🟢 Low | 🔴 High | v1.3.1 | ❌ Open | Agents learn from mistakes without human intervention |
| Per-agent silo memory + cross-agent queries | 🟢 Low | 🔴 High | v1.3.1 | ❌ Open | Each agent accumulates its own knowledge; agents can reference each other |
| PII classification + sanitization | 🟢 Low | 🟡 Medium | post-v2.0.0 | ❌ Open | Defense-in-depth; data boundary enforcement covers core promise |
| HttpAgentExecutor / external agent integrations | 🟢 Low | 🟡 Medium | post-v2.0.0 | ❌ Open | Compelling, not foundational |
| Agent type classification + workflow templates | 🟢 Low | 🟡 Medium | v1.3.1 | ❌ Open | Feature expansion, not safety-critical |
| One-on-one role channel + OpenAI-compat proxy | 🟢 Low | 🟡 Medium | v1.3.1 | ❌ Open | UX polish, post-v2.0.0 |
| Inbox → Dreaming → Knowledge | 🟢 Low | 🟡 Medium | v1.3.x | ❌ Open | Institutional memory; valuable but not blocking |
| Message passing + containerization | 🟢 Low | 🟢 Low | v2.x | ❌ Open | Architecture evolution, long horizon |

**Reading the matrix:**
- 🔴🔴 = do next, blocks v2.0.0 or is the linchpin
- 🟡🔴 = important, schedule soon after linchpin items
- 🟢🔴 = high value but not time-pressured; design now, build at right milestone
- anything 🟢🟢 = genuine backlog

**v2.0.0 gate remaining work (3 items):**
1. **Smoke suite** — `tests/smoke/` with scheduler + memory + policy + one agent loop; no API keys required
2. **First-run / installer** — wizard polish + 4 bundled demo roles + 5 demo tasks + privacy report view
3. **INSTALL.md** — supported OS/Python/model, required vs optional env vars, stable vs experimental surface table

---

## v1.2.x → v1.3.0 graduation
v1.3.0 releases when:
1. **Trust layer is real** (v1.2.4): audit trail, §21 enforcement, inbox distillation
2. **Computer-use is complete** (v1.2.5): browser + terminal + external agents
3. **Safety foundation holds** (v1.2.6): PII classification, data boundary enforcement

The graduation promise: a user can run MoJoAssistant with agents touching real
data, point to the audit log, and say "here is exactly what left my device and
when — and here is proof nothing else did."

---

## v2.0.0 Public Release — dropping beta

This is a separate gate from v1.3.0 graduation. v1.3.0 is a feature milestone;
v2.0.0 is a quality and trust milestone. Beta comes off when a stranger can install
MoJoAssistant on a clean machine, run one command, and get a working system with
a clear, honest picture of what it does and doesn't do.

### Non-negotiable before publish

**1. Audit trail + §21 enforcement (v1.2.4 core)**
The privacy claim — "here is exactly what left your device" — is unverifiable
without the append-only audit log and `audit_get(task_id)`. Until §21 enforcement
makes `role_id` mandatory at `scheduler_add_task` and rejects inline
`system_prompt`, the entire policy layer can be bypassed by omission. These two
items are the linchpin. Everything else is polish on top of a promise that isn't
yet provable.

**2. Tool-calling reliability on the supported path**
The Qwen/LMStudio execution path is currently too unreliable to present as
dependable agent execution. Before publish, one model+provider combination must
be designated the supported path and must pass the smoke suite consistently.
Everything else is explicitly experimental.

**3. Dependency resilience**
Integration tests must not fail because an optional package (e.g.
`sentence_transformers`) is absent — unless that absence is explicitly documented
as unsupported and the test is marked accordingly. Failing CI on a clean install
due to an undeclared optional dependency is a broken install story, not a test
gap.

**4. Release definition — one documented supported path**
One document (README or INSTALL.md) that specifies:
- Supported OS + Python version
- Required env vars (`.env.example` is necessary but not sufficient — document
  which vars are actually required vs optional and what breaks without them)
- Required models: which provider, which model, what context size
- What works out of the box vs what requires additional configuration
- What is explicitly marked experimental

**5. Smoke suite — one command, clean machine**
A single command (e.g. `make smoke` or `pytest tests/smoke/`) that:
- Passes on a clean install with only required dependencies
- Exercises: scheduler tick, memory read/write, MCP tool surface, policy check,
  and at least one end-to-end agent loop (task queued → executed → result logged)
- Produces a clear PASS/FAIL with no ambiguous skips
- Does not require external API keys (uses local/free tier only)

**6. Scope cut — stable surface vs experimental**
At publish time, explicitly label:
- **Stable**: scheduler, HITL inbox, policy checker pipeline, memory search,
  MCP tool surface, data boundary enforcement, ntfy push, role system
- **Experimental**: Qwen/LMStudio agent execution, HttpAgentExecutor,
  coding agent integration, ZeroClaw/OpenClaw integration, PII classification
Users should know what they're getting, not discover the edges themselves.

**7. Onboarding experience — installation assistant + demo suite**
A first-time user must be able to understand every key concept of MoJoAssistant
through the system itself, not only through documentation. This requires three
components working together:

*Installation assistant (setup wizard)*
- Guided first-run flow: API key entry, LLM endpoint detection, memory path
  confirmation, ntfy push opt-in
- Validates each step before proceeding — no silent misconfiguration
- Produces a working `.env` and confirms the server starts cleanly
- Already partially built (`app/interactive-cli.py`); needs polish and a
  non-interactive path for Docker/CI

*Default bundled roles (demo personas)*
Each role demonstrates a distinct capability and a distinct safety posture:
- **Alex** — personal memory assistant; `local_only: false`; shows basic
  memory search + conversation logging
- **Rebecca** — research analyst; `tier_preference: free_api`; shows
  web search, sub-task dispatch, dreaming consolidation
- **Ahman** — security auditor; `local_only: true`; shows `data_boundary`
  enforcement, policy violation events, Security Sentinel integration
- **Carl** — code reviewer; `local_only: true`; shows role chat interface,
  knowledge repo indexing, `read_file` / `list_files` tool access

*Demo task scripts*
A set of pre-built scheduler tasks that a new user can run on day one to
observe the system end-to-end:
- `demo_memory_roundtrip` — store a conversation, search it back, verify
  retrieval; confirms memory pipeline is wired
- `demo_policy_block` — a task that deliberately attempts a blocked tool call;
  demonstrates policy_violation event, HITL notification, and audit trail
- `demo_research_loop` — Rebecca researches a local topic, dispatches a
  summarisation sub-task, writes the result to memory; demonstrates multi-hop
  agent execution
- `demo_security_sentinel` — trigger a one-off Security Sentinel run; shows
  the nightly digest in the dashboard
- `demo_dreaming` — feed a sample conversation through the dreaming pipeline;
  shows A→B→C→D consolidation and the resulting archive in `dream(list)`

*Self-protection walkthrough*
The dashboard must include a "How MoJoAssistant protects you" tab (or a
`config(action="privacy_report")` MCP tool) that shows, for any task:
- which LLM resources were used and their tier
- what tools were called and whether any were blocked by policy
- the full audit trail (`audit_get(task_id)`)
- which data left the device and which stayed local

This is the privacy promise made verifiable — not as a document, but as a
live view the user can inspect at any time.

*Extensibility guide*
A single `docs/guides/EXTENDING.md` that explains:
- how to create a new role (copy + edit JSON, no code)
- how to add a custom behavioral pattern to `~/.memory/config/behavioral_patterns.json`
- how to register a personal MCP server overlay
- how to write a custom tool for the scheduler tool registry

The bar: a non-developer can personalise MoJoAssistant within 30 minutes of
first install without reading source code.


**8. Test health**
No known test failures in CI on the supported path. Tests that exercise
unsupported/optional paths must be marked `@pytest.mark.optional` or similar
and skipped by default. The 15 currently pre-existing failures must be resolved
or explicitly skipped with a documented reason before publish.

### What can ship post-v2.0.0

- PII classification (v1.2.5) — defense-in-depth; data boundary enforcement
  already covers the core privacy promise
- HttpAgentExecutor / external agent integrations — compelling, not foundational
- Inbox distillation / task session compaction — polish
- Message passing / containerization — v2.x

### The publish bar in two sentences

A non-developer can install MoJoAssistant, run the bundled demo suite, and
understand every key concept — memory, roles, policy, dreaming, HITL — through
the system itself, not through documentation.

A technical user can then read the release definition, inspect the privacy
report for any task, and trust that what it says it does, it actually does —
and that what it doesn't mention, it doesn't quietly attempt.

---

## Future Releases

### Data Boundary Enforcement

**Problem:** Nothing prevents data from a "local only" task from flowing into
an external LLM call in a subsequent step. Policy blocks tools, not data flows.

**Design:**
- `"local_only": true` flag on tasks and roles
- Executor refuses to route any data from a `local_only` session to a resource
  with `type != "local"` or `tier != "free"`
- Violation → task fails with clear error, not silent data leak

**Files:** `agentic_executor.py`, `models.py`, `role_manager.py`

---

### Audit Trail — Data Boundary Crossings

**Problem:** No way to answer "did any of this conversation touch an external API?"

**Design:**
- Every resource call logged with: task_id, resource_id, resource_type (local/api),
  timestamp, token count (no content)
- New MCP tool `audit_get_crossings(task_id)` — shows exactly which external
  resources a task touched and when
- Stored in `~/.memory/audit_log.json` (separate from event log, never purged)

**Files:** `agentic_executor.py`, new `app/mcp/adapters/audit_log.py`, `tools.py`

---

### PII / Data Classification Layer

**Problem:** The system has no concept of sensitive data. A local LLM might
extract PII and pass it to an external tool without any warning.

**Design:**
- `DataClassifier` — lightweight pattern-based scanner (regex + local model)
  that runs on tool inputs/outputs and flags: PII, credentials, financial data,
  health data
- Classification result attached to the session context
- If classified data is about to cross a boundary → warn or block depending
  on role policy (`"block_pii_external": true`)
- Not a replacement for careful design — a safety net

**Files:** New `app/security/data_classifier.py`, `agentic_executor.py`

---

### Sanitization Layer

**Problem:** Before a locally-processed result goes to an external service,
nothing strips or abstracts the sensitive parts.

**Design:**
- `DataSanitizer` — transforms data before it crosses the local boundary
- Strategies: redact (replace PII with `[REDACTED]`), abstract (replace specific
  values with category labels), summarise (local LLM rewrites without specifics)
- Configured per role: `"external_sanitization": "redact"` or `"abstract"`
- Applied automatically when a local result is passed to an external resource

**Files:** New `app/security/sanitizer.py`, `agentic_executor.py`, `role_manager.py`

---

### Per-Source Routing Rules (Attention Layer extension)

**Problem:** All opencode results land at the same attention level. All failures
look the same. Source-aware routing would let security failures escalate higher
than dreaming failures.

**Design:** Extend `AttentionClassifier` with a config-driven rule layer:
```json
{
  "attention_rules": [
    {"source": "ahman", "event_type": "task_failed", "hitl_level": 4},
    {"source": "opencode", "event_type": "task_completed", "hitl_level": 1},
    {"severity": "error", "source_tag": "security", "hitl_level": 5}
  ]
}
```
Rules evaluated before defaults. Configurable via `config` MCP tool.

**Files:** `attention_classifier.py`, `config/attention_config.json`

---

### Infrastructure Routing (Long-term)

**Problem:** High-priority events (level 4–5) should reach the user even when
no MCP client is open — not just via ntfy push.

**Design:**
- Level 3–4 → existing ntfy push (already works)
- Level 5 → terminal bell / system notification in active SSH session
- Level 0–2 → daily digest written to `~/.memory/digest/YYYY-MM-DD.md`
- Digest MCP tool: `get_daily_digest(date)` — human-readable summary of the day

**Files:** New `app/mcp/adapters/push/terminal.py`, new digest writer in scheduler

---

---

### Policy Enforcement Agent

**Problem:** `denied_tools` and `allowed_tools` are static setup-time rules.
They can't understand context — they block or allow regardless of what data
is actually flowing or what the operation will do.

**Design:**
- A `PolicyAgent` role that subscribes to the inbox event stream
- Receives events *before* operations complete — not just logs them after
- Classifies events using DataClassifier (PII, credentials, boundary crossings)
- Decisions: ALLOW (record + proceed), BLOCK (cancel + escalate to hitl_level 5)
- Every decision written to the audit log with reasoning
- Configurable per role: `"policy_agent": "strict"` or `"permissive"`
- Works in concert with the Sanitization Layer — PolicyAgent can trigger
  sanitization instead of outright blocking when data can be cleaned

**Why the inbox enables this:**
All inter-agent communication, external calls, and HITL questions flow through
the event stream. The inbox is the natural interception point — the PolicyAgent
reads events before they are acted on, not after.

**Files:** New `app/scheduler/policy_agent.py`, `app/mcp/adapters/event_log.py`
(pre-execution hooks), `app/config/doctor.py` (validate policy_agent config)

---

### Message Passing + Containerized Components

**Problem:** All components (MCP server, scheduler, agents) live in one Python
process, communicating via in-process method calls. This means one component
crashing affects all others, scaling requires forking the entire process, and
agents must be written in Python.

**Design:**
- Replace in-process method calls with explicit message passing through
  the existing `EventLog` + SSE bus
- Define a typed message envelope: `source`, `destination`, `message_type`,
  `payload`, `reply_to` — same schema as today's events, made explicit
- Each component (MCP server, scheduler, each agent role) becomes an
  independent process/container that sends and receives typed messages
- `reply_to_task` already defines the reply message schema — it works
  identically over a network bus
- Migration path: gradual. In-process calls remain as fallback;
  message bus becomes primary; containers become optional at any step

**Near-term (no containers required):**
- Multi-process: scheduler as a separate daemon (already partially true)
- Agent isolation: each role's task runs in a subprocess with message-only I/O
- Language-agnostic: a Rust or Go component can join the bus

**Long-term:**
- Full containerization: Docker/OCI containers per component
- The message bus (EventLog → Redis/NATS) is the only shared surface
- Policy Agent as a sidecar container inspecting all messages

**Files:** `app/mcp/adapters/event_log.py` (message bus extension),
new `app/messaging/` module, `app/scheduler/core.py` (subprocess boundary)

---

### Inbox → Dreaming → Institutional Knowledge

**Problem:** When an assistant and a 3rd-party agent resolve a problem via
the HITL inbox (question → context → answer → task completed), that entire
interaction is structured knowledge. Today it dissolves into raw conversation
text and loses its typed structure before dreaming can see it.

**Design:**
- New dreaming pipeline stage: **Inbox Distillation**
- Runs after nightly dreaming on the previous day's EventLog slice
- Pairs `task_waiting_for_input` + `task_completed` events by `task_id`
- Extracts: role, problem stated, context at the time, resolution provided,
  outcome (success/failure), iteration count
- Produces a structured "resolved interaction" knowledge unit:

```json
{
  "type": "resolved_interaction",
  "role": "ahman",
  "problem": "which subnet should I scan?",
  "context_summary": "weekly security review, home network setup",
  "resolution": "scan 10.0.0.0/24",
  "outcome": "completed — found 3 open ports, no critical issues",
  "resolved_by": "user_reply",
  "task_id": "ahman_scan_001",
  "refined_at": "2026-03-20T03:00:00"
}
```

- Stored in archival memory — surfaces automatically via `search_memory()`
- Over time: the assistant builds institutional knowledge about how problems
  are resolved, by whom, and with what outcome
- The dreaming LLM can also identify *patterns* across interactions:
  "Ahman always needs subnet clarification on home network tasks"
  → becomes a role-level hint injected into future Ahman task prompts

**Files:** New `app/dreaming/inbox_distillation.py`,
`app/dreaming/pipeline.py` (add optional inbox stage),
`app/mcp/adapters/event_log.py` (expose filtered slice for dreaming)

---

## Summary Table

| Feature | Protects / Enables | Scope |
|---------|---------|-------|
| Coding agent HITL bridge (OpenCode, Claude Code) | Interactive external agents | v1.2.2 |
| Per-source routing rules | Attention quality | v1.2.2 |
| Resource pool unification (two-layer catalog) | Agents find the right resource automatically | v1.2.3 |
| Tool registry catalog + list_tools() discovery | Agents discover tools at runtime, users add custom tools | v1.2.3 |
| Data boundary enforcement | Data flows | v1.2.4 |
| Audit trail | Accountability | v1.2.4 |
| Task session compaction (chunking + local LLM summary) | Long session retrievability | v1.2.4 |
| PII classification | Sensitive data leakage | v1.2.5 |
| Sanitization layer | External exposure | v1.2.5 |
| Infrastructure routing | Reachability | ~~v1.2.6~~ superseded — ntfy + dashboard + get_content cover this |
| Policy checker pipeline (inline) | Pre-execution blocking, data boundary, violation audit | ✅ v1.2.6 |
| Policy Enforcement Agent (inbox-based) | Cross-agent proactive blocking with reasoning | v1.3.x |
| `local_only` task flag | Syntactic sugar over allowed_tiers | ✅ v1.2.6 |
| Inbox → Dreaming → Knowledge | Institutional memory, pattern learning | v1.2.x |
| Message passing + containerization | Fault isolation, language agnosticism, scale | v2.x |
