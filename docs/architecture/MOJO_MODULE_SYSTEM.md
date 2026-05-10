# MoJo Module System

Status: Design Direction  
Date: 2026-05-10  
Supersedes: fragments in RELEASE_COMPONENT_BOUNDARY.md, MEMORY_DREAM_SUBMODULE_MIGRATION_PLAN.md

---

## The Core Idea

MoJo Core is an orchestration engine, not a memory system.

It owns:
- The 14 MCP tool surface (stable API for clients)
- Scheduler and HITL loop
- Policy pipeline
- Role system and data boundary enforcement
- The canonical data store formats

Everything else — how memory is consolidated, how personas are scored, how roles grow, how skills are defined — is a **module**: a pluggable implementation of a MoJo interface, delivered as a git submodule.

The fundamental contract is the **data store**. As long as the conversation store format stays stable, any memory module can read existing conversations and produce better retrieval. Old data. Better model. One `git submodule add` + `pip install`.

This is not aspirational. `dreaming-memory-pipeline` already does it. ABCD is the first memory module — not the last.

---

## Module Types

### 1. Memory Module

Reads raw conversation sessions. Produces consolidated, searchable knowledge.

**Interface:** `MemoryModule@1.0`
```
ingest(session_path)         → KnowledgeUnit[]
search(query, role_id, k)    → Result[]
consolidate(role_id)         → ArchiveRef
export(role_id, dest_path)   → manifest
import_from(src_path)        → role_id[]
```

**Current implementation:** `submodules/dreaming-memory-pipeline`  
ABCD pipeline (A=raw session, B=chunked facts, C=clustered themes, D=semantic archive).  
Not the final model — the reference implementation. A better model slots in by satisfying the same interface over the same conversation store.

**Upgrade path:** New model ships as a new submodule. Owner runs one command. Existing conversations are re-processed. No migration needed.

---

### 2. Persona Module

Creates role definitions from a human specification. Scores roles on personality dimensions.

**Interface:** `PersonaModule@1.0`
```
generate(spec)               → RoleDefinition
score(role_def)              → NineChapterScore
list_personas(filter)        → Persona[]
```

**Current implementation:** `submodules/agency-agents`  
184 pre-built personas. NineChapter scoring (five dimensions: core_values, emotional_reaction, cognitive_style, social_orientation, adaptability). Scores are predictive confidence values, not quality grades.

**Why modular:** A different persona system (e.g. OCEAN-based, or culturally-specific) could replace or complement agency-agents without touching role execution.

---

### 3. Growth Module

Evaluates how a role is performing over time. Proposes targeted growth. Validates changes with the owner.

**Interface:** `GrowthModule@1.0`
```
snapshot(role_id)            → GrowthSnapshot
evaluate(role_id, history)   → DimensionDrift[]
propose(role_id)             → GrowthProposal
validate(proposal, hitl)     → GrowthDecision
```

**Current implementation:** Built into MoJo Core (BRIDLE framework)  
Four pillars: GROWTH (memory accumulation), DIRECTION (one-on-one calibration), DNA (dreaming consolidation), PRESENT (HITL validation).  

**Candidate for extraction** in v1.5.x. Currently too tightly coupled to the scheduler and role system to extract cleanly. The seam is clear; the move waits for runtime stability.

---

### 4. Skill Module

Defines capability blueprints — parameterized templates for building tools in any environment.

**Interface:** `SkillModule@1.0`
```
catalog()                    → SkillBlueprint[]
blueprint(skill_id)          → SkillBlueprint
install(skill_id, env)       → DynamicToolEntry
test(skill_id)               → TestResult
```

**Current implementation:** None (planned)  
Ahman builds skills at runtime into `~/.memory/config/dynamic_tools.json`. The pattern is personal — paths, resource limits, local Docker config. A skill module provides the blueprint (what a container skill looks like) without encoding personal configuration. Each user's agent instantiates the blueprint for their environment.

**Not a shared skill library.** Tools built by one user's agents stay in their `dynamic_tools.json`. The module provides the specification and test harness, not pre-built scripts.

---

## The Data Store Is the Interface

