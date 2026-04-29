# Chat → Dream Bridge: Design Proposal

**Status:** Proposal — awaiting review  
**Date:** 2026-04-28  
**Relates to:** `two_tier_growth_design.md` Gap 4, `ROLE_CHAT_INTERFACE.md`

---

## Where We Are

The two-tier growth architecture is mostly working:

| Component | Status |
|-----------|--------|
| `role_chat.py` + `dialog` MCP tool | Done — one-on-one chat with roles, sessions persist at `~/.memory/roles/{role_id}/chat_history/` |
| `DreamingPipeline.process_conversation()` | Done — A→B→C→D for raw conversation text |
| `DreamingPipeline.process_document()` | Done — atomic fact extraction → D for research outputs |
| `DreamingHandler` role-scoped storage | Done — routes to `~/.memory/roles/{role_id}/knowledge_units/` when `role_id` set |
| `_index_clusters_to_knowledge_base()` | Done — C/D output indexed into searchable vector store |
| Framework tier (`__framework__` sentinel) | Done — all agents see shared patterns at task start |
| Gap 4: chat_history → dreaming pipeline | **Missing** |

The one-on-one conversations exist. The dreaming pipeline exists. There is no wire between them.

---

## The Missing Wire

When you have a one-on-one session with Rebecca, the exchange is saved to:

```
~/.memory/roles/rebecca/chat_history/chat_rebecca_20260428_143012.json
```

That session is never read again by anything. Rebecca's next task starts with no memory of the conversation.

The bridge is: **new chat sessions → dreaming pipeline → indexed into Rebecca's knowledge base**.

---

## What Needs to Be Built

### 1. Pipeline Upgrade: `process_chat_session()` in DreamingPipeline

The existing `process_conversation()` takes raw text. Chat sessions are structured JSON (see `ROLE_CHAT_INTERFACE.md`):

```json
{
  "session_id": "chat_rebecca_20260428_143012",
  "role_id": "rebecca",
  "exchanges": [
    { "user": "...", "assistant": "...", "timestamp": "..." }
  ]
}
```

A new entry point is needed that understands this format:

```python
async def process_chat_session(
    self,
    session_data: dict,           # parsed chat_history JSON
    role_id: str,
    metadata: Optional[dict] = None,
) -> dict:
```

**What it does differently from `process_conversation()`:**

- **Strips noise** — tool call traces, system messages, and empty exchanges are removed before chunking. Only the actual user ↔ role dialogue enters the pipeline.
- **Preserves corrections** — exchanges where the user corrects or redirects the role (signal: short user message following a long assistant response) are tagged as high-value B-chunks. These carry more weight in synthesis.
- **Scope tagging at C-cluster time** — the synthesizer is given a hint that the source is a personal one-on-one session. C-clusters that are about the role's *personality, preferences, or owner relationship* are tagged `scope: personal`. C-clusters about *tool patterns, workflow failures, or architectural knowledge* are tagged `scope: framework`.
- **Routes by scope** — personal clusters → role-private knowledge store. Framework clusters → `__framework__` store. Same infrastructure, new routing signal.

This is a submodule change (`submodules/dreaming-memory-pipeline`).

---

### 2. Bridge Scheduled Job

A new scheduled job (cron, nightly) that:

1. For each role in `~/.memory/roles/`:
   - Reads `~/.memory/roles/{role_id}/chat_history/` for session files
   - Checks a watermark file `~/.memory/roles/{role_id}/chat_dream_watermark.json` (tracks last processed session timestamp)
   - Skips sessions older than watermark
2. For each new session:
   - Calls `pipeline.process_chat_session(session_data, role_id)`
   - Routes output to role-private store (and framework store for framework-tagged clusters)
3. Updates the watermark

**Watermark format:**
```json
{
  "last_processed_at": "2026-04-28T02:15:00",
  "processed_session_ids": ["chat_rebecca_20260428_143012"]
}
```

This job fits naturally as a `TaskType.DREAMING` variant with `mode: "chat_bridge"` in the `DreamingHandler`. No new TaskType needed.

---

### 3. One-on-One Interface: What Still Needs Work

`dialog` MCP tool and `role_chat.py` are working. The gaps are:

| Gap | Status | Needed? |
|-----|--------|---------|
| Dashboard "Chat" tab | Not built | Nice to have for v1.3 |
| Streaming responses | Not checked | High priority if chat feels slow |
| Session list / history navigation | `list_chat_sessions()` exists | Wire to MCP or dashboard |
| "Remember: X" explicit capture | Not built | v1.3.2 per design doc |
| Post-session dream trigger (on-demand) | Not built | Could skip if nightly bridge is fast enough |

The bridge is useful even without the dashboard — `dialog` via MCP already works from Claude Code.

---

## Upgrade Decision: Where Does `process_chat_session` Live?

**Option A — In the submodule (dreaming-memory-pipeline)**

Pro: keeps all pipeline logic together, submodule is the right layer for ingestion paths.  
Con: requires a submodule commit + main repo update.

**Option B — In `DreamingHandler` as a pre-processing step (convert chat → text, then call `process_conversation()`)**

Pro: no submodule change needed. Handler serializes the JSON into readable text before passing to `process_conversation()`.  
Con: loses the structured signal (corrections, scope tagging). The synthesizer sees flat text instead of annotated chunks.

**Recommendation: Option A** — the scope tagging (personal vs framework routing) is the key value of this bridge. If we flatten to text first, we lose exactly the part that makes one-on-one sessions different from regular task sessions.

---

## Scope Tagging: How the Synthesizer Decides

The synthesizer (`DreamingSynthesizer`) gets a new optional `source_type` hint when called from `process_chat_session()`. The prompt changes:

**Current synthesizer prompt (paraphrase):**
> "Group these chunks into thematic clusters. Label each cluster type."

**Chat-session synthesizer prompt addition:**
> "Source: one-on-one owner ↔ role conversation.
> For each cluster, add a `scope` field:
> - `personal` — the owner's preferences, the role's relationship with the owner, personality notes
> - `framework` — tool patterns, workflow errors, system behavior, knowledge that any role would benefit from"

This is a prompt-only change in the synthesizer — no new model, no new logic.

---

## Implementation Order

```
Phase 1 (submodule)
  dreaming-memory-pipeline:
    synthesizer.py   — add source_type hint + scope field in C-cluster output
    pipeline.py      — add process_chat_session() entry point

Phase 2 (main repo)
  app/scheduler/handlers/dreaming.py  — add mode="chat_bridge", chat session loader,
                                        watermark read/write, scope-based routing
  app/scheduler/core.py (or cron)     — register nightly chat_bridge task per role

Phase 3 (optional, v1.3)
  Dashboard chat tab
  Streaming for dialog tool
  "Remember: X" explicit capture
```

---

## Open Questions for Review

1. **Scope tagging via LLM prompt** — is the synthesizer reliable enough for personal vs framework routing, or should the bridge default everything to personal and only tag framework explicitly when the user says so (e.g., "note for all roles: ...")?

2. **Nightly vs on-demand bridge** — should the bridge run nightly (batch) or immediately after a chat session ends (real-time)? Real-time is more responsive but adds latency to every chat exchange.

3. **Session minimum length** — chat sessions shorter than N exchanges (e.g., 3 turns) may not produce meaningful clusters. Should the bridge skip short sessions, or process them anyway at lower quality?

4. **Dream quality level** — one-on-one sessions are personal growth material. Should they always run at `premium` quality (more detailed synthesis) vs the nightly task dreaming which runs at `basic`?
