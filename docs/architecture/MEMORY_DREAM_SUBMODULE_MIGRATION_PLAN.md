# Memory & Dream Submodule Migration Plan

## Goal
Move memory and dreaming core implementation ownership into `submodules/dreaming-memory-pipeline` so implementation can evolve independently, while app code remains a thin integration shell.

## Why Previous Approach Broke
- Core logic lived across both app and submodule, creating split ownership.
- Legacy import paths (`app.memory.*`, `app.services.memory_service`) stayed widely used, so drift continued.
- No CI guard enforced boundary rules, so regressions were easy to reintroduce.

## Target Ownership Contract
- Submodule owns core implementation:
  - `submodules/dreaming-memory-pipeline/src/mojo_memory/**`
  - submodule dreaming pipeline internals
- App owns integration surface only:
  - MCP handlers, scheduler adapters, role orchestration, runtime wiring.
- App memory/service files remain compatibility shims during transition.

## Execution Plan
1. Canonical import migration
- Replace runtime/test/script imports to `mojo_memory.*` where feasible.
- Keep app compatibility shims for backwards compatibility.

2. Path/bootstrap hardening
- Ensure `mojo_memory` imports work in local runs without requiring editable install.
- Keep CI explicit install of submodule package.

3. Ownership guardrails
- Add automated checker that fails when:
  - app shim files stop being shims.
  - new non-doc code uses legacy `app.memory` or old app memory service imports.
- Gate in CI smoke workflow.

4. Transition cleanup (follow-up)
- Update remaining docs/examples to canonical imports.
- Remove compatibility shims only after no runtime dependency remains.

## Acceptance Criteria
- Non-doc code no longer relies on legacy memory imports (except explicit allowlist).
- CI fails on ownership contract violations.
- Import smoke includes canonical `mojo_memory` modules.
- Existing app entry points continue to run.

## Current Status
- Phase 1 done: core memory/services moved to submodule + app shims added.
- Phase 2 done: major runtime/test/script import migration to canonical namespace.
- Phase 3 done: ownership checker + CI gate added.
- Phase 4 pending: broader doc/example normalization and eventual shim removal.
