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
Status: `DONE` (2026-05-11)

Scope:
- Strengthen module discovery/validation/runtime behavior.

Deliverables:
1. Validate discovered descriptors against `docs/schemas/module.json`.
2. Add dependency checks (`dependencies` graph in module descriptors).
3. Add startup policy switch for strict mode (fail on module load errors).
4. Extend doctor output with dependency/descriptor validation diagnostics.

Completed:
1. `validate_descriptor()` / `validate_all_descriptors()` in `provider_contracts.py` — checks each descriptor against `docs/schemas/module.json` via jsonschema.
2. `check_dependency_graph()` — flags modules whose declared dependencies are not registered.
3. `MOJO_STRICT_MODULE_LOADING` env var — `discover_modules()` raises `RuntimeError` on any load error when set.
4. `doctor.py` `_check_modules()` surfaces descriptor violations and missing dependencies as `"error"` CheckResults.

Acceptance:
- Invalid descriptor -> deterministic doctor error.
- Missing dependency -> deterministic doctor error/warn per policy.

---

### 3. Conformance Suite Expansion
Status: `DONE` (2026-05-11)

Scope:
- Expand beyond memory/dream into planned module families.

Deliverables:
1. Add conformance skeletons for Persona, Growth, Skill modules.
2. Add CI workflow gate for conformance suite.
3. Add plugin matrix test path (default provider + mock alternative provider).

Acceptance:
- New module cannot merge without passing its conformance contract tests.

Completed:
1. Persona conformance: `tests/conformance/test_persona_provider_conformance.py`.
2. Growth conformance: `tests/conformance/test_growth_provider_conformance.py`.
3. Skill conformance: `tests/conformance/test_skill_provider_conformance.py`.
4. Provider matrix coverage (default + mock alternative provider): `tests/conformance/test_provider_matrix.py`.
5. CI conformance gate wired in `.github/workflows/smoke-test.yml` (`Conformance Suite Gate` step).

---

### 4. Retrieval Engine Module
Status: `DONE` (2026-05-11)

Scope:
- Separate retrieval policy from memory provider internals.

Deliverables:
1. Define retrieval strategy interface.
2. Implement baseline strategies (semantic/hybrid).
3. Wire strategy selection via config (no code edits required to switch).

Completed:
1. `RetrievalStrategy` ABC + `ScoredResult` dataclass added to `app/services/provider_contracts.py`.
2. `SemanticStrategy` (cosine over single model) and `HybridStrategy` (weighted multi-model fusion) implemented in `submodules/dreaming-memory-pipeline/src/mojo_memory/retrieval/`.
3. Strategy registry (`mojo_memory.retrieval.registry`) — `get_strategy(name)` / `register_strategy(name, instance)`.
4. `HybridMemoryService` reads `config.retrieval.strategy` at init and delegates `_get_multi_model_context` to the selected strategy; falls back to legacy path if strategy not available.
5. `module.json` declares `retrieval_strategies` and `default_retrieval_strategy` capabilities.
6. 22 conformance tests in `tests/conformance/test_retrieval_strategy_conformance.py` — contract + registry + custom strategy registration.

Acceptance:
- Memory provider delegates retrieval policy through strategy interface.

---

### 5. Embedding Backends Module
Status: `IN PROGRESS` (interface phase)

Scope:
- Decouple embedding implementations from memory provider.
- Establish the Agentic Bridge Pattern so third-party backends (SIE, OpenAI,
  Cohere, Ollama, vLLM, etc.) can be installed by a MoJo agent without any
  developer writing glue code manually.

Deliverables:
1. `EmbeddingBackend` ABC in `app/services/provider_contracts.py`.
2. Built-in backends in `mojo_memory/embeddings/backends/`:
   - `HuggingFaceBackend` — wraps current `SimpleEmbedding` HF logic
   - `LocalServerBackend` — generic HTTP embedding server (existing local path)
   - `RandomBackend` — deterministic fallback for testing
3. Backend registry: `get_backend(name)` / `register_backend(name, instance)`.
4. `SimpleEmbedding` refactored to delegate to a registered backend.
5. Config key `embedding.backend` selects the active backend at startup.
6. Conformance test suite: `tests/conformance/test_embedding_backend_conformance.py`.
7. Bridge installer prompt: `docs/bridges/embedding_backend_bridge_prompt.md` —
   the self-contained agent prompt for generating any third-party bridge (SIE,
   OpenAI, etc.) that passes the conformance suite.

