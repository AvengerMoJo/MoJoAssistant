# MoJoAssistant — Full Architecture & Vision Overview

**Version:** v1.4.2-beta  
**Author:** Alex Lau  
**Last updated:** 2026-05-13

---

## What Is MoJoAssistant?

MoJoAssistant (MoJo) is a **local-first personal AI assistant framework**. It sits between you and your AI systems — keeping your memory, context, workflow state, and agent tasks on your own hardware, then exposing everything through a clean tool surface that any AI client (Claude, Claude Code, or a custom agent) can use directly.

The fundamental promise: **your data never leaves your machine unless you explicitly allow it.**

MoJo is not a chatbot. It is the infrastructure layer that makes AI assistants genuinely personal — they remember who you are, how you work, what matters to you, and they grow more calibrated over time. Every role (persona) you create accumulates its own memory, learns from its own mistakes, and evolves its presentation style through a structured growth architecture.

---

## The Architecture in One Picture

```
┌────────────────────────────────────────────────────────────────────┐
│                        AI Clients                                   │
│          Claude Desktop · Claude Code · Custom Agents               │
└──────────────────────────────┬─────────────────────────────────────┘
                               │  Model Context Protocol (MCP)
                               │  14 stable hub tools
┌──────────────────────────────▼─────────────────────────────────────┐
│                       MoJo Core (Orchestration)                     │
│                                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │
│  │  Scheduler  │  │  Policy      │  │  HITL Inbox  │  │  Roles  │ │
│  │  + BRIDLE   │  │  Pipeline    │  │  + Audit     │  │  System │ │
│  └─────────────┘  └──────────────┘  └──────────────┘  └─────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │               Provider Registry                                  ││
│  │  Memory · Dream · Persona · Growth · Skill                      ││
│  │  Retrieval · Embedding · Storage                                 ││
│  └─────────────────────────────────────────────────────────────────┘│
└───────────┬──────────────────────────────────────────────────────────┘
            │  Pluggable modules (git submodules + pip install)
┌───────────▼──────────────────────────────────────────────────────────┐
│                        Module Layer                                   │
│                                                                       │
│  dreaming-memory-pipeline  ·  agency-agents  ·  [your module]        │
│  ABCD pipeline             ·  NineChapter    ·  [any ABC impl]        │
└───────────────────────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────────────┐
│                    Data Stores (~/.memory/)                           │
│                                                                       │
│  conversations/  ·  roles/  ·  dreams/  ·  knowledge_units/         │
│  task_sessions/  ·  config/  ·  owner_profile.json                   │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Core Layers

### 1. The MCP Tool Surface

MoJo exposes **14 hub tools** over the Model Context Protocol. Every AI client sees the same stable surface regardless of what's running underneath. The tools are:

| Tool | What it does |
|------|-------------|
| `memory` | Add, search, and archive conversations and knowledge |
| `get_context` | Read the current context — memory, tasks, events — in one call |
| `search_memory` | Semantic search across all memory stores |
| `add_conversation` | Write a new conversation entry |
| `dream` | Trigger or inspect the dreaming pipeline |
| `knowledge` | Manage the knowledge base (add, search, get file from repo) |
| `scheduler` | Add, list, get, remove, and manage tasks |
| `role` | Create, edit, list roles + growth/persona/one-on-one actions |
| `skill` | Catalog, install, test, and uninstall dynamic tool blueprints |
| `config` | Read and write config; run doctor diagnostics |
| `agent` | Lifecycle hub for external agents (Claude Code, OpenCode) |
| `external_agent` | HITL bridge for coding agents to inject questions |
| `reply_to_task` | Deliver an answer back to a waiting agent |
| `task_report_read` | Read the output report of a completed task |

The surface is intentionally small and stable. Everything complex happens inside the hub actions, not by adding new top-level tools.

---

### 2. The Scheduler

The scheduler is MoJo's task runner. It manages a queue of tasks across multiple types:

- **`internal_assignment`** — a role (AI persona) thinks through a goal autonomously using its tools
- **`dreaming`** — nightly memory consolidation pipeline
- **`scheduled`** — cron-based recurring tasks (daily briefings, weekly one-on-ones, growth snapshots)
- **`external_agent`** — a third-party coding agent (Claude Code, OpenCode) runs inside MoJo's HITL loop
- **`custom`** — user-defined single-shot tasks

Tasks run in a resource pool. Each role has a tier preference (local free model first, external API as fallback). The scheduler tracks every task's iteration budget, enforces caps, and records full session logs for dreaming and benchmarking.

**HITL (Human-in-the-Loop):** Any task can pause mid-execution and inject a question into the owner's inbox via `ask_user`. The owner answers; the task resumes. This is the foundation of MoJo's trust model — agents always have an escalation path to the human, and the human can interrupt any task at any time.

---

### 3. The Policy Pipeline

Every action a role attempts passes through the policy pipeline before execution. The pipeline checks:

- **Data boundary** — does this action try to send data outside its allowed scope?
- **Security sentinel** — does this match a behavioral pattern flagged as dangerous? (23 patterns across 4 categories: credential access, exfiltration, privilege escalation, destructive operations)
- **PII scanner** — does the output contain credentials, financial data, health information, or infrastructure details?
- **Danger budget** — has this task exceeded its allowed risk level for this run?

The policy pipeline is enforced at the MCP layer — roles cannot bypass it by calling tools directly. Every violation is written to the append-only audit log with task ID, role ID, timestamp, and action attempted.

---

### 4. The Role System

A **role** is a named AI persona with:
- A dynamic system prompt assembled from role fields at dispatch time (not a hardcoded string)
- A capability set (which tools it can use — expandable at runtime)
- A data boundary (what memory scopes it can read and write)
- A NineChapter personality score (five dimensions: core values, emotional reaction, cognitive style, social orientation, adaptability)
- Its own private memory store (knowledge units, lessons, task history, growth snapshots)
- A BRIDLE growth profile (see below)

Roles are defined in `~/.memory/roles/{role_id}.json`. They are portable — a role definition can be moved between MoJo instances. The memory is separate and travels with the role's `~/.memory/roles/{role_id}/` directory.

**Role types** (agent_type field):
- `provisioner` — infrastructure setup, Docker/Portainer management, system configuration
- `researcher` — information gathering, synthesis, knowledge management
- `analyst` — data analysis, reporting, pattern recognition
- `coder` — code generation, review, debugging
- `assistant` — general-purpose conversational + task execution

Workflow templates per agent type are auto-injected at task start.

---

### 5. The Memory Architecture

Memory in MoJo has three layers:

**Layer 1 — Working Memory (Conversations)**
Raw conversation sessions written to `~/.memory/conversations_multi_model.json`. Every `add_conversation` call lands here. Searchable immediately via embedding similarity.

**Layer 2 — Knowledge Units (Dreaming output)**
Atomic facts extracted from conversations by the ABCD dreaming pipeline. Each knowledge unit carries: content, source session, extraction timestamp, semantic embeddings (multiple models), and relevance metadata. Stored per role in `~/.memory/roles/{role_id}/knowledge_units/`.

**Layer 3 — Dream Archives (Long-term)**
The output of the full ABCD pipeline — deduplicated, cross-referenced, semantically organized. Stored in `~/.memory/dreams/`. Old conversation data is archived here; the dream archive is the canonical long-term memory.

**Knowledge isolation:** Each role's knowledge is physically scoped. `knowledge_search` queries only the calling role's knowledge store. `memory_search` queries the owner's global memory. This is enforced in code, not just in prompts.

**Two-tier growth:**
- **Role-private** (`scope="role"`) — what this role has learned, stays with this role
- **Framework-wide** (`scope="framework"`) — patterns that all agents benefit from (e.g. "tool X requires argument Y to be a string, not an integer")

---

## The Module System

### Core Principle

> MoJo Core is an orchestration engine, not an implementation.

The core owns: the MCP surface, the scheduler, the policy pipeline, the role system, and the data store formats. Everything else — how memory is consolidated, how personas are scored, how roles grow, how skills are defined, how embeddings are computed, how data is stored — is a **module**: a pluggable implementation behind an abstract interface.

This is not aspirational. The `dreaming-memory-pipeline` submodule already demonstrates the pattern. Swapping it for a better memory model requires one `git submodule add` and one `pip install`. No core code changes. Existing conversations are immediately available to the new module.

### The Provider Registry

At startup, MoJo discovers all modules via `module.json` descriptors. Each descriptor declares:
- `name` — unique identifier
- `provider_type` — what kind of module this is (open string, not a closed enum)
- `entry_point` — the Python class that implements the ABC
- `contract_version` — which version of the interface it satisfies
- `dependencies` — other modules it depends on

The registry validates every descriptor against the schema, checks the dependency graph, and reports violations through the doctor subsystem. `MOJO_STRICT_MODULE_LOADING=1` makes any load error a fatal startup failure.

### The Eight Provider Families

#### Memory Provider
**Contract:** `MemoryProvider` ABC  
**Methods:** `add_conversation`, `get_conversation`, `search_conversations`, `add_knowledge`, `search_knowledge`, `archive_knowledge`, `health_check`  
**Default:** `HybridMemoryService` backed by `dreaming-memory-pipeline`  
**What it enables:** Any memory backend — Redis, PostgreSQL, Chroma, Weaviate, or a custom embedding store — can be plugged in without changing how roles use memory.

#### Dream Provider
**Contract:** `DreamProvider` ABC  
**Methods:** `run_stage_a`, `run_stage_b`, `run_stage_c`, `run_stage_d`, `run_pipeline`, `validate_input`  
**Default:** `DreamingPipeline` from `dreaming-memory-pipeline` submodule  
**What it enables:** The ABCD pipeline is the reference implementation. A better consolidation model (different LLM, different clustering algorithm, graph-based synthesis) slots in by satisfying the same interface over the same conversation store.

#### Retrieval Strategy
**Contract:** `RetrievalStrategy` ABC  
**Methods:** `search(query_embedding, candidates, max_results, threshold)` → `List[ScoredResult]`  
**Implementations:** `SemanticStrategy` (cosine over one model), `HybridStrategy` (weighted multi-model fusion)  
**Config key:** `retrieval.strategy`  
**What it enables:** Switching from single-model cosine similarity to BM25, to learned sparse retrieval, to a reranker — with no changes to how memory is stored or how roles query it.

#### Embedding Backend
**Contract:** `EmbeddingBackend` ABC  
**Methods:** `embed(text)` → `List[float]`, `embed_batch(texts)` → `List[List[float]]`  
**Implementations:** `HuggingFaceBackend`, `LocalServerBackend`, `RandomBackend`  
**Config key:** `embedding.backend`  
**What it enables:** Switching embedding models (all-MiniLM → E5 → BGE → OpenAI → Cohere) requires only a config change. New backends are generated by agents via the Agentic Bridge Pattern (see below).

#### Storage Backend
**Contract:** `StorageBackend` ABC  
**Methods:** `read`, `write`, `delete`, `list_keys`  
**Implementations:** `LocalFileStorageBackend` (default), `DuckDBStorageBackend`, `MirrorBackend`  
**What it enables:** The persistence layer is fully abstracted. `MirrorBackend` enables zero-downtime migrations — dual-write to old and new backends simultaneously, then validate parity before cutting over.

#### Persona Provider
**Contract:** `PersonaProvider` ABC  
**Methods:** `generate(spec)` → `RoleDefinition`, `score(role_def)` → `PersonaScore`, `list_personas(filter)` → `List[PersonaSummary]`  
**Default:** `AgencyPersonaModule` backed by `agency-agents` submodule (184 pre-built personas, NineChapter scoring)  
**What it enables:** A different persona system — OCEAN-based, culturally specific, domain-specific — can replace or complement the current one without touching role execution.

#### Growth Provider
**Contract:** `GrowthProvider` ABC  
**Methods:** `snapshot(role_id)`, `evaluate(role_id, signals)`, `propose(role_id, evaluation)`, `validate_proposal(role_id, proposal, decision)`  
**Default:** `BonsaiGrowthModule` wrapping `BonsaiEngine` + `SnapshotManager`  
**What it enables:** The BRIDLE growth architecture (see below) is the default. A different growth model — pure reinforcement learning, RLHF-based, or community-calibrated — can be swapped in via config.

#### Skill Provider
**Contract:** `SkillProvider` ABC  
**Methods:** `catalog`, `blueprint`, `install`, `install_blueprint`, `uninstall`, `test`, `search`  
**Default:** `DefaultSkillProvider` with two-layer blueprint loading (system + personal)  
**What it enables:** Skills are parameterized blueprints — templates for building dynamic tools in any environment. An agent can adopt an external tool (GitHub CLI, CubeSandbox, custom API) at runtime by submitting a blueprint dict. MoJo validates and installs it without any code change.

---

## BRIDLE — The Growth Architecture

**BRIDLE:** Bonsai Refinement through Iterative Directed Learning and Evolution.

Every AI assistant today gives the same answer regardless of who it's talking to. BRIDLE is the architecture for growing an assistant's *taste* — not what it knows, but how it presents what it knows, what it chooses to highlight, and how it evolves its presentation style over time in response to the owner's preferences.

### The Four Pillars

```
┌──────────────┬──────────────┬───────────────┬────────────────┐
│   GROWTH     │  DIRECTION   │     DNA       │    PRESENT     │
│  (Memory)    │ (One-on-One) │  (Dreaming)   │    (HITL)      │
├──────────────┼──────────────┼───────────────┼────────────────┤
│ Task         │ Owner        │ ABCD pipeline │ Growth         │
│ reflections  │ weekly       │ updates core  │ proposals      │
│ accumulate   │ one-on-one   │ values and    │ validated      │
│ per role     │ calibration  │ long-term     │ before they    │
│              │              │ memory        │ take effect    │
└──────────────┴──────────────┴───────────────┴────────────────┘
```

**GROWTH (shipped):** Each task reflection is written to the role's private memory. The agent learning loop synthesizes failure patterns into lessons. Framework-wide patterns are shared across all agents. Growth snapshots capture the role's personality state at a point in time.

**DNA (shipped):** The ABCD dreaming pipeline runs nightly. Raw conversations → deconstructed semantic facts → synthesized global view → long-term archive. The dream archive feeds back into search, making old conversations retrievable at the right level of abstraction.

**DIRECTION (planned):** Weekly owner one-on-one calibration session. The owner reflects on the role's recent behavior — what worked, what felt off, what should change. This feeds directly into the next growth proposal. Blocked on the chat→dream bridge (the infrastructure to preserve one-on-one conversations into the dream pipeline).

**PRESENT (planned):** Every growth proposal — a proposed change to the role's personality or presentation style — must be validated by the owner before it takes effect. The HITL inbox is already built. The `hitl_callback` injection point is reserved in `BonsaiGrowthModule`. Wiring is deferred until DIRECTION exists, because proposals need calibration input to be meaningful.

### Why This Matters

A CFO role that has accumulated 6 months of growth knows: this owner cares about downside risk more than upside potential; she wants numbers first, context second; she trusts the model but wants to see the assumptions. That taste is not in the system prompt. It is in the role's growth snapshot — built incrementally, validated by the owner, anchored by dreaming. It is genuinely personal.

---

## The Agentic Bridge Pattern

### The Problem

Every time a promising third-party framework appears — a new embedding server, a vector store, a reranking service, a graph database, a sandbox runtime — someone has to read the docs, write glue code, test it, and maintain it as the framework evolves. This is integration tax. It scales linearly with the number of integrations and freezes the system in the choices made at build time.

### The Solution

**MoJo owns the interface. An agent generates the adapter. The conformance suite is the judge. No developer writes glue code.**

```
External framework (GitHub, PyPI, REST API, local server)
        │
        ▼
  [MoJo Bridge Agent]
   ← reads our ABC + conformance tests
   ← reads the framework's docs/README/API spec
        │
        ▼
  Generates bridge implementation
        │
        ▼
  Conformance suite runs automatically
        │
    pass ──→ bridge committed, config updated, system uses it
    fail ──→ agent reports gap, iterates or escalates to HITL
