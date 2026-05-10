# Core Module Extraction List

Status: Active  
Last updated: 2026-05-10  
Related: [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md) · [DATA_CONTRACTS.md](DATA_CONTRACTS.md) · [MODULE_MIGRATION_PLAN.md](MODULE_MIGRATION_PLAN.md)

---

## Scope Rule

Keep in core only:
- MCP surface and protocol handling (`app/mcp/**`)
- Scheduler and orchestration (`app/scheduler/core.py`, `queue.py`, `executor.py`, `triggers.py`)
- HITL loop (`app/mcp/routers/hitl.py`, `app/scheduler/hitl_bridge.py`)
- Role/policy routing (`app/scheduler/policy/**`, `app/scheduler/security_gate.py`)
- App bootstrap and config (`app/config/**`)
- Thin provider wiring (registry, shims)

Everything else below should be extracted or is already extracted.

---

## Module Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ Done | Extracted and committed to submodule |
| 🔄 In progress | Shims in place, submodule exists, interface not yet formalized |
| 📋 Planned | Clear seam, scheduled for extraction |
| 🔬 Research | Seam not yet clean enough to extract |

---

## Memory + Dream Modules

### 1. `memory-provider` ✅ Done (Phase 1)
**Lives in:** `submodules/dreaming-memory-pipeline/src/mojo_memory/`  
**Core shims:** `app/memory/*.py`, `app/services/memory_service.py`, `app/services/hybrid_memory_service.py`  
**Boundary:** conversation CRUD/search, knowledge CRUD/search, archive operations  
**Exposes:** `MemoryProvider` contract — see [DATA_CONTRACTS.md](DATA_CONTRACTS.md) `ConversationStore@1.0`  
**Remaining work:**
- [ ] Add `module.json` to submodule root
- [ ] Define `MemoryInterface` class (`ingest`, `search`, `consolidate`, `export`, `import_from`)
- [ ] CI ownership guardrail: fail if `app/memory/*.py` grows beyond shim

---

### 2. `dream-provider` 🔄 In progress (Phase 1)
**Lives in:** `submodules/dreaming-memory-pipeline/src/mojo_memory/` + `app/dreaming/`  
**Issue:** `app/dreaming/` (pipeline.py, chunker.py, synthesizer.py, etc.) is still in Core — not yet shimmed  
**Boundary:** ABCD stages, dream artifact generation, consolidation flow  
**Exposes:** `DreamProvider` contract — see [DATA_CONTRACTS.md](DATA_CONTRACTS.md) `DreamArchive@1.0`  
**Remaining work:**
- [ ] Move `app/dreaming/*.py` implementations into submodule
- [ ] Replace `app/dreaming/*.py` with compatibility shims (same pattern as memory)
- [ ] Expose `DreamProvider` interface through submodule `interface.py`
- [ ] Add ownership guardrail for `app/dreaming/`

---

### 3. `provider-contracts` ✅ Done (renamed)
**Now lives in:** [DATA_CONTRACTS.md](DATA_CONTRACTS.md)  
Canonical versioned schemas for ConversationStore, TaskSession, RoleDefinition, DreamArchive, DynamicTool, NineChapterScore.  
Any module reading/writing these stores must conform. Schema versions increment on breaking changes.

---

### 4. `provider-registry` 📋 Planned (Phase 5, v2.0.0)
**Boundary:** module registration, discovery, startup validation, compatibility checks  
**Currently:** no formal registry — submodules are loaded by hardcoded imports  
**Remaining work:**
- [ ] Scan `submodules/*/module.json` at startup
- [ ] Run each module's `health_check` command
- [ ] Surface failures in `config(action="doctor")`
- [ ] Version compatibility check: warn if module `data_contracts` version mismatches Core

---

### 5. `provider-adapters` ✅ Done (compatibility shims)
The `app/memory/*.py` and `app/services/*.py` shims are the adapter layer.  
**Removal target:** after all import call sites are migrated to `mojo_memory.*` canonical namespace.  
**Tracker:** `docs/architecture/MEMORY_DREAM_SUBMODULE_MIGRATION_PLAN.md` Phase 4

---

### 6. `retrieval-engine` 🔬 Research
**Lives in:** Scattered across `app/memory/simplified_embeddings.py` (now in submodule), `app/services/hybrid_memory_service.py` (shim), and `app/scheduler/` query paths  
**Boundary:** ranking, fusion, context assembly policy  
**Issue:** retrieval strategy is currently embedded in memory service implementation, not separated as a policy layer  
**Remaining work:**
- [ ] Define retrieval strategy interface (BM25, semantic, hybrid fusion)
- [ ] Move strategy selection out of memory implementation and into a configurable layer
- [ ] Target: v2.0.0 or later

