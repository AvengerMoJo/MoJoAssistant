# Module Migration Plan

Status: Active  
Date: 2026-05-10  
Target: v2.0.0 public release  
Design context: [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md)

---

## Goal

By v2.0.0, MoJo Core should be an orchestration engine with clean, versioned seams to pluggable modules. Every major intellectual component — memory consolidation, persona generation, role growth, skill definitions — lives in a module with a declared interface and a `module.json`.

The migration is incremental. Seams come before extraction. Extraction comes before stabilization.

---

## Modules in Scope

| Module | Type | Current State | Submodule? | Target |
|--------|------|--------------|------------|--------|
| dreaming-memory-pipeline | Memory | Partially extracted, shims in place | Yes | Formalize interface, add module.json |
| agency-agents | Persona | Submodule, parser working, 185 personas | Yes | Add module.json, NineChapter as interface |
| BRIDLE/Bonsai | Growth | Built into Core, clean seam | No | Extract in v1.5.x |
| Skill Blueprint | Skill | No module yet, tools in dynamic_tools.json | No | New submodule in v1.4.x |
| Data Storage | Contract | Informal, no version tags | N/A | Formalize schemas in DATA_CONTRACTS.md |

---

## Phase 0 — Document the direction (v1.3.x) ✓ Done

- [x] Write `MOJO_MODULE_SYSTEM.md` — modular architecture vision
- [x] Write `DATA_CONTRACTS.md` — canonical schema definitions with version tags
- [x] Write `MODULE_MIGRATION_PLAN.md` — this document
- [ ] Add links from `SYSTEM_README.md` and `README.md`

---

## Phase 1 — Formalize existing submodules (v1.4.x)

### 1a. dreaming-memory-pipeline

The memory module migration started in v1.3.x (shims in place, mojo_memory package committed to submodule). Finish the contract.

**Tasks:**
- [ ] Add `module.json` to submodule root declaring `implements: MemoryModule@1.0`
- [ ] Define `MemoryInterface` class in submodule (`src/mojo_memory/interface.py`) with `ingest`, `search`, `consolidate`, `export`, `import_from` methods
- [ ] Add `memory export` command to CLI: dumps all dreams + conversation store to a portable archive
- [ ] Add `memory import` command: restores from archive, rebuilds search index
- [ ] Add ownership guardrail CI check: `app/memory/*` and `app/services/memory_service.py` must be shims only
- [ ] Update `config(action="doctor")` to load and validate `module.json` for each submodule

**Acceptance criteria:**
- Running `pip install -e submodules/dreaming-memory-pipeline` + swapping the submodule pointer works with no Core changes
- `memory export` produces a portable `.tar.gz` that can be restored on a different machine
- CI fails if a non-shim line is added to `app/memory/*`

---

### 1b. agency-agents

**Tasks:**
- [ ] Add `module.json` declaring `implements: PersonaModule@1.0`
- [ ] Add `interface.py` with `generate(spec)`, `score(role_def)`, `list_personas(filter)` 
- [ ] NineChapter scoring exposed as a stable function (currently called inline in role creation)
- [ ] `role(action="create")` MCP tool calls the Persona module interface, not internal functions
- [ ] Add smoke test: `from agency_agents.interface import PersonaModule; m = PersonaModule(); assert len(m.list_personas()) > 100`

**Acceptance criteria:**
- NineChapter scores computed via module interface, not internal import
- A replacement persona module with the same interface can be swapped in

---

## Phase 2 — Skill Blueprint submodule (v1.4.x)

The skill system today: agents write scripts to `~/.memory/sandbox-skills/` and register entries in `dynamic_tools.json`. No shared spec for what a skill looks like.

**New submodule:** `mojo-skill-blueprints` (or `mojo-arsenal`)  
Provides parameterizable templates, not pre-built personal scripts.

**Structure:**
```
mojo-skill-blueprints/
  module.json
  blueprints/
    container/
      blueprint.json      ← skill spec (intent class, args, preconditions, test)
      template.sh         ← script template with {MEMORY_PATH}, {CONTAINER_NAME} placeholders
      test.sh             ← smoke test for the installed skill
    sandbox/
      blueprint.json
      template.sh
      test.sh
    web/
      curl_request.json   ← simple tool, no script needed
  interface.py            ← SkillModule@1.0 implementation
```

