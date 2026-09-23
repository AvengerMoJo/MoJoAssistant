# Spec: agency-agents Persona Module Sync to Latest Role Development

**Date:** 2026-09-18
**Status:** Draft — for Paul (PM) to allocate an agent, or for the MoJoAssistant coding assistant to implement and raise a PR
**Priority:** Low — explicitly not the most important feature; schedule when an implementer is free
**Depends on:** `docs/architecture/MOJO_MODULE_SYSTEM.md`, `docs/architecture/MODULE_ARCHITECTURE_AUDIT.md`, `docs/specs/agent_workforce_dashboard_spec.md`
**Scope:** `submodules/agency-agents` (fork `github.com/AvengerMoJo/agency-agents`) + `app/roles/*` + conformance tests in MoJoAssistant

## Problem

The `agency_persona` module (submodule `submodules/agency-agents`, fork of msitarzewski/agency-agents) is out of step with the latest role development, and the direction of ownership is inverted. Verified 2026-09-18:

1. **Stale data contracts.** `module.json` declares `contract_version: 1.0` and data contracts `RoleDefinition@1.0` / `NineChapterScore@1.0`. The live RoleDefinition emitted today by the wizard (`app/roles/role_designer.py:378-391`) carries `archetype`, `agent_type` / `agent_type_label`, `capabilities` (unified from the legacy `tools` / `tool_access` fields in `app/roles/role_manager.py:_migrate_role`), `system_prompt`, `model_preference`, `session_id`. Every one of those fields post-dates the module's declared contract.

2. **Inverted ownership / dead package.** The fork ships `src/agency_agents/interface.py` as a PersonaModule interface package, but it is a re-export of *app* code (`from app.roles.persona_provider import AgencyPersonaModule as PersonaModule`). Per `MOJO_MODULE_SYSTEM.md` ("Interfaces are ours, adapters are generated"; "How personas are generated belongs to the module"), the app must consume the module, not the reverse. The module package today provides no real implementation.

3. **Latest role development lives in Core, not the module.** The Nine Chapter wizard (`role/design_start` → `design_answer` in `app/mcp/core/tools.py`, driven by `app/roles/role_designer.py`), the catalog parser (`app/roles/agency_agents_parser.py` — `parse_file`/`list_roles`/`search_roles`), the prefills bridge (`app/roles/agency_agents_bridge.py` — `build_prefills`/`prefills_to_session_answers`), and the import bridge (`app/roles/agency_importer.py` — hardcoded `submodules/agency-agents` path + `_TOOL_MAP` tool→capability mapping) all live in Core. That is exactly the module-design violation the audit tracks: Core carrying `How personas are generated` logic.

4. **Not upstream-syncable anyway.** The fork has no `msitarzewski` upstream remote (only `mojo`/`origin` → `AvengerMoJo/agency-agents`), so it is fully ours to restructure. Its durable asset is the catalog of ~276 markdown personas — that content stays untouched.

## Desired Outcome

- **fork → v1.1.0** ships a *real* `PersonaModule@1.1` implementation package: generation, catalog parsing, capability tool-map, and NineChapter overlays live **in** the module; `interface.py` exports the module's own code, not app re-exports.
- **MoJoAssistant consumes the module**: `app/roles/` keeps only thin adapters + the wizard HITL flow; no agency-agents-specific parsing remains in Core; submodule pointer bumped.
- **Contracts updated** to match the live schema: `RoleDefinition@2.0` (adds `archetype`, `agent_type`/`agent_type_label`, `capabilities`, `system_prompt`, `model_preference`; keeps `id`/`name`/`purpose`/`dimensions`/`nine_chapter_score`), `NineChapterScore@1.0` unchanged.
- **No behavioral regression**: the `design_start`/`design_answer` wizard, the catalog-import flow, `capabilities` migration, and all persona conformance + unit tests behave identically (or better documented) after the move.
- **Two PRs for the user to take**: one on `AvengerMoJo/agency-agents` (module v1.1.0), one on `AvengerMoJo/MoJoAssistant` (rewire + pointer bump).

## Non-Goals

- Syncing persona *content* from the upstream msitarzewski repo — no upstream remote exists; catalog updates are a separate task if ever wanted.
- Changing the wizard UX: `design_start`/`design_answer` steps, HITL synthesis, confirmed-create flow all stay as-is; only *where* the logic lives moves.
- Changing `RoleManager`'s stored schema or the `capabilities` unification behavior.
- Converting the 276 markdown personas to a new format — markdown remains the catalog source of truth.

## Design

### 1. Module restructure (fork repo `AvengerMoJo/agency-agents`, branch `wip_persona_module_v1_1`)

Move logic into `src/agency_agents/` as a proper package (an editable install or `src/` layout importable by the app):

