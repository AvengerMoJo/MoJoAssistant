# Release Notes — v1.4.0-beta

**Date:** 2026-05-13
**Tag:** `v1.4.0-beta`
**Commits since v1.3.7-beta:** 44
**Test suite:** 293 passed, 1 skipped, 0 failures

---

## Theme: Pluggable Module Architecture Complete

v1.4.0 closes the module architecture chapter. Every core subsystem —
memory, dream, persona, growth, skill, retrieval, embedding, and storage —
is now behind an ABC contract with a conformance suite and a pluggable
registry. No subsystem requires a core code change to be replaced, extended,
or augmented by a third-party implementation.

The other half of the story is the **Agentic Bridge Pattern**: third-party
adapters are no longer written by hand. An agent studies the external
framework, generates a conformance-passing bridge, and installs it at
runtime. The bridge installer prompt is the delivery mechanism. The
conformance suite is the only gate.

This release also ships the **Plugin SDK** — scaffolding, validation CLI,
and two sample plugins — so third-party module authors have a clear path
from template to conformance-passing provider without touching MoJo's
internals.

---

## What Shipped

### #1 — Dream Provider Full Extraction

The dreaming pipeline now lives entirely in the `dreaming-memory-pipeline`
submodule. The `app/dreaming/` layer is shim-only — thin compatibility
wrappers that delegate to the submodule. No app-layer code depends on
dream internals directly.

### #2 — Provider Registry Hardening

The module registry now validates every discovered descriptor against
`docs/schemas/module.json` at startup. Added:
- `validate_descriptor()` / `validate_all_descriptors()` — jsonschema checks
- `check_dependency_graph()` — flags modules whose declared dependencies are not registered
- `MOJO_STRICT_MODULE_LOADING` env var — raises `RuntimeError` on any load error when set
- `doctor.py` `_check_modules()` surfaces violations as `"error"` CheckResults

### #3 — Conformance Suite Expansion

293 tests across all provider families, CI gated. Added provider families:
- Persona, Growth, Skill conformance suites
- `test_provider_matrix.py` — every provider tested against both default and mock alternative
- CI workflow `Conformance Suite Gate` step — no module merges without passing

### #4 — Retrieval Engine Module

Retrieval policy is now a first-class swappable strategy, not buried in
memory provider internals.

- `RetrievalStrategy` ABC + `ScoredResult` dataclass in `provider_contracts.py`
- `SemanticStrategy` — cosine similarity over a single embedding model
- `HybridStrategy` — weighted multi-model fusion
- Strategy registry: `get_strategy(name)` / `register_strategy(name, instance)`
- `HybridMemoryService` reads `config.retrieval.strategy` at init; no code change required to switch
- `module.json` declares `retrieval_strategies` and `default_retrieval_strategy` capabilities

### #5 — Embedding Backends Module

Embedding implementations are decoupled from the memory provider and
adoptable via the Agentic Bridge Pattern.

- `EmbeddingBackend` ABC in `provider_contracts.py`
- Built-in backends: `HuggingFaceBackend`, `LocalServerBackend`, `RandomBackend`
- Backend registry: `register_backend(name, factory)` / `get_backend(name)`
- `SimpleEmbedding` refactored to delegate to the registry-selected backend
- Config key `embedding.backend` selects the active backend at startup
- Bridge installer prompt: `docs/bridges/embedding_backend_bridge_prompt.md`
  — self-contained agent prompt for generating any third-party bridge (SIE,
  OpenAI, Cohere, Ollama, vLLM) that passes the conformance suite

### #6 — Storage Backends Module

The persistence layer is fully abstracted. Switching backends requires no
code change — only config or dependency injection.

- `StorageBackend` ABC in `mojo_memory/storage/base.py`
- `LocalFileStorageBackend` — default reference implementation
- `DuckDBStorageBackend` — relational + vector-ready extension point
- `MirrorBackend` — dual-write fan-out for zero-downtime migrations with parity validation
- `ConversationSchema` — canonical schema for conversation records
- Backend registry/factory for dynamic plugin loading
- `MultiModelEmbeddingStorage` and `KnowledgeManager` migrated to injected backend
- Runtime guide: `docs/guides/STORAGE_BACKEND_RUNTIME.md`

### #7 — Persona Provider Completion

NineChapter scoring and persona generation moved fully into the
`agency-agents` submodule.

- `PersonaProvider` ABC + data types in `provider_contracts.py`
- `AgencyPersonaModule` default adapter in `app/roles/persona_provider.py`
- Persona descriptor added to `submodules/agency-agents/module.json`
- MCP `role()` gains: `persona_list`, `persona_score`, `create` via `persona_spec`/`persona_file`
- `app/scheduler/ninechapter.py` converted to compatibility shim
- Interface docs: `submodules/agency-agents/docs/PERSONA_MODULE_INTERFACE.md`

### #8 — Growth Provider Extraction

The Bonsai growth engine is now accessible through the `GrowthProvider`
interface — no direct scheduler coupling, HITL injection point reserved.

- `GrowthProvider` ABC in `provider_contracts.py`
- `BonsaiGrowthModule` adapter in `app/scheduler/growth_provider.py`
  — wraps `BonsaiEngine` + `SnapshotManager` (snapshot/evaluate/propose/validate)