```

### The Three Invariants

For every pluggable concern, MoJo maintains:

1. **The ABC** — a Python abstract base class with complete docstrings defining the semantics of every method, including invariants ("results sorted descending by score", "never returns None")

2. **The conformance suite** — parametrized tests covering every method. A bridge that passes is correct by definition. No manual integration testing needed.

3. **The bridge installer prompt** — a self-contained agent prompt that gives the ABC, the conformance tests, and instructions to study the target framework and write a passing bridge. Any capable agent, dispatched with this prompt + the target's documentation URL, can independently produce a correct adapter.

### Example: Embedding Backends

`docs/bridges/embedding_backend_bridge_prompt.md` is the bridge installer prompt for the `EmbeddingBackend` ABC. To add support for OpenAI embeddings, Cohere, SIE, Ollama, or any other embedding service, you dispatch a MoJo agent with that prompt and the target's API documentation URL. The agent writes `HuggingFaceBackend` → `OpenAIBackend` (or whatever is needed), runs the conformance suite, and commits only if it passes. You change one config key. Done.

### Open `provider_type`

`module.json` descriptors use a free-form `provider_type` string — not a closed enum. Someone can ship a module with `provider_type: "orchestration"` or `provider_type: "voice"` or `provider_type: "network"` and MoJo loads and registers it without any core change. The conformance suite is the only gate. This is the schema expression of the self-growing architecture: **new module families need no core code change**.

---

## The Skill System

Skills are **parameterized tool blueprints** — templates for building dynamic tools in any environment, without hardcoding personal configuration into shared code.

A `SkillBlueprint` has:
- An `executor_template` — a shell command with `${VAR}` placeholders for environment-specific values
- A `template_vars` map — each variable with type, description, and optional default
- A `parameters` schema — what the tool accepts at call time
- `test_args` — safe arguments for smoke-testing after install

When a user installs a skill, MoJo substitutes their values for the `${VAR}` placeholders and writes the final tool entry to `~/.memory/config/dynamic_tools.json`. The blueprint stays in the system catalog; the rendered tool is personal.

**Agent-mediated adoption:** The `skill_installer_prompt.md` is a self-contained agent prompt for adopting any external tool. The agent studies the target, generates a conforming blueprint dict, and calls `install_blueprint()`. MoJo validates the blueprint, saves it, and renders the tool. No developer involvement.

**CubeSandbox** (`https://github.com/tencentcloud/CubeSandbox`) is the canonical proof-of-concept: a KVM/RustVMM-based sandbox with an E2B-compatible Python SDK. The current worktree already includes the CubeSandbox client (`app/scheduler/sandbox/cubesandbox_client.py`) and the sandbox-first OpenCode bootstrap path (`app/scheduler/handlers/coding_session_opencode.py`). The reference blueprints (`cubesandbox_exec`, `cubesandbox_create`) are the expected output of the skill installer agent run against the CubeSandbox README. With a live server, the full end-to-end test is: dispatch agent → generates blueprints independently → installs → smoke test passes.

