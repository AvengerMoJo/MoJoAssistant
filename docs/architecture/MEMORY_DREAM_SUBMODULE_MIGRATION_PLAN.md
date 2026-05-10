# Memory + Dream Modularization Program Plan

## Objective
Evolve from a partially shared implementation to a clean modular architecture where:
- MoJoAssistant core depends on provider contracts only.
- Memory and Dream are pluggable modules with independent release cycles.
- Multiple agents can implement different modules in parallel with low merge risk.

## Why Prior Design Did Not Scale
- Split ownership between app and submodule caused drift and conflicting fixes.
- Imports pointed to concrete implementations, not interfaces.
- No compatibility contract for alternative providers.
- No CI gate for architecture boundaries.

## Architecture End State
1. Core layer (`app/`) exposes stable contracts and orchestration only.
2. Provider layer contains swappable modules:
- Memory provider (default: `mojo_memory` in submodule)
- Dream provider (default: submodule dreaming pipeline)
3. Adapter layer maps provider outputs to core MCP/scheduler/role workflows.
4. Conformance suite validates any provider plugin against required contracts.

## Ownership Boundaries
1. App Core Ownership
- `app/mcp/**`, `app/scheduler/**`, `app/roles/**`, `app/config/**`
- provider loader/registry and contract definitions
- no domain logic for memory indexing, embedding internals, dream generation internals

2. Memory/Dream Module Ownership
- `submodules/dreaming-memory-pipeline/src/mojo_memory/**`
- `submodules/dreaming-memory-pipeline/**` dreaming implementation internals
- optional future third-party plugin packages

3. Transition-only Compatibility Layer
- `app/memory/*.py`
- `app/services/memory_service.py`
- `app/services/hybrid_memory_service.py`
- must remain shims only until final removal

## Provider Contracts (Must Be Stable)
1. Memory Provider Contract
- create/read/update/search conversation memory
- archive/query structured memory units
- expose health/capability metadata
- deterministic error model (typed failures, no silent fallback)

2. Dream Provider Contract
- run ABCD pipeline stages
- output normalized dream artifacts
- provide stage-level validity metadata
- support dry-run/validation mode for benchmark harness

3. Versioning Contract
- each provider reports `provider_name`, `provider_version`, `contract_version`
- app rejects incompatible contract versions at startup

## Execution Workstreams (Parallelizable)
1. Workstream A: Contracts + Registry (Core Team)
- Define `MemoryProvider` and `DreamProvider` interfaces in app core.
- Expand `app/services/memory_backend.py` into generic provider registry/factory.
- Add config keys/env overrides for provider selection:
  - `MOJO_MEMORY_PROVIDER`
  - `MOJO_DREAM_PROVIDER`
  - provider-specific class path overrides

2. Workstream B: Memory Module Hardening (Memory Team)
- Ensure `mojo_memory` fully satisfies new memory contract.
- Add provider metadata and capability reporting.
- Remove app-only assumptions from module internals.

3. Workstream C: Dream Module Hardening (Dream Team)
- Expose dream pipeline through dream provider contract.
- Align ABCD stage outputs with benchmark validation schema.
- Add explicit retrieval-facing artifacts for downstream tools.

4. Workstream D: App Integration Refactor (Integration Team)
- Route all runtime paths via provider interfaces only.
- Remove direct import coupling from app runtime to provider internals.
- Keep compatibility behavior unchanged externally.

5. Workstream E: Testing + CI Gates (Quality Team)
- Add provider conformance test suite (memory + dream).
- Add plugin matrix smoke tests (default provider + mock provider).
- Enforce boundary checker in CI across relevant workflows.

6. Workstream F: Docs + Developer UX (DX Team)
- Publish plugin author guide with minimal template provider.
- Add migration guide for existing app.memory import users.
- Document release/version compatibility policy.

## Sequencing and Milestones
1. Milestone M1: Contract Freeze
- Contracts defined, reviewed, and versioned.
- Provider loader/registry merged.

2. Milestone M2: Default Provider Compliance
- Submodule memory/dream providers pass conformance suite.
- App runtime paths run only through factory layer.

3. Milestone M3: Compatibility Sunset Readiness
- All non-doc imports migrated off legacy paths.
- Shim usage metric near zero.

4. Milestone M4: Full Modular Cutover
- Remove app compatibility shims.
- Enforce hard CI fail on legacy import paths.

## Agent Task Partitioning (Independent Execution)
1. Agent-Core
- Files: `app/services/*provider*`, `app/config/*`, `app/mcp/core/*`
- Deliverables: contract classes, registry, startup compatibility checks

2. Agent-Memory
- Files: `submodules/dreaming-memory-pipeline/src/mojo_memory/**`
- Deliverables: memory contract implementation + metadata + tests

3. Agent-Dream
- Files: submodule dreaming pipeline paths + benchmark integration hooks
- Deliverables: dream contract adapter + ABCD validation output alignment

4. Agent-Integration
- Files: `app/mcp/**`, `app/scheduler/**`, `app/interactive-cli.py`
- Deliverables: runtime refactor to provider interfaces only

5. Agent-Quality
- Files: `tests/**`, `.github/workflows/**`, `scripts/check_memory_dream_ownership.py`
- Deliverables: conformance suite + CI gates + plugin matrix tests

6. Agent-DX
- Files: `docs/**`
- Deliverables: plugin author docs, migration docs, compatibility matrix

## Integration Rules
1. Every workstream must ship with tests.
2. No workstream may modify another workstream's owned files without explicit handoff.
3. Contract changes require synchronized updates across:
- provider implementation
- conformance tests
- docs compatibility matrix
4. Main branch merge gates:
- ownership boundary check passes
- smoke tests pass
- conformance tests pass

## Risks and Mitigations
1. Risk: Hidden legacy imports
- Mitigation: expand boundary checker and fail CI on regressions

2. Risk: Contract churn blocks teams
- Mitigation: freeze contract early; use `contract_version`

3. Risk: Provider-specific behavior differences
- Mitigation: conformance tests plus capability metadata

4. Risk: Runtime break on missing plugin
- Mitigation: startup validation with actionable error messages and fallback policy

## Acceptance Criteria (Program Complete)
1. App runtime contains no direct dependency on concrete memory/dream implementation modules.
2. Default submodule providers pass full conformance suite.
3. At least one alternate provider (or mock provider) runs through smoke tests.
4. Legacy shim files removed or disabled behind explicit deprecation flag.
5. Documentation fully describes plugin development, compatibility, and rollout.

## Current Progress Snapshot
1. Done
- Core memory implementation ownership moved into submodule package.
- Runtime import migration largely completed.
- Ownership checker and CI smoke gate added.
- Provider loader introduced for memory service paths.

2. In Progress
- Generalizing memory loader into full memory + dream provider registry.
- Defining explicit provider contracts and compatibility checks.

3. Next
- Implement conformance suite and plugin matrix.
- Complete dream-provider boundary and remove shim dependency.
