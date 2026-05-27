# Development Rules (AI-First, Community-Ready)

## Purpose
This document defines evergreen development rules to keep MoJo moving fast with AI-assisted execution while remaining easy for community contributors to join and extend.

## Core Principles
1. AI-first execution: every substantial feature must be runnable by an agent from a clear written spec.
2. Contract-first architecture: interfaces and data contracts are defined before implementation.
3. Human-governed autonomy: high-impact actions require explicit HITL approval.
4. Community-ready by default: changes must be discoverable, testable, and documented for external contributors.

## Contribution Lanes
1. Core Lane: contracts, registries, orchestration safety, policy boundaries.
2. Module Lane: memory, dream, persona, growth, skills, plugin capabilities.
3. Integration Lane: external adapters, connectors, and runtime bridges.
4. Community Lane: docs, templates, starter packs, and onboarding workflows.

## Mandatory Artifacts Per Feature/PR
1. Spec: problem, scope, dependencies, risks, done criteria.
2. Interface: ABC/schema/state transitions and compatibility notes.
3. Tests: conformance + smoke + regression for changed behavior.
4. Operations: config examples, rollout plan, rollback plan.
5. Docs: usage guide and extension guide.

## AI Agent Working Rules
1. Plan before code: identify ownership boundaries and parallelizable slices.
2. Contract before implementation: define interface and acceptance checks first.
3. No hidden behavior: policy and approval logic must be explicit in code and docs.
4. Rejection learning loop: rejected recommendations must produce RCA and corrective updates.
5. Standard handoff format: files changed, tests run, blockers, follow-up tasks.

## Plugin and Skill Standards
1. Module/plugin packages must include `module.json` with provider type, entry point, and contract version.
2. Plugins must pass SDK validation and relevant conformance tests before merge.
3. Skills must include blueprint schema, install path, and test path.
4. At least one working sample must exist for each newly introduced extension pattern.

## Quality Gates (Merge Requirements)
1. Full conformance suite for affected contracts.
2. Smoke suite for startup/import/runtime integrity.
3. Boundary/ownership checks for modularization rules.
4. Documentation consistency checks (status tables must match detailed sections).
5. Safety/policy checks for high-risk flows.

## Change Governance
1. No silent TODOs: unfinished scope must be tracked in the module TODO with owner and status.
2. No contract drift: breaking contract changes require migration notes and compatibility updates.
3. No undocumented runtime flags: every env/config switch must be documented.
4. No bypass of HITL gates for actions classified as medium/high risk.

## Community Onboarding Requirements
1. "Start contributing quickly" guide with required setup and validation commands.
2. Reusable role prompts for coordinator, module implementer, and QA reviewer.
3. Sample plugin and sample skill that can be scaffolded, validated, and tested end-to-end.
4. Troubleshooting section for common setup, validation, and integration failures.

## Recommended Validation Command Set
1. `python3 scripts/check_memory_dream_ownership.py`
2. `python3 -m pytest tests/conformance -q`
3. `python3 -m pytest tests/smoke -q`

## Definition of Done (Feature Level)
A feature is done only when:
1. Contract and implementation are aligned.
2. Required tests pass.
3. Docs are updated.
4. Rollout/rollback instructions exist.
5. A new contributor can reproduce and validate the feature from docs.