---

## The Plugin SDK

Third-party module authors — or MoJo agents building new module types at runtime — have a complete path from template to conformance-passing provider:

**`scripts/plugin_sdk.py scaffold`**
```bash
python3 scripts/plugin_sdk.py scaffold \
  --provider skill \
  --name my_redis_skill \
  --out ./my-plugin/
```
Generates: `module.json`, `src/my_redis_skill/provider.py` (stub implementing the ABC), `tests/test_provider.py` (standalone duck-typing conformance check), `pyproject.toml`.

**`scripts/plugin_sdk.py validate ./my-plugin/`**
Checks: schema validity, entry_point format, importability, and ABC subclass relationship (when MoJo is in path). Custom `provider_type` values get a warning to define the ABC and conformance suite before integration — not an error.

**Sample plugins** in `examples/plugins/`:
- `sample-memory-plugin/` — full working in-memory `MemoryProvider` implementation (reference for new memory backends)
- `sample-persona-plugin/` — minimal `PersonaProvider` stub (reference for custom persona systems)

---

## Connectivity & Infrastructure

### MCP Connectivity Options

MoJo exposes its tool surface over MCP. Three connectivity modes:

**Local (same machine)**
Claude Code on the same computer connects directly to `http://localhost:3100/mcp`. Zero config beyond starting MoJo.

