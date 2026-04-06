# Spec: Task Session Memory — v1.2.15

## Problem

Scheduled task sessions are ephemeral. When Carl studies OpenHarness, that work lives
only in `~/.memory/task_sessions/{task_id}.json`. The next time Carl gets an assignment
he starts fresh — no memory of what he did, what he found, or what the owner asked him.

Web UI conversations work correctly today (roles have `memory_search` + `knowledge_search`
mid-conversation). The gap is exclusively scheduled tasks.

## Mental Model

**A scheduled task IS a conversation between the owner and the agent:**

- `goal` = owner's assignment
- iteration_log (tool calls + responses) = agent's working process
- `final_answer` = agent's reply to the owner

This conversation should be persisted into the role's memory exactly like a web UI
conversation — so future tasks can recall what was asked and what was done.

## Desired Behaviour

After a task completes (success or failure with a final answer):

1. The full session is automatically fed into the dreaming pipeline for that `role_id`
2. The dreaming pipeline distills it into the role's knowledge base
3. Future tasks by the same role find it via `knowledge_search`
4. The owner can also find it via `memory_search` (global)

Carl doing an OpenHarness study → Carl remembers "I was asked to study OpenHarness,
here is what I found" → next OpenHarness task picks up where the last one left off.

## Implementation Plan

### 1. Session format adapter

Task sessions are structured differently from web UI conversations. The dreaming pipeline
needs a converter:

```python
# app/scheduler/session_to_conversation.py

def task_session_to_conversation(session: dict) -> str:
    """
    Convert a task session JSON into a conversation transcript
    suitable for the dreaming pipeline.

    Format:
      [OWNER] <goal>
      [AGENT] Iteration 1: <tool calls summary>
      [AGENT] Iteration 2: ...
      [AGENT] Final answer: <final_answer>
    """
```

The transcript should be readable as a conversation, not a raw JSON dump.
Tool call names + summaries are enough — full stdout/stderr can be omitted
to keep the input size manageable.

### 2. Auto-dream on completion

In `app/scheduler/core.py`, after a task transitions to `completed` or `failed`
(with a final answer), enqueue a dreaming job:

```python
async def _on_task_complete(self, task: Task):
    if not task.result or not task.config.get("role_id"):
        return
    role_id = task.config["role_id"]
    session_path = Path(task.result.get("output_file", ""))
    if not session_path.exists():
        return
    await self._enqueue_dream(role_id, task.id, session_path)
```

The dream job should run asynchronously — it must not block task completion
or push notifications.

### 3. Dream job

```python
async def _enqueue_dream(self, role_id: str, task_id: str, session_path: Path):
    """
    Load session, convert to transcript, feed to dreaming pipeline
    under the role's conversation namespace.
    """
    session = json.loads(session_path.read_text())
    transcript = task_session_to_conversation(session)
    conversation_id = f"task_{task_id}"

    pipeline = DreamingPipeline(
        llm=self._llm_interface,
        storage=role_scoped_storage(role_id),
    )
    await pipeline.process_conversation(
        conversation_id=conversation_id,
        conversation_text=transcript,
        metadata={
            "source": "task_session",
            "task_id": task_id,
            "role_id": role_id,
            "goal": session.get("config", {}).get("goal", ""),
            "completed_at": session.get("completed_at", ""),
        },
    )
```

### 4. Role-scoped storage

The dreaming pipeline already supports pluggable `StorageBackend`. Each role needs
its own namespace so `knowledge_search` stays role-scoped:

```
~/.memory/knowledge/{role_id}/
```

`role_scoped_storage(role_id)` returns a `JsonFileBackend` pointed at that path.
This is consistent with existing knowledge isolation design (see `project_assistant_knowledge_isolation.md`).

### 5. Failure sessions

Failed tasks with a partial final answer (auto-extracted) should also be dreamed —
the agent's partial work and the failure reason are valuable context.

Failed tasks with `final_answer: null` (runaway/timeout with no output) should be
**skipped** — there is nothing useful to distill.

## Scope Boundaries

- **Not in this spec:** dreaming web UI conversations (already works via `add_conversation`)
- **Not in this spec:** retroactive dreaming of existing task sessions (separate migration task)
- **Not in this spec:** cross-role memory sharing (owner uses `memory_search` for that)
- **Not in this spec:** dreaming pipeline changes — `process_conversation()` is sufficient as-is

## Success Criteria

1. Carl completes an OpenHarness study task → `knowledge_search` in a new Carl task
   returns a summary of the previous study
2. Owner asks Carl via web UI "what did you find about OpenHarness?" → Carl finds it
   via `knowledge_search`
3. Failed tasks with partial output are dreamed; pure-null tasks are not
4. Dreaming does not block task completion or push notifications

## Open Questions

- **LLM resource for dreaming:** dreaming is a local-only operation (free tier).
  Should it use the same resource as the task, or always route to a free local model?
  Recommendation: always free tier — dreaming quality does not need the best model.

- **Dream timing:** immediately on completion, or batched (e.g. nightly)?
  Recommendation: immediate, async — keeps memory fresh without adding latency to
  the task result.

- **Token budget for transcripts:** long tasks (25 iterations) produce large transcripts.
  Recommendation: cap transcript at ~8,000 tokens; summarise older iterations if needed.
