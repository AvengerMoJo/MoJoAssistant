# Agent Operating Rules (Global in This Repo)

These rules apply to all coding agents working in this repository.

## Source of Truth
- Primary policy document: `Coding Agents Rules.md`
- Agents should follow that file as the canonical rule set.

## Mandatory Memory Workflow
1. Use MoJoAssistant MCP memory context to inform decisions before major edits.
2. Persist important user/assistant exchanges and decisions to memory.
3. Use memory context to self-correct and improve response quality over time.

## Git Workflow
1. Start work from `main` by creating a branch named `wip_<feature>` (or `wip_<feature_name>`).
2. Keep implementation work on the `wip_<feature>` branch until fully tested.
3. Merge into `main` only when the user explicitly requests the merge.
4. All commits must be authored as the user, not as the agent.
5. The user is accountable for committed code shared with community/company.

## Scope
- This `AGENTS.md` governs all folders under this repository unless a deeper `AGENTS.md` overrides specific subtrees.