**Cloudflared tunnel**
Exposes MoJo to Claude.ai (browser) or remote Claude Code with zero port-forwarding:
```bash
cloudflared tunnel --url http://localhost:3100
```
Produces a public HTTPS URL. Add it to Claude.ai → Settings → Integrations.

**Private mesh network (post-beta)**
Self-hosted Headscale (open-source Tailscale control plane) + WireGuard for stable internal hostnames across all devices. Every node (localhost, 249 server, sandbox VMs) gets a `*.mojo.internal` hostname. Agents register nodes via a future `NetworkProvider` ABC. Deferred to post-v2.0.0.

### Infrastructure Roles

MoJo has dedicated infrastructure roles:

**Ahman** (`agent_type: provisioner`) — infrastructure guardian. Handles Docker/Portainer management, system setup, sandbox provisioning, service configuration, and CubeSandbox validation on the 249 server (`ssh -p 12345 ai-agent@192.168.2.249`).

Ahman uses `tmux` sessions for persistent terminal work and `ask_user` only for genuine blockers (missing root access, missing credentials). Everything else he executes directly.

### The 249 Server

A dedicated host at `192.168.2.249` (port 12345) used for:
- GPU-heavy workloads (model inference)
- Persistent sandbox services (CubeSandbox KVM)
- Background agent tasks that need more compute than localhost

