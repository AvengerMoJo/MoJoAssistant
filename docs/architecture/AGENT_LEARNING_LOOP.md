# Agent Learning Loop — Self-Improving Agents Through Memory and Dreaming

**Status:** Planned — v1.3.x
**Design date:** 2026-03-26

---

## The Problem

When an agent fails or hits a wall, one of two things happens today:

1. The user reads the failure, diagnoses the cause, fixes the code or configuration,
   and re-queues the task.
2. The failure is forgotten. Same wall, same failure, next time.

Both outcomes put the human in the loop for problems the agent could learn to
handle itself. The goal is not zero human involvement — it's zero human involvement
for *known* failure patterns. The first time Researcher can't find MoJo's architecture
in search_memory, a human may need to notice. The second time, she should already
know.

---

## The Core Insight

**Memory + dreaming IS the learning mechanism.** You don't need code changes
when an agent fails — you need the failure to be properly processed through
memory and dreaming so the agent carries the lesson forward. The infrastructure
already exists. What's missing is closing the loop: failures write to memory,
dreaming processes failures into lessons, lessons inject into future task context.

---

## The Learning Loop (per agent)

```
1. TASK RUNS
   AgenticExecutor executes task with role R

2. FAILURE / INCOMPLETE EVENT
   Task ends with status: failed | completed_incomplete | blocked
   AgenticExecutor writes a structured failure record to role R's private memory:
   {
     "type": "task_lesson",
     "task_id": "...",
     "role_id": "researcher",
     "objective": "analyze MoJo memory architecture",
     "what_was_tried": ["search_memory(query='memory architecture')", "fetch_url(...)"],
     "what_failed": "search_memory returned no results for MoJo architecture docs",
     "root_cause": "architecture docs not ingested into knowledge base",
     "what_would_unblock": "ingest docs/architecture/ into knowledge base OR use direct file access",
     "suggested_alternatives": ["ask_user to ingest docs", "use bash_exec to read files directly"],
     "timestamp": "..."
   }

3. PRIVATE DREAM PASS (per role, nightly)
   Role R's dreaming pass reads its private memory including task_lesson records.
   It synthesizes lessons into durable knowledge units:
   {
     "type": "agent_lesson",
     "role_id": "researcher",
     "pattern": "MoJo architecture / internal codebase queries",
     "lesson": "search_memory does not contain MoJo's own architecture docs. For internal MoJo analysis, use direct file access via bash_exec or ask for knowledge base ingestion first.",
     "confidence": 0.9,
     "learned_from": ["rebecca_karpathy_mojo_memory_dream_001", "rebecca_study_mojo_memory_dream_tweet_001"],
     "last_reinforced": "..."
   }

4. MEMORY CONTEXT INJECTION (at task start)
   Before the agent's first iteration, AgenticExecutor queries role R's private memory
   for lessons relevant to the current task goal.
   Relevant lessons are prepended to the agent's context:
   "Memory note: In previous tasks involving MoJo internal analysis, search_memory
    did not contain architecture docs. Use direct file access or request ingestion first."

5. AGENT ACTS WITH ACCUMULATED KNOWLEDGE
   The agent doesn't repeat the same mistake. It either tries the alternative
   approach directly, or surfaces a better-informed blocker question to the user.
```

---

## Per-Agent Silo Memory

Each role has its own private memory store at `~/.memory/roles/{role_id}/`:

```
~/.memory/roles/researcher/
  lessons/          ← synthesized lesson knowledge units (from dream pass)
  task_history/     ← raw failure/success records per task
  capabilities/     ← what Researcher knows she can and cannot do
  preferences/      ← patterns Researcher has learned about the user's preferences

~/.memory/roles/analyst/
  lessons/
  ...

~/.memory/roles/coder/
  lessons/
  ...
```

Private memory is:
- **Written by** the agent's own executor (failure records) and dream pass (lessons)
- **Read by** the agent itself at task start (memory context injection)
- **Queryable by other agents** via `search_memory(role_id="researcher")` — cross-agent knowledge sharing

---

## Cross-Agent Memory Reference

Agents learn different things. Researcher learns research patterns. Analyst learns
system administration and file operations. Coder learns code review heuristics.
These learnings don't have to stay siloed.

**Read access:** Any agent can query another agent's lesson memory:
```
search_memory(query="git clone codebase access", role_id="analyst")
→ "Analyst's lesson: git clone works best with SSH keys configured at ~/.ssh/id_ed25519.
   For repos requiring auth, use gh auth login first."
```

