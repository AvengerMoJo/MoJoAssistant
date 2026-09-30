# Changelog

All notable changes to the MoJoAssistant project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Tool name note:** The `opencode_*` and `claude_code_*` tool names from early releases
> have been replaced by unified `agent_*` tools (`agent_start`, `agent_stop`, `agent_status`,
> `agent_list`, `agent_restart`, `agent_destroy`, `agent_action`, `agent_list_types`).

## [1.6.0] - 2026-09-30

### Added
- **opencode v1/v2 client compatibility layer** — `OpenCodeClient` now takes an
  `api_version` param (v1 or v2, validated), unwraps v2's `{"data":...}` envelope,
  and implements v2's async prompt+poll-until-idle `send_message` plus Form-based
  question reply/reject. `agent_bridge`'s `HostRegistry` and the coding-session
  handler both plumb `api_version` through per host instead of always assuming v1.
- **Basic-auth support for external HTTP MCP servers** — `ExternalMCPServer` gains
  `auth_scheme` (`bearer` default or `basic`), needed for `agent_bridge`'s
  password-based auth.
- **`fleet` and `device_control` capability categories** — `fleet` covers the
  third-party opencode+herdr workforce (AgentBridge); `device_control` covers
  remote desktop/mobile automation (`desktop_run`) for reproducing real UI bugs
  that logs/APIs alone can't show. `network_admin` role gains `fleet`.
- **`scripts/doctor_opencode.py`** — read-only opencode v2 diagnostic (auth/
  credential state, MCP server health, the herdr plugin-format error, service
  reachability), grounded against opencode's own docs rather than guessed.

### Fixed
- **Infra-unreachable questions no longer sit in the HITL queue forever** —
  `is_infra_failure_question()` detects the "Coding agent backend not reachable"
  signature and routes straight to `mark_failed()` instead of waiting on a human
  who can't answer it.
- **`Task.to_dict` was silently dropping bookkeeping fields** — the old blanket
  `_`-prefix strip removed keys like `_hitl_posted_at`, breaking Discord dedup;
  a `_DURABLE_CONFIG_KEY_PREFIXES` allowlist (`_qm_`, `_hitl_`) keeps them through
  serialization.
- **Discord HITL crash on long answer options** — Discord rejects a message if
  any button label exceeds 80 characters; labels are now truncated with the full
  text always shown in a new "Options" embed field. Also: infra-failure alerts
  now render as a grey "System Alert (no reply needed)" embed instead of the
  orange "Owner Action Required" one, so a glance at the channel shows which
  messages actually need a reply.
- **bash safety-gate blocked in-bounds paths** — `_first_blocked_path()` now uses
  `shlex.split()` and an `allowed_roots` carve-out with exact-root matching for
  `/`, fixing a bug where the blocklist matched `/` against every path
  unconditionally (`~/.memory/projects/` was being wrongly blocked).
- **Workforce dashboard page blocked ~31s by one dead host** — `/workforce` now
  renders instantly from static config, with live status fetched separately per
  host, each capped at 6s instead of running serially with a 30s timeout each.

## [1.4.2-beta] - 2026-05-27

### Added
- Version consistency enforcement — `scripts/check_version_consistency.py` validates all
  version references against `pyproject.toml` single source of truth; CI-gateable
- CHANGELOG brought current from v1.1.6 through v1.4.2

### Changed
- All version strings synchronized to v1.4.2-beta across `pyproject.toml`, `README.md`,
  `docs/MOJOASSISTANT_FULL_OVERVIEW.md`, and `app/*/__init__.py`

## [1.4.0-beta] - 2026-05-13

### Added
- Pluggable module architecture complete — every core subsystem behind an ABC contract
  with conformance suite (293 tests passing)
- Plugin SDK with scaffolding CLI (`scripts/plugin_sdk.py`), validation, and sample plugins
- Agentic Bridge Pattern — agents auto-generate third-party adapters from framework docs
- Retrieval engine module (Semantic + Hybrid strategies)
- Embedding backends module (HuggingFace, LocalServer, Random)
- Storage backends module (LocalFile, DuckDB, Mirror dual-write)
- Skill Blueprints module — runtime-installable external skills via `skill()` MCP hub
- Open `provider_type` in module descriptor schema — new module families need no core change
- Benchmark evaluation decoupled from app imports — any provider can be benchmarked

### Fixed
- Stale `TaskType.AGENT` enum reference in HITL bridge test