Every module reads or writes one of the canonical data stores. The stores are the API boundary — not Python classes, not REST endpoints.

| Store | Path | Owner | Consumed by |
|-------|------|-------|-------------|
| ConversationStore | `$MEMORY_PATH/conversations_multi_model.json` | MoJo Core | Memory modules |
| TaskSession | `$MEMORY_PATH/task_sessions/{id}.json` | MoJo Core | Memory modules, Growth modules |
| RoleDefinition | `$MEMORY_PATH/roles/{id}.json` | MoJo Core | All modules |
| DreamArchive | `$MEMORY_PATH/dreams/` | Memory modules | Search, Growth |
| DynamicTool | `$MEMORY_PATH/config/dynamic_tools.json` | Skill modules | Executor, CapabilityResolver |

Full schemas: see [DATA_CONTRACTS.md](DATA_CONTRACTS.md)

---

## Module Declaration

Every submodule carries a `module.json` at its root:

```json
{
  "id": "dreaming-memory-pipeline",
  "implements": "MemoryModule@1.0",
  "mojo_core_min": "1.3.0",
  "data_contracts": ["ConversationStore@1.0", "TaskSession@1.0"],
  "entrypoint": "src/mojo_memory",
  "install": "pip install -e .",
  "health_check": "python -c \"from mojo_memory.services.memory_service import MemoryService; print('ok')\""
}
```

MoJo Core reads all `submodules/*/module.json` at startup. Modules that fail their health check are reported by `config(action="doctor")` — same as external MCP servers today.

---

## What MoJo Core Never Touches

These belong to modules, not the core:

- How facts are extracted from conversations (Memory module)
- How clusters are built from facts (Memory module)
- How personas are generated (Persona module)
- How NineChapter dimensions are computed (Persona module)
- How growth proposals are formed (Growth module)
- How skill scripts are written (Skill module)

MoJo Core provides the raw material (sessions, roles, events) and the execution environment (scheduler, policy, HITL). Modules do the intellectual work.

---

## Design Principles

**1. The data store is the contract, not the code.**  
Modules are replaceable as long as they honor the store schemas. No interface inheritance required.

**2. Personal configuration stays personal.**  
Modules provide blueprints, not implementations. A skill blueprint defines what `container_create` should do. The agent instantiates it with the owner's paths and resource limits.

**3. One install away.**  
The upgrade path for any module is: `git submodule add <url> submodules/<name>` + `pip install -e submodules/<name>`. Existing data is immediately available to the new module.

**4. Seams before extraction.**  
A module doesn't need to exist as a submodule to have a seam. Clean internal boundaries (like BRIDLE's current state) are enough until extraction is justified by actual reuse need.

**5. Never force modularity ahead of stability.**  
Extraction should follow proof of boundary, not drive it. See [RELEASE_COMPONENT_BOUNDARY.md](RELEASE_COMPONENT_BOUNDARY.md).

---

## Relationship to Existing Docs

| Doc | Relationship |
|-----|-------------|
| [CAPABILITY_ABSTRACTION_CONTRACT.md](CAPABILITY_ABSTRACTION_CONTRACT.md) | Defines intent classes and provider metadata — becomes the Skill Module interface spec |
| [MEMORY_DREAM_SUBMODULE_MIGRATION_PLAN.md](MEMORY_DREAM_SUBMODULE_MIGRATION_PLAN.md) | Phase 1–3 complete; Phase 4 (shim removal) is next |
| [RELEASE_COMPONENT_BOUNDARY.md](RELEASE_COMPONENT_BOUNDARY.md) | Defines what must be stable for release — modular seams are a release requirement |
| [DREAMING_SPECIFICATION.md](DREAMING_SPECIFICATION.md) | Full spec for the current Memory module implementation |
| [BONSAI_ARCHITECTURE.md](BONSAI_ARCHITECTURE.md) | Full spec for the current Growth module (BRIDLE) — extraction candidate |
| [DATA_CONTRACTS.md](DATA_CONTRACTS.md) | Canonical schema definitions for all data stores |
| [MODULE_MIGRATION_PLAN.md](MODULE_MIGRATION_PLAN.md) | Concrete migration steps before v2.0.0 |
