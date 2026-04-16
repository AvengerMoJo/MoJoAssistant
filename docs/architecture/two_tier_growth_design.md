# Two-Tier Role Growth Design

**Author:** Alex Lau  
**Date:** 2026-04-16  
**Status:** Design — partially implemented, gaps documented below

---

## The Intent

Role growth in MoJoAssistant is designed as two distinct tiers:

| Tier | What it is | Example | Who benefits |
|------|-----------|---------|-------------|
| **Framework** | Patterns all agents can learn from — tool calling bugs, workflow failures, executor quirks | "Qwen outputs XML in FINAL_ANSWER instead of making tool calls" | Every role |
| **Personal** | Role-specific accumulated character, domain stance, writing style | "Anna knows the owner's voice and how he structures arguments" | That role only |

The chat interface (Claude Code or role_chat) → dreaming pipeline → role refinement loop is the intended growth mechanism. Not one-off fixes. Not individual patches per agent. A system that lets learning accumulate and propagate to the right tier automatically.

---

## What Currently Exists

### Memory Stores

Three stores exist today:

| Store | Path | Who writes | Who reads | Scoping |
|-------|------|-----------|----------|---------|
| User personal memory | `~/.memory/` | Claude Code auto-memory hooks, explicit `write_file` | `memory_search` (global) | User-owned, never agent-accessible |
| Role-private knowledge | Embedded in vector store, partitioned by `role_id` | `add_conversation`, `_reflect_to_memory` | `_orient_from_memory` (role-scoped search) | Isolated per role |
| ABCD dream archives | `~/.memory/dreams/sessions/`, `~/.memory/dreams/inbox/` | Dreaming pipeline | **Nobody** (see Gap 1) | Flat JSON, not indexed |

### The ABCD Consolidation Pipeline — Already Running

The dreaming pipeline runs **automatically**, not on-demand only. There are two automatic triggers:

**1. Session compaction** (`app/scheduler/core.py:751`):  
After every agentic task completes, the scheduler automatically queues a `TaskType.DREAMING` task. This runs `build_session_text(task_id)` → `process_conversation()` → A→B→C→D pipeline → archives at `~/.memory/dreams/sessions/session_{task_id}/`.

If the task's final answer is ≥500 chars, a second dreaming task runs `mode="document"` for atomic fact extraction into `~/.memory/dreams/` as well.

**2. Inbox distillation** (`app/scheduler/executor.py:271`):  
If a dreaming task has `distill_inbox=True`, yesterday's resolved HITL interactions (task_waiting_for_input + task_completed pairs from the EventLog) are serialized and fed through the dreaming pipeline → `~/.memory/dreams/inbox/inbox_YYYY-MM-DD/`.

**3. Direct reflection** (`agentic_executor.py:_reflect_to_memory`):  
After every successful task, a lightweight summary (tool sequence + outcome excerpt) is written directly to the role-private knowledge store via `add_to_knowledge_base(role_id=role_id)`. This one IS searchable — it's the actual orientation source for future tasks.

### The Orient → Reflect Loop (Searchable Path)

At task start: `_orient_from_memory(goal, role_id)` → `_search_knowledge_base_async(goal, role_id=role_id)` → injects top-6 hits as orientation block.

At task end: `_reflect_to_memory(goal, role_id, final_answer, iteration_log)` → `add_to_knowledge_base(document, metadata, role_id=role_id)`.

This loop works. Roles accumulate task reflections and retrieve them at future task start.

---

## The Gaps

### Gap 1 — ABCD Archives Are Orphaned (Critical)

The dreaming pipeline runs, produces rich B-chunks, C-clusters, and atomic knowledge units — and stores them as flat JSON archives in `~/.memory/dreams/`. But:

- `_orient_from_memory` searches the **vector knowledge base**, not the dream archives.
- The dream archives are never indexed back into the searchable store.
- The rich consolidated knowledge from the ABCD pipeline cannot be retrieved by any agent.

**Effect:** The automatic session compaction and inbox distillation produce output that nobody reads. The orientation agents actually receive comes from `_reflect_to_memory` only — a raw lightweight summary, not the ABCD-consolidated knowledge.

**Fix needed:** After `process_conversation()` completes, index the C-clusters (synthesized knowledge) and atomic knowledge units back into the vector knowledge base via `add_to_knowledge_base()`. This closes the loop: ABCD output → searchable → `_orient_from_memory` can retrieve it.