## [1.3.3-beta] - 2026-05-01

### Added
- PII scanner (`app/scheduler/security/pii_scanner.py`) — pattern-based detection for
  credentials, financial data, health info, infrastructure details
- `scan_text()` and `redact_pii()` APIs with `[REDACTED:type]` placeholders
- Tool args scanning integrated into policy pipeline

## [1.3.2-beta] - 2026-04-28

### Added
- Agent type classification (`agent_type` field in role JSON): provisioner, researcher,
  analyst, coder, assistant
- Workflow templates (`config/workflow_templates/{type}.json`) auto-injected at task start
- OpenAI-compatible proxy (`/v1/models`, `/v1/chat/completions`) — any LLM client talks
  to any role directly
- Cross-role referral (`refer_to_role` tool in Role Chat)
- `scheduler_add_task` available as agent tool — roles can dispatch sub-tasks to each other

## [1.3.1-beta] - 2026-04-25

### Added
- Agent learning loop — failure-to-lesson pipeline in AgenticExecutor
- Memory context injection at task start — relevant lessons prepended to agent context
- Per-role silo memory (`lessons/`, `task_history/` directories under `~/.memory/roles/`)
- Failure taxonomy: missing_resource, wrong_tool, missing_permission, ambiguous_goal,
  external_unavailable, knowledge_gap
- Cross-agent memory reference via `search_memory(role_id=...)`

## [1.3.0-beta] - 2026-04-20

### Added
- Behavioral security layer — parallel observer (BehavioralMonitor) with per-role baselines
  using exponential moving average
- ContainmentEngine — three-tier response: LOW (silent ntfy), MEDIUM (sandbox honeypot),
  HIGH (hard halt)
- SandboxRuntime — honeypot containment: bash in tmpdir, file ops in sandbox, network blocked
- Forensics logging — containment events written to `~/.memory/security/containment_log.jsonl`
- 23 behavioral security patterns across 4 categories (credential access, C2/reverse shells,
  exfiltration, privilege escalation)

## [1.2.16-beta] - 2026-04-16

### Added
- Two-tier role growth: framework-shared knowledge (`scope="framework"`) + role-private
- ConfigHealer — runtime config improvement via `doctor(action="improve")`
- 3-layer CapabilityResolver (system defaults → role capabilities → runtime override)
- Role system prompt engine — dynamic generation from role fields
- Benchmark evaluation harness (LOCOMO, LongMemEval, ABCD e2e, Role memory)
- Systemd service scripts for 24/7 operation

### Fixed
- Empty response loop for thinking models (Qwen `<think>` tags producing empty `response_text`)
- Qwen XML tool call leakage — tool calls emitted as plain text instead of function-call API
- `agentic_capable` results now have 7-day TTL instead of permanent block
- Startup recovery: PENDING tasks retry, zombie cleanup, interrupted task re-queue
- HITL executor: ask_user pause/resume, budget extension persistence, empty question fix

## [1.2.14-beta] - 2026-04-05

### Added
- Budget extension mechanism — agents request more iterations via `BUDGET_EXTENSION_REQUEST`
- `pinned_resource` — pin a task to a specific LLM resource for model comparison
- FINAL_ANSWER fallback auto-extraction when agents forget `<FINAL_ANSWER>` tags

### Fixed
- `available_tools` category names not expanded (LLM received empty tool list)
- Task completion push notifications never fired (EventLog not written by scheduler)
- `get_context` blocking inbox showed stale historical tasks
- Parallel tool call runaway (Gemma batching dozens of identical calls) — dedup + cap at 10
- Double push notification per task completion

## [1.2.8-beta] - 2026-03-29

### Added
- ConfigDoctor v1.2.6/v1.2.7 checks (policy, memory, scheduler, role/local_only)
- Dependency resilience — numpy/sentence_transformers soft-import with graceful fallback

### Fixed
- Malformed JSON tool-call arguments now return structured error to model
- Consecutive no-tool drift forcing message (model responds with prose but no tools)
- Role chat tool-loop budget — forces final text-only call when iterations exhausted
- `datetime.utcnow()` deprecation across 9 files, 20 call sites

## [1.2.7-beta] - 2026-03-25