- `persona_provider.py` — real `AgencyPersonaModule(PersonaProvider)` implementation, moved from `app/roles/persona_provider.py` (`generate`, `score`, `list_personas`, `health_check`, `get_version`). Keep `PROVIDER_NAME = "agency_persona"`, bump `PROVIDER_VERSION = "1.1.0"`, `CONTRACT_VERSION = "1.0"` (app-side contract version stays 1.0; module package version is 1.1.0).
- `catalog.py` — parsing moved from `app/roles/agency_agents_parser.py` + `app/roles/agency_importer.py`: `parse_file`, `list_roles`, `search_roles`, frontmatter/section extraction. The catalog path becomes a parameter (`defaults/` folder in-module), **no hardcoded MoJoAssistant path**; the app passes `submodules/agency-agents/` at call time.
- `bridge.py` — `build_prefills` / `prefills_to_session_answers` moved from `app/roles/agency_agents_bridge.py`, plus the behavioral-overlay builder currently in `src/agency_agents/ninechapter.py` (kept as the canonical overlay home).
- `scoring.py` — NineChapter `score()` internals + overlay generation, consolidated from `app/roles/persona_provider.py` and `src/agency_agents/ninechapter.py`.
- `toolmap.py` — `_TOOL_MAP` from `app/roles/agency_importer.py` (agency-agents tool names → capability categories) moved into the module.
- `interface.py` — stop re-exporting app code; export the module's real `PersonaModule`/`AgencyPersonaModule` + version constants.
- `module.json` — `version: 1.1.0`, `entry_point` → the packaged provider class, `data_contracts: {RoleDefinition: 2.0, NineChapterScore: 1.0}`.
- Keep all ~276 markdown persona files byte-identical.

### 2. App rewire (MoJoAssistant repo, branch `wip_persona_module_rewire`)

- `app/roles/persona_provider.py` — slim to a thin adapter (subclass or re-export of the module's `AgencyPersonaModule`), preserved only where the app's provider registry/discovery requires an in-app symbol.
- `app/roles/agency_agents_parser.py`, `agency_agents_bridge.py`, `agency_importer.py` — delete the agency-specific logic; route callers through the module package. Keep `role_designer.py`'s lazy one-line imports valid (import from module package instead of `app.roles.*`). Note: `role_designer.py` currently has **no** dangling `n_parser`/`n_bridge` references (verified — the rename was completed), so only the new import targets change.
- `tests/conformance/test_persona_provider_conformance.py` — update import source where it exercises the provider; tests must pass unchanged in behavior.
- `tests/unit/test_role_designer.py` — add/adjust a regression test covering: catalog import → prefills → wizard answers → `RoleManager.save` round-trip, and that generated RoleDefinitions include the post-1.0 fields (`archetype`, `capabilities`, `model_preference`, `system_prompt`).
- Bump the submodule pointer to the new fork commit.

## Acceptance Criteria

- [ ] Fork repo `AvengerMoJo/agency-agents` branch `wip_persona_module_v1_1` has `src/agency_agents/*` implementing generate/parse/bridge/score/toolmap as above; `interface.py` contains no import of `app.roles.*`.
- [ ] `module.json` reads `version 1.1.0`, `contract_version 1.0`, `entry_point` → packaged provider, `data_contracts RoleDefinition 2.0` + `NineChapterScore 1.0`.
- [ ] All ~276 persona markdown files byte-identical (no content drift from the move).
- [ ] MoJoAssistant branch `wip_persona_module_rewire`: `app/roles/` contains no orphaned agency-agents parsing logic; `role_designer.py` wizard imports resolve against the module package; submodule pointer bumped.
- [ ] `tests/conformance/test_persona_provider_conformance.py` passes (same behavior as before the move).
- [ ] `tests/unit/test_role_designer.py` passes, including the new catalog→wizard→RoleManager round-trip test and post-1.0-field assertions.
- [ ] Manual smoke: `role` hub `design_start` with `file_path=<submodule>/product/product-manager.md` pre-fills wizard answers and synthesizes a role with `capabilities`/`archetype` populated; `RoleManager.get` returns the stored role.
- [ ] Two open PRs created for the user to take (fork module PR + MoJoAssistant rewire PR). Commits authored as the user, per `AGENTS.md` git rules (no `Co-Authored-By` lines).

## Delivery

- **Where:** branch from `main` in each repo per `Coding Agents Rules.md` git practices: `wip_persona_module_v1_1` (fork) and `wip_persona_module_rewire` (MoJoAssistant). Implementer: Paul-allocated agent **or** the MoJoAssistant coding assistant — whichever is free; this feature is a good low-risk first exercise for a workforce/allocated agent since it is mechanical (move + bump + rewire) with a hard proof (conformance + unit tests + smoke).
- **PRs:** open both PRs back to `main` once acceptance criteria are met; the human reviews and merges (`take`s) them. Do not merge without explicit go.
- **BRIDLE:** every state-changing step validated before moving on (move → run conformance+tests → smoke → open PR); log progress in the PR description if a run is split across agents.