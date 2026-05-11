# Module Implementation TODO (Parallel Execution Spec)

## Purpose
Execution checklist for all planned module extractions/implementations so multiple agents can work in parallel with consistent standards.

## Mandatory Spec For All Modules
Every module implementation MUST follow:
- [Module Adoption How-To](/home/alex/Development/Personal/MoJoAssistant/docs/guides/MODULE_ADOPTION_HOWTO.md)

This guide is the normative implementation pattern for:
1. contract implementation
2. module descriptor (`module.json`)
3. discovery/registration
4. runtime selection
5. conformance/verification

## Global Rules (All Agents)
1. Own one module only per PR.
2. Do not edit other module ownership areas.
3. Include tests in same PR.
4. Include `module.json` if module is pluggable.
5. Pass gates before handoff:
- `python3 scripts/check_memory_dream_ownership.py`
- `python3 -m pytest tests/smoke/test_imports.py -q`
- `python3 -m pytest tests/conformance/test_provider_conformance.py -q` (or module-specific conformance when added)

## TODO Modules

### 1. Dream Provider Full Extraction
Status: `DONE` (2026-05-11)

Scope:
- Move remaining `app/dreaming/*` implementation internals into submodule provider paths.
- Keep only compatibility shims in app layer.

Deliverables:
1. `app/dreaming/*` reduced to shim-only files.
2. Submodule owns dream implementation internals.
3. Dream provider uses contract-consistent return shapes for all stages/pipeline.

Acceptance:
- No direct core dependency on dream internals.
- Doctor module checks show discoverable/loadable dream module.

---

### 2. Provider Registry Hardening
Status: `IN PROGRESS`

Scope:
- Strengthen module discovery/validation/runtime behavior.

Deliverables:
1. Validate discovered descriptors against `docs/schemas/module.json`.
2. Add dependency checks (`dependencies` graph in module descriptors).
3. Add startup policy switch for strict mode (fail on module load errors).
4. Extend doctor output with dependency/descriptor validation diagnostics.

Acceptance:
- Invalid descriptor -> deterministic doctor error.
- Missing dependency -> deterministic doctor error/warn per policy.

---

### 3. Conformance Suite Expansion
Status: `IN PROGRESS`

Scope:
- Expand beyond memory/dream into planned module families.

Deliverables:
1. Add conformance skeletons for Persona, Growth, Skill modules.
2. Add CI workflow gate for conformance suite.
3. Add plugin matrix test path (default provider + mock alternative provider).

Acceptance:
- New module cannot merge without passing its conformance contract tests.

Dependency update:
- Persona interface is now defined (`PersonaProvider` / `PersonaModule@1.0`), so Persona conformance work no longer needs to wait on #7.

---

### 4. Retrieval Engine Module
Status: `PLANNED`

Scope:
- Separate retrieval policy from memory provider internals.

Deliverables:
1. Define retrieval strategy interface.
2. Implement baseline strategies (semantic/hybrid).
3. Wire strategy selection via config (no code edits required to switch).

Acceptance:
- Memory provider delegates retrieval policy through strategy interface.

---

### 5. Embedding Backends Module
Status: `PLANNED`

Scope:
- Decouple embedding implementations from memory provider.

Deliverables:
1. `EmbeddingBackend` interface.
2. Backends: local/HF/API adapters.
3. Selection by configuration/environment.

Acceptance:
- Switching backend requires no provider code changes.

---

### 6. Storage Backends Module
Status: `PLANNED`

Scope:
- Abstract persistence layer.

Deliverables:
1. `StorageBackend` interface.
2. JSON backend as reference.
3. SQLite/vector backend stubs with clear extension points.

Acceptance:
- Memory provider uses storage interface, not concrete JSON assumptions.

---

### 7. Persona Provider Completion
Status: `DONE (Phase 1b core goals)`

Scope:
- Finish extraction of persona generation/scoring logic.

Deliverables:
1. Move `ninechapter` scoring into persona submodule.
2. Expose module interface callable from core tooling.
3. Keep core shim for backward compatibility until cutover.

Completed:
1. `PersonaProvider` contract + data types defined in `app/services/provider_contracts.py`.
2. Default adapter implemented: `app/roles/persona_provider.py` (`AgencyPersonaModule`).
3. Persona module descriptor added: `submodules/agency-agents/module.json`.
4. MCP `role(action="create")` supports persona-module generation path via `persona_spec` / `persona_file`.
5. Persona conformance baseline test added: `tests/conformance/test_persona_provider_conformance.py`.
6. NineChapter canonical implementation moved into submodule: `submodules/agency-agents/src/agency_agents/ninechapter.py`.
7. Core `app/scheduler/ninechapter.py` converted to compatibility shim.

Still missing for #7:
1. Route additional persona-related flows (beyond role create) through provider interface where applicable.
2. Add submodule-local interface docs/README for `PersonaModule@1.0`.

Acceptance:
- Role creation/scoring path goes through persona module interface.

---

## Missing Now (Cross-Module Snapshot)

1. Dream extraction not complete: `app/dreaming/*` still has non-shim implementation pieces.
2. Registry hardening not complete: descriptor schema validation and dependency graph enforcement still pending.
3. Conformance expansion not complete: Growth/Skill conformance suites and CI matrix gate still pending.
4. Retrieval/Embedding/Storage modular splits not started beyond planning.
5. Growth, Skill, Benchmark decoupling, Plugin SDK are still planned/research stages.

---

### 8. Growth Provider Extraction
Status: `PLANNED`

Scope:
- Extract BRIDLE/Bonsai growth logic into dedicated module.

Deliverables:
1. Define growth module contract.
2. Move growth internals out of scheduler/role manager.
3. Inject HITL callback from core (no hard dependency).

Acceptance:
- Growth module proposes; core validates/persists.

---

### 9. Skill Blueprints Module
Status: `PLANNED`

Scope:
- Externalize skill blueprint catalog and installer.

Deliverables:
1. Blueprint schema.
2. Install/test APIs.
3. Migration of current skill definitions to blueprints.

Acceptance:
- Skills can be installed from blueprint without editing core files.

---

### 10. Benchmark Eval Decoupling
Status: `PLANNED`

Scope:
- Make benchmark runners provider-interface driven and core-independent.

Deliverables:
1. Benchmark package separation.
2. Run against any provider implementing contracts.
3. Keep ABCD validation checklist integrated.

Acceptance:
- LOCOMO/LongMemEval runnable without direct app internals imports.

---

### 11. Plugin SDK
Status: `RESEARCH`

Scope:
- Developer scaffolding for third-party module authors.

Deliverables:
1. Scaffolding templates.
2. Validation CLI.
3. Minimal sample plugin package.

Acceptance:
- Third-party provider can be created from template and pass conformance.

## Agent Fan-Out Plan
Assign one agent per module:
1. Dream Extraction
2. Registry Hardening
3. Conformance Expansion
4. Retrieval Engine
5. Embedding Backends
6. Storage Backends
7. Persona Completion
8. Growth Extraction
9. Skill Blueprints
10. Benchmark Decoupling
11. Plugin SDK Research

Each agent must deliver:
1. files changed
2. tests run
3. gate checklist results
4. blockers and dependency notes

## Review Workflow (Lead Integrator)
For each incoming PR:
1. Verify module boundary ownership.
2. Verify adoption guide compliance.
3. Run smoke + conformance checks.
4. Merge only if contract/boundary/quality/docs gates are met.