---

### 7. `embedding-backends` 🔬 Research
**Lives in:** `submodules/dreaming-memory-pipeline/src/mojo_memory/memory/simplified_embeddings.py`  
**Boundary:** embedding model integrations (HuggingFace local, API, stub)  
**Issue:** currently tightly coupled to the memory provider; not independently swappable  
**Remaining work:**
- [ ] Define `EmbeddingBackend` interface
- [ ] Move backend-specific code behind interface
- [ ] Allow configuration of backend without changing memory provider
- [ ] Target: v2.0.0

---

### 8. `storage-backends` 🔬 Research
**Lives in:** `submodules/dreaming-memory-pipeline/src/mojo_memory/memory/multi_model_storage.py`  
**Boundary:** persistence drivers (JSON, SQLite, vector, object storage)  
**Issue:** JSON-first implementation, no driver abstraction yet  
**Remaining work:**
- [ ] Define `StorageBackend` interface
- [ ] JSON driver is the default/reference implementation
- [ ] SQLite and vector store as future alternate drivers
- [ ] Target: v2.0.0+

---

## Persona Module

### 9. `persona-provider` 🔄 In progress (Phase 1b)
**Lives in:** `submodules/agency-agents/` + `app/roles/agency_agents_bridge.py`, `app/roles/agency_agents_parser.py`, `app/roles/agency_importer.py`  
**Also in Core:** `app/scheduler/ninechapter.py` — NineChapter scoring logic  
**Boundary:** role definition generation from spec, NineChapter scoring, persona catalog  
**Exposes:** `PersonaModule@1.0` — `generate(spec)`, `score(role_def)`, `list_personas(filter)`  
**Remaining work:**
- [ ] Add `module.json` to `submodules/agency-agents/`
- [ ] Move `app/scheduler/ninechapter.py` into `agency-agents` submodule as canonical home
- [ ] Add `interface.py` to submodule exposing `PersonaModule@1.0`
- [ ] `role(action="create")` MCP tool calls module interface, not internal import
- [ ] Add shim in Core for backward-compat imports from `app/scheduler/ninechapter`

---

## Growth Module

### 10. `growth-provider` (BRIDLE/Bonsai) 📋 Planned (Phase 3, v1.5.x)
**Lives in:** `app/scheduler/bonsai.py` + scattered BRIDLE logic in `app/scheduler/agentic_executor.py`, `app/roles/role_manager.py`  
**Boundary:** role snapshots, dimension drift evaluation, growth proposals, HITL validation  
**Four pillars:** GROWTH (memory), DIRECTION (one-on-one), DNA (dreaming), PRESENT (HITL)  
**Exposes:** `GrowthModule@1.0` — `snapshot`, `evaluate`, `propose`, `validate`  
**Coupling blockers:**
- `bonsai.py` imports scheduler internals directly
- PRESENT pillar calls HITL loop — must remain injectable, not hardcoded
- Role manager interleaves growth logic with CRUD operations
**Remaining work:**
- [ ] Define `GrowthInterface` in Core (pure abstract — no implementation)
- [ ] Refactor `bonsai.py` to call Core only through defined interfaces
- [ ] Extract to `mojo-growth` submodule
- [ ] Add `module.json`
- [ ] HITL callback stays in Core; Growth module calls it via injected function

**Note:** PRESENT pillar (HITL validation) is a Core orchestration concern. Growth module proposes; Core validates with owner. This boundary must be enforced in the interface.

---

## Skill Module

### 11. `skill-blueprints` 📋 Planned (Phase 2, v1.4.x)
**Currently:** no submodule — agents write to `~/.memory/config/dynamic_tools.json` and `~/.memory/sandbox-skills/` directly  
**Boundary:** parameterized skill templates, install + test harness, capability category declarations  
**Exposes:** `SkillModule@1.0` — `catalog()`, `blueprint(skill_id)`, `install(skill_id, env)`, `test(skill_id)`  
**Reference implementations to migrate:**
- Ahman's container skills (`container_create`, `container_exec`, `container_destroy`)
- Sandbox skills (`sandbox_create`, `sandbox_sync`, `sandbox_status`, `sandbox_destroy`, `sandbox_list`)
- `curl_request`, `project_management` tool definitions
**Remaining work:**
- [ ] Create `mojo-skill-blueprints` repo and add as submodule
- [ ] Define blueprint JSON schema (name, intent_class, args, preconditions, template, test)
- [ ] Migrate existing skills as reference blueprints with `{MEMORY_PATH}` placeholders
- [ ] Implement `install(skill_id, env)` — instantiates template, writes to `dynamic_tools.json`, runs test
- [ ] Add `skill(action="install")` and `skill(action="list")` MCP tool actions

