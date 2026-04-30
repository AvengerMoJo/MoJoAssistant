# Assistant Smoke Matrix (Contract-First)

Date: 2026-04-30

## Why

Smoke tests must validate operator outcomes, not just internal function behavior.

## Layer 1: Resource Pool Contracts

Validate what assistant execution can expect from user environment:
- provider availability/reachability
- model presence
- minimum context/output limits
- agentic capability flag + freshness

Baseline contract for "basic agentic tool-calling":
- enabled=true
- status=available
- model non-empty
- context_limit >= 8192
- output_limit >= 512

Notes:
- Thinking model is optional for baseline correctness.
- Vision is optional unless role/task requires vision tools.

## Layer 2: Role/Character Setup Contracts

Validate user-generated role setup before task execution:
- role_id resolves canonically
- role capability mapping resolves to concrete tools
- required tool family overlaps task need (e.g., shell: bash_exec/tmux)
- behavior rules are explicit (e.g., requires_tool_use, exhausts_tools_before_asking)

## Layer 3: Execution Contracts

Validate runtime behavior:
- at least one relevant tool attempt when capability exists
- no silent fallback on role/resource/precondition failures
- explicit failure message + debug surfaced to task list/dashboard
- final output contract respected (tagged final answer in agentic mode)

## Growth Path

1. Implement contract evaluators (done)
2. Wire into scheduler preflight checks
3. Expose contract report in task list/dashboard
4. Add role-generated dynamic smoke orchestration
5. Add per-module prompt patch recommendations based on observed failures

## Non-Goals

- Hardcoding role-specific behavior (e.g., Ahman-only route assertions)
- Coupling smoke pass to one exact model family