**Tasks:**
- [ ] Create `mojo-skill-blueprints` repo and add as submodule
- [ ] Migrate Ahman's container skills (container_create/exec/destroy) as reference blueprints
- [ ] Migrate existing sandbox skills (sandbox_create/sync/status/destroy/list) as blueprints
- [ ] Implement `install(skill_id, env)` — instantiates template with env vars, writes to `dynamic_tools.json`, runs `test.sh`
- [ ] Add `skill(action="install", blueprint_id="container/container_create")` MCP tool action
- [ ] Add `skill(action="list")` showing available blueprints vs. installed tools

**What stays personal:** The instantiated scripts in `~/.memory/sandbox-skills/` and the runtime entries in `dynamic_tools.json`. The blueprint module provides the pattern; the agent fills in personal configuration.

---

## Phase 3 — Extract BRIDLE/Bonsai as Growth module (v1.5.x)

BRIDLE is currently built into MoJo Core. The seam is clean (four-pillar design), but the implementation touches the scheduler, role system, and HITL directly.

Extraction preconditions:
- Scheduler API must be stable (v1.4.x)
- Role system must have a clean read interface
- HITL callback must be injectable

**Tasks:**
- [ ] Define `GrowthInterface` in MoJo Core: `snapshot`, `evaluate`, `propose`, `validate`
- [ ] Refactor BRIDLE to call only through defined interfaces (no internal imports)
- [ ] Extract to `mojo-growth` submodule
- [ ] Add `module.json`
- [ ] MoJo Core loads growth module via `module.json` discovery, not hardcoded import

**Note:** HITL validation (PRESENT pillar) stays in MoJo Core — it is an orchestration concern, not a growth concern. The growth module proposes; Core validates with the owner.

---

## Phase 4 — Data Storage portability (v1.5.x–v2.0.0)

Conversation store and dream archives must be portable across machines and MoJo versions.

**Tasks:**
- [ ] Add `schema_version: "ConversationStore@1.0"` field to `conversations_multi_model.json`
- [ ] Add `schema_version: "DreamArchive@1.0"` to dream archive metadata
- [ ] Add `schema_version: "RoleDefinition@1.0"` to role JSON files
- [ ] Add version compatibility check at startup: warn if module declares incompatible `data_contracts`
- [ ] Build `mojo export` CLI command: produces portable archive of all user data (conversations, dreams, roles, dynamic tools) — importable on a fresh install
- [ ] Build `mojo import` CLI command: restores from archive, re-indexes, validates module compatibility

**Acceptance criteria:**
- Full user data survives a fresh install on a new machine
- A new memory module can be pointed at exported conversation data and build a search index without MoJo running

---

## Phase 5 — Module discovery at startup (v2.0.0)

**Tasks:**
- [ ] MoJo Core scans `submodules/*/module.json` at startup
- [ ] Each declared module runs its `health_check` command
- [ ] `config(action="doctor")` reports module health alongside MCP server health
- [ ] Modules that fail health check degrade gracefully (warn, not crash)
- [ ] `config(action="doctor_improve")` suggests install commands for failed modules

---

## What Does Not Change

MoJo Core's stable surface — the 14 MCP tools, the scheduler API, the role system, the policy pipeline, the HITL loop — does not change as a result of this migration.

Modules plug into Core. Core does not plug into modules.

The data stores are the interface. Modules read and write stores; they do not call Core internals.

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Submodule per module, not a monorepo plugin system | Git submodules are already the established pattern; no new tooling needed |
| Data stores as interface, not Python ABCs | Avoids tight coupling between Core and module language; future modules could be in any language |
| Personal skills stay personal | Container paths, resource limits, network names are environment-specific; blueprint provides pattern only |
| BRIDLE extraction deferred to v1.5.x | Scheduler API not yet stable enough to define a clean GrowthInterface without fighting internal coupling |
| Import/export in v1.5.x | Requires schema versions to be stable first; Phase 4 depends on Phase 1 completion |