**Key principle:** blueprints are patterns, not pre-built personal scripts. Each user's agent instantiates the blueprint with their environment. See [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md).

---

## Quality + DX Modules

### 12. `benchmark-eval` 🔄 In progress
**Lives in:** `tests/benchmarks/`, `app/benchmarking/`  
**Boundary:** LOCOMO, LongMemEval runners, ABCD validation harness, role memory eval  
**Status:** LOCOMO Phase 1 complete (272 sessions, ABCD dreams). Harness expanded in recent commits.  
**Remaining work:**
- [ ] Extract benchmark runners into standalone package (no Core imports required to run)
- [ ] `docs/benchmarks/shared/ABCD_VALIDATION_CHECKLIST_v1.md` is the active validation protocol
- [ ] Target: clean separation by v2.0.0 so benchmarks can run against any conforming provider

---

### 13. `conformance-suite` 📋 Planned
**Boundary:** provider contract tests — any module claiming `MemoryModule@1.0` must pass these  
**Currently:** no formal conformance tests; smoke tests exist but are Core-coupled  
**Remaining work:**
- [ ] Define conformance test suite per interface (`MemoryModule`, `PersonaModule`, `GrowthModule`, `SkillModule`)
- [ ] CI gate: new submodule must pass conformance before merging
- [ ] Target: v2.0.0

---

### 14. `plugin-sdk` 🔬 Research
**Boundary:** scaffolding for third-party module authors  
**Currently:** not started — premature until at least one full extraction cycle is complete  
**Target:** post v2.0.0

---

### 15. `docs-specs` ✅ Done (in progress)
**Lives in:** `docs/architecture/`  
- [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md) — modular architecture vision
- [DATA_CONTRACTS.md](DATA_CONTRACTS.md) — versioned schemas
- [MODULE_MIGRATION_PLAN.md](MODULE_MIGRATION_PLAN.md) — phased migration to v2.0.0
- [CORE_MODULE_EXTRACTION_LIST.md](CORE_MODULE_EXTRACTION_LIST.md) — this document

---

## Extraction Order (Dependency-First)

Unchanged from original — rationale still holds:

1. **`provider-contracts`** ✅ → now `DATA_CONTRACTS.md`
2. **`provider-registry`** → v2.0.0 (depends on stable contracts)
3. **`memory-provider`** ✅ + **`dream-provider`** 🔄 → parallel tracks, Phase 1
4. **`persona-provider`** 🔄 → Phase 1b (agency-agents + NineChapter)
5. **`skill-blueprints`** → Phase 2, v1.4.x (new submodule)
6. **`growth-provider`** → Phase 3, v1.5.x (BRIDLE/Bonsai extraction)
7. **`embedding-backends`** + **`storage-backends`** → v2.0.0 (after provider internals stable)
8. **`retrieval-engine`** → v2.0.0
9. **`benchmark-eval`** → v2.0.0 (standalone, no Core imports)
10. **`conformance-suite`** → v2.0.0
11. **`plugin-sdk`** → post v2.0.0

---

## Merge Gates Per Extraction

### 1. Contract Gate
- New/changed contract types are versioned in `DATA_CONTRACTS.md`
- No silent signature changes
- Module declares `data_contracts` in `module.json`

### 2. Boundary Gate
- Core does not import module internals directly
- Ownership checker (`scripts/check_memory_dream_ownership.py`) passes
- Pattern extends to all extracted modules

### 3. Compatibility Gate
- Default providers pass conformance suite
- Backward-compat shims remain functional until cutover milestone
- No import breakage in existing tests

### 4. Quality Gate
- Smoke tests pass for MCP + scheduler + CLI flows
- Benchmark harness still executes
- `config(action="doctor")` reports module health correctly

### 5. Documentation Gate
- Module `module.json` present and valid
- `CORE_MODULE_EXTRACTION_LIST.md` status updated
- `MODULE_MIGRATION_PLAN.md` phase task checked off

---

## Done Criteria For Full Modular Cutover (v2.0.0)

1. Core runtime depends only on module interfaces and data contracts — no internal imports
2. Memory, dream, persona, growth, and skill modules are all outside Core
3. At least one alternative provider can be plugged in without Core code changes
4. `provider-registry` discovers and health-checks all modules at startup
5. Legacy shim layer removed or explicitly deprecated behind flag
6. CI fails on any reintroduction of direct Core-to-module internal coupling
7. Full user data export/import works across a fresh install