---

### Gap 2 — No Framework Knowledge Tier

Every `add_to_knowledge_base` call is either:
- Unscoped (legacy) — goes into shared store
- `role_id`-scoped — visible only to that role

There is no `role_id="__framework__"` sentinel or equivalent. Framework-level patterns have nowhere to land that all agents can later retrieve.

**Fix needed:**
- Add `scope` param to `add_conversation`: `"role"` (default) | `"framework"` (writes to sentinel `role_id="__framework__"`)
- In `_orient_from_memory`: after role-private search, always run a second search against `role_id="__framework__"` and merge — every agent sees framework patterns at task start
- In `_reflect_to_memory`: extract tool error patterns and workflow failures into the framework store (separate from the role-private task reflection)

---

### Gap 3 — No Scope Classifier

Nothing decides whether a piece of learning is framework-level or personal-level. The only distinction today is `role_id` (who owns it), not `scope` (who should see it).

**Fix needed (minimal):** Start with explicit agent tagging. An agent that encounters a Qwen XML bug calls `add_conversation(scope="framework", ...)`. No automated classifier needed in v1.

**Fix needed (future):** The dreaming pipeline's synthesizer could output cluster-level scope tags during the B→C stage. If a C-cluster's theme is "tool calling failure" or "workflow error", tag it as framework-scope and index it accordingly. This is the automated path that doesn't require agents to know what's framework vs personal.

---

### Gap 4 — No Chat → Framework Bridge

Claude Code auto-memory (`~/.memory/projects/.../*.md`) and the dreaming pipeline are disconnected. Conversations in the chat interface (like this one, where the Qwen XML bug was discovered) don't flow into framework knowledge automatically.

**Deferred — implement alongside the owner one-on-one interface.**

Gap 4 is the mechanism that makes the weekly owner one-on-one loop work:
- Owner has a one-on-one session with a role via the chat interface
- That conversation saves to memory
- Dreaming pipeline processes it and routes learnings to the right tier
- Role's posture shifts by next task

Without the one-on-one interface, there is nothing to bridge. These two features ship together:

1. **One-on-one interface** — role_chat or dashboard UI for owner ↔ role sessions
2. **Chat → dream bridge** — scheduled job that reads new chat entries, runs `process_document()`, and routes C-clusters by scope (framework → `__framework__` store, personal → role-private store)

The scope classifier from Gap 3 (explicit agent tagging) is sufficient for this — no automated classifier needed.

---

## What Needs to Be Built (Priority Order)

### Phase 1 — Close the ABCD → Searchable Loop (Gap 1)

**File:** `app/scheduler/executor.py` (dreaming task completion handler)  
After `pipeline.process_conversation()` succeeds, iterate over C-clusters and knowledge units from the archive and call `add_to_knowledge_base(content, metadata, role_id=role_id_from_metadata)` for each synthesized cluster.

This immediately makes the ABCD pipeline output useful. No new concepts — just wire the output into the existing searchable store.

### Phase 2 — Framework Knowledge Tier (Gap 2)

**Files:**
- `app/scheduler/capability_registry.py` — add `scope` param to `add_conversation`; if `scope="framework"` use `role_id="__framework__"`
- `app/scheduler/agentic_executor.py:_orient_from_memory` — add secondary search against `role_id="__framework__"`, merge with role-private results
- `app/scheduler/agentic_executor.py:_reflect_to_memory` — if iteration log contains tool errors or repeated failures, write an extracted pattern to `role_id="__framework__"` store
- `config/capability_catalog.json` — document the `scope` param

### Phase 3 — Chat → Framework Bridge (Gap 4)

**Design:** A new `TaskType.FRAMEWORK_DIGEST` or a cron-triggered dreaming task that ingests Claude Code auto-memory entries, runs `process_document()`, and routes the output by scope.  

Depends on the scope classifier (Gap 3). Hold until Phase 2 is validated.

---

## What Does Not Need to Be Built

- A scope classifier for Phase 1 and Phase 2 — explicit agent tagging is sufficient.
- Cross-role context sharing — roles never read each other's private knowledge. Framework knowledge is the only shared tier, and it's framework patterns, not role identity.
- A new memory service — the existing `add_to_knowledge_base(role_id=...)` infrastructure handles framework scope via the `__framework__` sentinel without new plumbing.