Access: `ssh -p 12345 -i ~/.ssh/ahman_id_ed25519 ai-agent@192.168.2.249`

---

## Security Architecture

### Three-Tier Behavioral Security

**LOW** — anomaly detected, silent ntfy push to owner  
**MEDIUM** — honeypot sandbox activated; role continues in isolation without knowing it's contained  
**HIGH** — hard halt; task terminated; owner notified

The `BehavioralMonitor` runs as a parallel observer on every task. It maintains per-role behavioral baselines from 23 patterns across 4 categories. A deviation triggers the appropriate tier.

### Data Boundary Enforcement

Each role operates within a declared data boundary. Attempts to read memory outside the boundary (e.g. reading another role's private knowledge) are blocked at the MCP layer and logged. The policy pipeline checks every tool call before execution.

### §21 Enforcement

`role_id` is mandatory at `scheduler_add_task`. Tasks that specify an inline `system_prompt` are rejected — all prompts must go through the role system, ensuring every action is attributable to a named role with a known data boundary and danger budget. This makes the privacy audit log complete and non-bypassable.

### Audit Trail

Every tool call, policy decision, and HITL event is written to an append-only audit log. `audit_get(task_id)` returns the complete provenance chain for any task: what was requested, what the policy decided, what executed, what left the device. This is the foundation of the privacy claim.

---

## Benchmarking

MoJo includes a full evaluation harness:

**LOCOMO** — 272 multi-session conversation benchmark. Phase 1 complete: Ben's role has all 272 sessions + ABCD dreams. Phase 2 (scoring) is ready to run.

**LongMemEval** — long-context memory evaluation against the provider interface (not concrete app imports). Any `MemoryProvider` implementation can be benchmarked.

**ABCD e2e** — end-to-end pipeline benchmark: raw sessions → dreams → scored recall.

**Role memory evaluation** — measures how well a role's accumulated memory improves task performance over time.

All benchmark runners use the provider interface (`get_memory_provider()`), not concrete imports. Switching the memory backend under test requires only a config change.

---

## The Road to v2.0.0

### v1.4.1 — Setup Experience (next)

The final push before dropping beta. Design doc: `docs/architecture/SETUP_EXPERIENCE.md`.

`python3 scripts/doctor.py --setup` walks a new user through:

1. **Feature validation** — live probes for every feature area with stable/experimental labels
2. **MCP server setup** — systemd service wiring
3. **Connectivity choice** — local / cloudflared tunnel / Tailscale (post-beta)
4. **LLM backend detection** — LMStudio, Ollama, or skip
5. **Final smoke run** — `pytest tests/smoke/ -m stable` with human-readable output

Pytest markers: `@pytest.mark.stable` (must pass on any supported install) and `@pytest.mark.experimental` (requires optional setup). CI runs only `stable`. Users can see both.

### v2.0.0 — Dropping Beta

Beta comes off when a stranger can install MoJoAssistant on a clean machine, run one command, and get a working system with a clear, honest picture of what it does and doesn't do.

Non-negotiable gates (all complete except setup experience):
- ✅ Audit trail + §21 enforcement
- ✅ Tool-calling reliability (one documented supported path)
- ✅ Dependency resilience
- ✅ INSTALL.md with supported path documentation
- ⚠️ Setup experience (v1.4.1)
- ⚠️ Stable vs experimental surface documented

### Post-v2.0.0

- **Self-hosted mesh network** — Headscale + WireGuard, `NetworkProvider` ABC, stable `*.mojo.internal` hostnames
- **BRIDLE DIRECTION pillar** — owner weekly one-on-one + chat→dream bridge
- **BRIDLE PRESENT pillar** — HITL growth validation
- **Message passing + containerization** — language-agnostic agents, proper process isolation
- **Community bridge registry** — shared, validated bridges for common third-party frameworks

---

## Design Principles

**1. Local-first, privacy by architecture.**
Data stays on your machine. The audit log makes every outbound action visible and attributable. Policy enforcement is at the MCP layer — not advisory, not prompt-based.

**2. The data store is the contract, not the code.**
Modules are replaceable as long as they honor the store schemas. A better memory model slots in over existing conversations. No migration needed.

**3. Interfaces are ours. Adapters are generated.**
MoJo defines every interface and conformance suite. Third-party integrations are generated by agents at runtime. We maintain the contract — not the adapters.

**4. Conformance as the install gate.**
No module ships without passing its conformance suite. A bridge that passes is correct by definition. This removes the need for manual integration testing of individual adapters.

**5. Personal configuration stays personal.**
Modules provide blueprints, not implementations. A skill blueprint defines what a tool should do. The agent instantiates it with the owner's paths, credentials, and resource limits. The blueprint is shared; the rendering is personal.

**6. Seams before extraction.**
A module doesn't need to live in a separate repo to have a clean boundary. The seam is enough until extraction is justified by actual reuse. BRIDLE is the current example: clean internal boundary, submodule extraction deferred until the four-pillar contract is proven stable.

**7. Never force modularity ahead of stability.**
Extraction follows proof of boundary. A premature extraction creates two unstable things instead of one.

**8. Agents as first-class citizens.**
The scheduler, HITL inbox, and resource pool treat AI agents — both internal roles and external coding agents — as the primary users of the infrastructure. Human oversight is built into every loop, not bolted on afterward.

---

## Key Files & Paths

| Path | What it is |
|------|-----------|
| `app/services/provider_contracts.py` | All ABCs and data types for every provider family |
| `app/mcp/core/tools.py` | The 14 MCP hub tools — entry point for all client interactions |
| `app/scheduler/` | Task queue, executor, HITL, policy pipeline, role execution |
| `app/scheduler/bonsai.py` | BonsaiEngine — core BRIDLE growth implementation |
| `app/scheduler/growth_provider.py` | `BonsaiGrowthModule` — GrowthProvider adapter |
| `app/scheduler/skill_provider.py` | `DefaultSkillProvider` — blueprint loading and install |
| `app/scheduler/doctor.py` | System health checks + module validation |
| `submodules/dreaming-memory-pipeline/` | ABCD memory consolidation pipeline |
| `submodules/agency-agents/` | 184 personas + NineChapter scoring |
| `~/.memory/` | All personal data (conversations, roles, dreams, config) |
| `~/.memory/config/dynamic_tools.json` | Installed skill tools (personal layer) |
| `~/.memory/owner_profile.json` | Owner identity, relationships, communication preferences |
| `config/skill_blueprints/` | System-layer skill blueprints |
| `docs/architecture/` | Full architecture documentation |
| `docs/schemas/module.json` | Module descriptor schema |
| `scripts/plugin_sdk.py` | Plugin scaffold + validate CLI |
| `tests/conformance/` | Full conformance suite (293 tests) |