### Added
- Security Sentinel role — nightly scheduled security digest from EventLog
- Sub-agent dispatch (`dispatch_subtask`) with depth-limit (max 3)
- Role chat interface at `/dashboard/chat` with persistent session history
- Iteration budget HITL — surfaces "grant more iterations?" instead of hard-failing
- Atomic fact extraction (KnowledgeUnit pipeline) for document dreaming

### Fixed
- MCPServerManager stop/restart hardening — clean state on partial failures
- Memory path conflict (`MEMORY_PATH` not respected by dreaming storage)
- Dreaming document tasks rejected with missing `conversation_id`

## [1.2.6-beta] - 2026-03-22

### Added
- Policy enforcement pipeline — pluggable checkers before every tool call
  (Static, ContentAware, DataBoundary, ContextAware)
- `local_only` shorthand for roles — locks to free-tier local resources only
- Data boundary enforcement (`allow_external_mcp`, `allowed_tiers`)
- MCP server lifecycle management (start/stop/restart/status)
- Two-layer `mcp_servers.json` (system + personal overlay)
- Urgency + importance → attention routing matrix
- Monitoring dashboard at `/dashboard` (live EventLog, task list, policy violations)
- Per-task tmux socket isolation (`/tmp/mojo-task-{id}.sock`)

### Fixed
- EventLog cross-thread write fix (asyncio.Lock → threading.Lock)
- MCPClientManager race-condition fixes (connect lock, stale flag reset, wait_for timeout)

## [1.2.4-beta] - 2026-03-20

### Added
- Audit trail — every non-free LLM call logged to `~/.memory/audit_log.jsonl` (metadata only)
- `audit_get` MCP tool for querying audit records
- Multi-source dreaming: inbox distillation + session compaction fed through dreaming pipeline
- `behavior_rules.exhausts_tools_before_asking` — role-level rule preventing premature `ask_user`
- Section 21 enforcement: MCP layer rejects tasks without `role_id`

### Fixed
- Stale inbox fix — completed/failed tasks no longer produce phantom blocking items

## [1.2.3-beta] - 2026-03-17

### Added
- Unified two-layer `resource_pool.json` (system + personal) replacing `llm_config.json`
- `acquire_by_requirements()` — roles declare capabilities, pool finds best match
- Tool catalog (`tool_catalog.json`) with category-based access replacing explicit tool lists
- MCPClientManager — any MCP server becomes agent tools via `mcp_servers.json` config
- `web_search` (Google Custom Search) and `fetch_url` builtin tools

## [1.2.2-beta] - 2026-03-14

### Added
- Generic coding agent integration (CodingAgentExecutor) with pluggable backends
- HITL permission bridge for OpenCode file write/shell command approval
- Per-source attention routing (config-driven max/min levels per source)
- `ask_user` universal HITL escape hatch — injected into every agentic task

### Fixed
- `add_conversation` latency — embedding generation moved to background task
- MEMORY_PATH hardcoded path fixes

## [1.2.1-beta] - 2026-03-11

### Added
- Attention Layer — deterministic classifier assigns hitl_level 0–5 to every event
- MCP tool consolidation: ~49 visible schemas → 12 (5 top-level + 7 action hubs)
- `get_context` type system (orientation, attention, events, task_session)
- Zero-latency scheduler wake signal (replaced 60s sleep polling with asyncio.Event)
- Config-driven default tasks in `scheduler_config.json`

## [1.1.8-beta] - 2026-03-08

### Added
- UnifiedLLMClient — single LLM call path consolidating 5 separate code paths
- Nine Chapter role/personality system (role_design_start/answer, role_create, role_list/get)
- Config-driven scheduler tasks + persistent event log (500-event circular buffer)
- `scheduler_list_agent_tools` MCP tool for tool discovery
- LLM config with nested sub-accounts, dynamic model detection via `/v1/models` probe

### Fixed
- ToolDefinition missing `parameters`, bash_exec whitelist → blacklist
- Dreaming pipeline: `D_archive["path"]` → `D_archive["storage_location"]` KeyError

## [1.1.7-beta] - 2026-03-05

### Added
- Agentic quality gates — exact-text, required content, bounded length checks with correction loop
- Dynamic resource policy selection based on task complexity and recent failures
- Parallel discovery mode (fan-out to multiple workers, aggregated parent result)
- Human-in-the-loop review report with summary, recommendation, ranked results

## [1.1.6-beta] - 2026-03-08