- `register_growth_provider` / `resolve_growth_provider` / `MOJO_GROWTH_PROVIDER` env override
- MCP `role()` gains: `growth_snapshot`, `growth_propose`, `growth_validate`
- `hitl_callback: Optional[Callable] = None` — PRESENT pillar injection point reserved

Note: DIRECTION (one-on-one calibration) and PRESENT (HITL validation)
pillars are designed but not yet implemented. `hitl_callback=None` keeps
the interface stable until those pillars exist.

### #9 — Skill Blueprints Module

External skills are installable at runtime without editing core files.
Agents adopt external tools by studying them and submitting a blueprint
dict — MoJo validates and installs.

- `SkillBlueprint`, `InstallResult`, `SkillTestResult`, `TemplateVarSpec` dataclasses
- `SkillProvider` ABC: `catalog / blueprint / install / install_blueprint / uninstall / test / search`
- `DefaultSkillProvider` — two-layer loading (system + personal), `${VAR}` template substitution
- `skill()` MCP hub — 8 actions
- `register_skill_provider` / `resolve_skill_provider` / `MOJO_SKILL_PROVIDER` env override
- System blueprints: `curl_request`, `sandbox_create`, `read_file`, `cubesandbox_exec`, `cubesandbox_create`
- Skill installer prompt: `docs/skills/skill_installer_prompt.md`
- **CubeSandbox** (`https://github.com/tencentcloud/CubeSandbox`) — KVM/RustVMM sandbox
  with E2B-compatible SDK. Reference blueprints are the proof-of-concept for the
  agent-mediated skill installation pattern. Server installation in progress (Ahman).

### #10 — Benchmark Eval Decoupling

Benchmark runners no longer import `app.*` at module level. Any provider
implementing the contracts can be benchmarked without the full app stack.

- `tests/benchmarks/provider_runtime.py` — `get_memory_provider()` adapter
- `run_longmemeval.py` — migrated to provider runtime
- `run_locomo.py` — `LLMInterface` import moved inside `build_llm()` (lazy)
- `run_locomo_abcd_e2e.py` — `DreamingPipeline` + `LLMInterface` imports moved into function body
- `tests/smoke/test_benchmark_decoupling.py` — regression guards for all three runners

### #11 — Plugin SDK

Third-party module authors have a complete path from template to
conformance-passing provider.

- `scripts/plugin_sdk.py scaffold --provider <type> --name <name> --out <dir>`
  — generates `module.json`, provider stub, standalone duck-typing test, `pyproject.toml`
- `scripts/plugin_sdk.py validate <dir>`
  — checks schema, entry_point format, importability, and ABC subclass when MoJo is in path
- `provider_type` accepts any custom string — `orchestration`, `voice`, `network`, etc.
  No enum restriction. Conformance suite is the only gate.
- Sample plugins: `examples/plugins/sample-memory-plugin/` and `sample-persona-plugin/`
- SDK guide: `docs/guides/PLUGIN_SDK.md`

### Agentic Bridge Pattern

Full pattern spec: `docs/architecture/AGENTIC_BRIDGE_PATTERN.md`

The self-growing architecture: MoJo defines the interface and conformance
tests and never owns third-party adapters. To adopt a new embedding
framework, vector database, or orchestration engine:

1. Dispatch a MoJo agent with the bridge installer prompt + the target's docs URL
2. Agent studies the external framework, writes a conformance-passing adapter
3. Agent runs the conformance suite — commit only if it passes
4. Config change selects the new backend — no developer glue code required

### `docs/schemas/module.json` — Open `provider_type`

Changed from a closed enum `["memory","dream","persona","growth","skill"]`
to an open pattern `^[a-z][a-z0-9_]*$`. New module types are valid without
any core change. This is the schema expression of the self-growing
architecture principle.

---

## Bug Fixes

- `test_hitl_bridge::test_stub_task_type_is_agent` — stale `TaskType.AGENT`
  reference corrected to `TaskType.EXTERNAL_AGENT` (enum was renamed, test
  wasn't updated)

---

## Known Gaps

- **Growth DIRECTION pillar** — owner weekly one-on-one calibration; deferred
  pending chat→dream bridge
- **Growth PRESENT pillar** — HITL blocking validation; `hitl_callback` slot
  reserved in `BonsaiGrowthModule`, wiring deferred until DIRECTION exists
- **CubeSandbox e2e validation** — live server installation in progress;
  end-to-end skill install + smoke test pending

---

## Up Next: v1.4.1-beta — Setup Experience

The final push before v2.0.0 (dropping beta). Design doc:
`docs/architecture/SETUP_EXPERIENCE.md`

- `python3 scripts/doctor.py --setup` — live feature validator with stable/experimental labels
- Interactive MCP + connectivity wizard: local / cloudflared tunnel / Tailscale (post-beta)
- Pytest `@pytest.mark.stable` / `@pytest.mark.experimental` markers
- Stable vs experimental surface table in `INSTALL.md`

---

## Upgrade Notes

No breaking changes. Existing configs, role files, and `module.json`
descriptors are fully compatible. The `provider_type` schema change is
backward-compatible — all existing values match the new open pattern.
