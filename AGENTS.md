# Agent Operating Rules (Global in This Repo)

These rules apply to all coding agents working in this repository.

## Source of Truth
- Primary policy document: `Coding Agents Rules.md`
- Agents should follow that file as the canonical rule set.

## Configuration and Data Hierarchy

MoJoAssistant follows a Linux-style layered config convention. Agents must respect this:

| What | Where | Rule |
|------|-------|------|
| System defaults, examples, templates | `project/config/` | Read-only at runtime. Never write here from running code. |
| Personal config overrides | `~/.memory/config/` | User's personal layer. Wins over project defaults. |
| All personal data and runtime state | `~/.memory/` | Conversations, knowledge, roles, task sessions, events — everything personal. |
| Secrets and environment | `.env` | Never commit. Never hardcode. |

**Simple rule for agents:** when in doubt, `~/.memory/` is home. Read personal state from there. Write personal state there. `project/config/` is factory defaults — read for fallback, never write at runtime.

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
6. Do NOT include `Co-Authored-By` lines in commit messages. The user is the sole author.

## BRIDLE Validation Workflow (Core Principle)

Every state-changing action must prove it worked before moving on:

```
Act → Validate → Log → Dream → Learn → Correct
```

Three failure modes to never repeat:
1. **Fail without log** — silent failure, same wall next run
2. **Log without learning** — dreaming never ingests it, mistake repeats
3. **Mistake without correction** — agent self-corrects silently, human never knows

Every state-changing MCP call: **PRE** (check preconditions) → **ACT** → **POST** (read back, verify, escalate on failure).

Incremental by design: process one unit per run, never batch blast. Track progress in a state file. Make the system move at the pace a human can absorb and correct.

Full policy in `Coding Agents Rules.md` § BRIDLE Validation Workflow. Full design doc at `~/.memory/research/bridle_validation_workflow.md`.

## Scope
- This `AGENTS.md` governs all folders under this repository unless a deeper `AGENTS.md` overrides specific subtrees.
