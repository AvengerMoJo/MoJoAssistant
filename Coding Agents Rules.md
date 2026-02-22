# Coding Agents Rules

## Purpose
Leverage the internal memory context system (MoJoAssistant MCP) to continuously self-correct and improve, with effectively no practical memory limitation for context retention and recall.

## Core Rules
1. Understand the task before changing code.
2. Prefer small, reversible changes.
3. Keep behavior backward-compatible unless explicitly requested.
4. Do not modify unrelated files.
5. Do not remove existing user changes without approval.

## Code Quality
1. Follow existing project structure and naming conventions.
2. Add tests for new behavior and bug fixes when feasible.
3. Keep functions focused and readable.
4. Add concise comments only where logic is non-obvious.
5. Run relevant checks/tests before finishing.

## Safety
1. Avoid destructive commands unless explicitly requested.
2. Never expose secrets or credentials.
3. Validate inputs and handle errors clearly.
4. Prefer least-privilege operations.

## Collaboration
1. State assumptions when requirements are ambiguous.
2. Communicate planned edits before large changes.
3. Summarize what changed and why.
4. Flag risks, tradeoffs, and follow-up work.

## Git Practices
1. Always branch from `main` into `wip_<feature>` (or `wip_<feature_name>`) for active work.
2. Keep all in-progress changes in the `wip_<feature>` branch until fully tested.
3. Merge back to `main` only when explicitly requested by the user.
4. All git commits must be committed as the user (repository owner), not as the agent.
5. The user is the responsible code author for community/company submission and accountability.
6. Make atomic commits with descriptive messages.
7. Keep commit history clean and scoped.
8. Do not amend or force-push unless requested.

## Definition of Done
1. Code changes implemented.
2. Relevant tests/checks pass (or failures documented).
3. Documentation updated when needed.
4. Handoff summary includes files touched and next steps.