Agentic Bridge Pattern (replaces manual adapter writing):
- MoJo owns the interface and conformance tests — never the third-party adapters.
- To install SIE (or any other framework): dispatch a MoJo agent with the bridge
  installer prompt + the framework's docs URL. Agent writes the bridge, runs
  conformance, commits if it passes. No developer glue code required.
- See [AGENTIC_BRIDGE_PATTERN.md](AGENTIC_BRIDGE_PATTERN.md) for the full pattern spec.

Acceptance:
- Switching backend requires only a config change (`embedding.backend = "sie"`).
- Any conformance-passing bridge can be dropped into `backends/` and registered.
- Bridge installer prompt is self-contained enough for any capable agent to execute.

---

### 6. Storage Backends Module
Status: `DONE` (2026-05-11)

Scope:
- Abstract persistence layer.

Deliverables:
1. `StorageBackend` interface.
2. Local FS backend as baseline reference.
3. DuckDB backend as advanced reference (relational + vector-ready extension point).

Completed:
1. Generic `StorageBackend` ABC in `mojo_memory/storage/base.py`.
2. `LocalFileStorageBackend` in `mojo_memory/storage/local_fs_backend.py` — default reference backend.
3. `DuckDBStorageBackend` in `mojo_memory/storage/duckdb_backend.py`.
4. Backend registry/factory (`register_storage_backend`, `create_storage_backend`) for dynamic plugin loading.
5. `MultiModelEmbeddingStorage` refactored to consume injected/selected backend instead of hardcoded file I/O.
6. `KnowledgeManager` migrated to the pluggable storage backend interface.
7. Conformance coverage in `tests/conformance/test_storage_backend_conformance.py` (local fs, duckdb when installed, custom backend registration, injected backend behavior).

Acceptance:
- Memory provider uses storage interface, not concrete JSON assumptions.

---

### 7. Persona Provider Completion
Status: `DONE` (2026-05-11)

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
8. Provider-based persona flows added in MCP role tooling:
- `role(action="persona_list")`
- `role(action="persona_score")`
9. Submodule-local interface documentation added: `submodules/agency-agents/docs/PERSONA_MODULE_INTERFACE.md`.

Acceptance:
- Role creation/scoring path goes through persona module interface.

---

## Missing Now (Cross-Module Snapshot)

1. ~~Dream extraction not complete~~ — DONE (2026-05-11).
2. ~~Registry hardening not complete~~ — DONE (2026-05-11).
3. ~~Conformance expansion~~ — DONE (2026-05-11). Growth/Skill/Persona conformance + provider matrix + CI gate. Keep extending as new provider families are added.
4. ~~Retrieval modular split~~ — DONE (2026-05-11).
5. ~~Storage backend modularization~~ — DONE (2026-05-11). LocalFile + DuckDB + registry + conformance tests.
6. Persona (#7) core extraction and interface docs are complete; future work is optimization, not structural completion.
7. ~~Growth (#8)~~ — DONE (2026-05-11). BonsaiEngine wired; HITL callback injection point reserved.
8. **Embedding Backends (#5)** — agent working on this. Needs: `EmbeddingBackend` ABC, built-in backends, conformance suite, bridge installer prompt.
9. Skill Blueprints (#9), Benchmark Decoupling (#10), Plugin SDK (#11) — still PLANNED/RESEARCH stages.

---

### 8. Growth Provider Extraction
Status: `DONE` (2026-05-11)

Scope:
- Wire existing BonsaiEngine behind the GrowthProvider interface.

Completed:
1. `BonsaiGrowthModule` adapter in `app/scheduler/growth_provider.py` wrapping
   `BonsaiEngine` + `SnapshotManager` (snapshot/evaluate/propose/validate).
2. `register_growth_provider` / `resolve_growth_provider` / `_register_default_growth_provider`
   added to `ProviderRegistry`; `MOJO_GROWTH_PROVIDER` env override supported.
3. Three MCP actions on `role()`: `growth_snapshot`, `growth_propose`, `growth_validate`.
4. Optional `hitl_callback` constructor param — the PRESENT pillar injection point for when
   blocking HITL validation is built.
5. 21 conformance tests in `tests/conformance/test_growth_provider_conformance.py`
   (parametrized over MockGrowthProvider + BonsaiGrowthModule).

Note: DIRECTION (one-on-one calibration) and PRESENT (HITL validation) pillars are
planned but not built. The `hitl_callback=None` default keeps the interface stable
until those pillars exist. Submodule extraction remains deferred until the full
four-pillar contract is proven stable.

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