### Added
- Google Calendar scheduler integration (end-to-end validated)
- OpenRouter multi-account free-tier routing with failover
- Dynamic free-model discovery via OpenRouter `/models` API
- Resource pool hot-reload (auto-detects config/env changes)
- Template seeding support for `dynamic_tools.json` and `planning_prompts.json`

### Fixed
- Sandbox path expansion for `~` in safety_policy.py
- Local LLM startup changed to lazy initialization (unblocking scheduler init)

## [1.1.5-beta] - 2026-03-04

### Added
- **Agentic Scheduler**: Autonomous LLM agent loop with three-phase architecture
  - **Phase 1 — Resource Pool & Executor**: `ResourceManager` with tier-based selection
    (free/free_api/paid), rate limiting, budget tracking; `AgenticExecutor` think-act loop
  - **Phase 2 — Concurrent Execution & Tool Use**: Semaphore-based concurrent task execution
    (`max_concurrent=3`), built-in `memory_search` tool for agentic tasks
  - **Phase 3 — Session Memory & Notifications**: Persistent per-task conversation trails,
    task resume support, automatic dreaming consolidation after agentic task completion
- **Safety Policy System**: Immutable safety rules sandboxing file ops to `~/.memory/`
- **Dynamic Tool Registry**: Six built-in tools with sandbox security and safe-command whitelisting
- **Planning Prompt Manager**: Four versioned planning workflows configurable at runtime
- **Operation Audit Log**: All tool executions tracked in `config/tool_operation_logs.json`
- **SSE Notification Sidecar**: Real-time task lifecycle events via `GET /events/tasks`
- **Generic Config Tool**: Single `config` MCP tool with help/get/set and dot-notation paths

### Changed
- Unified `agent_*` MCP tools now use `AgentRegistry` for cleaner backend dispatch
- Removed incorrect `tool_registry_*` / `planning_*` MCP tools from external API

### Fixed
- Tilde not expanded in `os.makedirs()` and `Path.resolve()`
- Module-level singleton instantiation causing import-time side effects

## [1.1.4-beta] - 2026-02-23

### Added
- **Dreaming Pipeline (A→B→C→D)**: Four-stage autonomous memory consolidation
- Resilient LLM JSON parsing with four-pass strategy for handling malformed output
- Versioned archives with incremental `archive_v<N>.json` files
- Scheduler-driven automation: nightly dreaming tasks at 3:00 AM
- Coding agent policies: `AGENTS.md` and `Coding Agents Rules.md`

### Fixed
- Fixed scheduler task rescheduling after completion
- Fixed thread safety in scheduler daemon

## [1.1.3-beta] - 2026-02-21

### Added
- **Smart Installer with AI Agents**: Conversational setup using Model Selector and Environment Configurator
- **Tool-Based Configuration**: LLM uses structured tool calls to configure `.env` values
- Comprehensive environment variable documentation (60+ variables)
- Model catalog system with curated model metadata
- **LMStudio Integration**: Multi-port detection and API token support

### Changed
- Directory reorganization: 42 files moved to proper structure

## [1.1.0] - 2026-02-09

### Added
- **OpenCode Manager**: Production-ready AI agent orchestration layer
- N:1 architecture — multiple OpenCode instances through single global MCP tool
- SSH deploy key management with per-project auto-generation
- State persistence across system restarts
- Health monitoring with auto-recovery

## [1.1.0-beta] - 2026-02-07

### Added
- **OpenCode Manager (N:1 Architecture)**: Lifecycle management for OpenCode instances
- Multi-project support with simultaneous instance management
- Per-project SSH deploy keys (auto-generated ED25519)
- Development mode with auto-reload support

## [1.0.1] - 2026-01-21

### Added
- SSH key passphrase detection and timeout protection for git operations
- OAuth 2.1 Authorization Server for Claude Connectors with PKCE flow
- JWT token validation with signature verification

### Security
- SSH key validation before repository registration prevents hanging on passphrased keys
- JWT signature verification ensures only valid OAuth tokens are accepted
- OAuth PKCE flow prevents authorization code interception

### Performance
- Multi-model memory uses all three embedding models (bge-m3:1024, gemma:768, gemma:256) in parallel

## [1.0.0] - 2025-09-23

### Added
- Initial MCP Server with unified STDIO and HTTP protocol support
- Multi-model embedding system with BAAI/bge-m3 and Google embeddinggemma-300m
- Four-tier memory architecture (working, active, archival, knowledge)
- Google Custom Search API integration