**Write access:** Only the owning agent and the system write to a role's private memory.
Cross-agent writes require explicit handoff (sub-task completion → lesson transfer).

**Discovery:** A future `list_agent_capabilities()` tool lets any agent find which
other agent can help with a given problem:
```
list_agent_capabilities(need="file system access, git operations")
→ ["analyst: has bash_exec, git access, file read/write"]
```

---

## Sub-Agent Dispatch (future)

When an agent hits a wall it can't solve alone and its lesson memory says
"this requires another agent's capability", it should be able to dispatch a
sub-task without human relay:

```
Researcher hits wall: "need codebase access"
→ memory says: "Analyst has file/git capability"
→ Researcher dispatches: scheduler_add_task(role_id="analyst", goal="clone MoJoAssistant repo and summarize Memory + Dream module architecture")
→ Researcher waits on sub-task completion (or continues other work)
→ Analyst completes → writes result to shared handoff location
→ Researcher reads result → continues analysis
```

This requires `scheduler_add_task` as a dispatchable tool for assistant roles
(not just for humans via MCP). The agent becomes an orchestrator, not just an
executor.

**Guardrails:**
- Sub-tasks inherit parent task's data_boundary policy — a local_only task cannot
  dispatch a sub-task with external access
- Sub-task depth limited (default: 2 levels) to prevent runaway recursion
- Sub-task cost counted against parent task's resource budget
- All dispatched sub-tasks visible in EventLog with parent task linkage

---

## Failure Taxonomy

Not all failures are equal. The learning loop needs to distinguish:

| Failure Type | Example | Learning Response |
|-------------|---------|-------------------|
| Missing resource | MoJo docs not in KB | Lesson: check X before trying Y; suggest ingestion |
| Wrong tool for platform | fetch_url on X.com | Lesson: use Playwright for JS platforms |
| Missing permission | bash_exec blocked by policy | Lesson: this role doesn't have bash; request different role or ask user |
| Ambiguous goal | Task goal too vague to execute | Lesson: ask clarifying question earlier in iteration |
| External unavailability | API rate limit, service down | Lesson: retry after delay; not a permanent failure |
| Knowledge gap | Agent doesn't know enough about domain | Lesson: search memory first; flag knowledge gap for dreaming |

The executor tags each failure record with its taxonomy type. The dream pass
uses the taxonomy to generate appropriately-scoped lessons (platform-specific,
role-specific, or system-wide).

---

## What Changes in the Codebase

### AgenticExecutor
- On task incomplete/failed: write structured `task_lesson` record to
  `~/.memory/roles/{role_id}/task_history/{task_id}.json`
- On task start: query role private memory for relevant lessons; prepend to
  system context as "Memory notes"

### DreamingPipeline
- Add per-role dream pass: reads `task_history/` for the role, synthesizes
  `agent_lesson` records into `lessons/`
- Triggered after role's task completes (like current agentic dreaming) and
  nightly for accumulated history

### search_memory MCP tool
- Add `role_id` parameter (already present) that also searches role's private
  `lessons/` directory
- Add `search_agent_lessons(role_id, query)` — explicit cross-agent lesson query

### scheduler_add_task (future)
- Allow assistant roles to call this tool (currently human-only via MCP)
- Enforce data_boundary inheritance from parent task
- Add `parent_task_id` field for sub-task linkage

### New: `list_agent_capabilities()` tool (future)
- Returns a summary of each role's known capabilities derived from their lesson memory
- Enables agents to discover who can help without hardcoding role names

---

## Why This Matters

The current model requires a human to be the learning loop:
agent fails → human notices → human fixes code or config → agent tries again.

This works at small scale. It breaks when:
- Agents are running 24/7 on dozens of tasks simultaneously
- Failure patterns are subtle or accumulated over weeks
- The human is asleep, busy, or simply didn't notice the "Incomplete" buried in
  a final answer

The learning loop closes this. Common failure patterns get resolved by the agents
themselves. Genuinely novel failures — things no lesson covers — surface clearly
as escalations. The human's attention is spent on genuinely new problems, not
on repeatedly unblocking the same walls.

This is also what makes MoJo's memory architecture fundamentally different from
a simple RAG system. RAG retrieves. This loop *learns*. The difference is whether
the system gets better over time without human intervention. With this loop, it does.
