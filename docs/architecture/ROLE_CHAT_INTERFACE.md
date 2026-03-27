# Role Chat Interface — Direct Conversation with Assistants

**Status:** Planned — v1.2.7
**Design date:** 2026-03-26

---

## The Problem

When Rebecca finishes a research task, the result lands in the HITL inbox as a
final answer. To ask a follow-up question, the user has to:
1. Read the raw output
2. Queue a new task
3. Wait for the executor loop to run again

This is not how you talk to a researcher. You ask her "what did you find about
the Trivy attack?" and she tells you — from memory, with her personality, without
launching a new agentic session.

Today MoJo proxies everything: user → MoJo → scheduler → agent → MoJo → user.
That made sense for task dispatch. It doesn't make sense for conversation.

---

## The Core Distinction

There are two fundamentally different ways to interact with a role:

```
Task mode (existing)                 Chat mode (new)
────────────────────                 ──────────────
MoJo schedules a task                User talks directly
AgenticExecutor runs loops           Single LLM call per exchange
Full tool access                     Read-only: own memory silo only
Writes session log, memory           No writes to shared state
Can run 24/7 in background           Synchronous, foreground only
```

Chat mode is NOT a simplified agent. It is a separate interaction model.

---

## Key Design Constraint: No Task Acceptance

A role in chat mode **cannot** accept new tasks. This is not a policy preference
— it is an architectural requirement.

If chat mode could dispatch tasks, you would have:
- Rebecca receiving work from two directions: scheduler + user chat
- No coordination between the two sessions
- Memory writes from both sessions stomping each other
- No clear priority model (which wins — the scheduled task or the chat request?)
- The user unable to tell what state Rebecca is in

The dashboard analogy: the dashboard is a read-only window into the system.
It does not accept commands. Chat mode is a read-only conversational window
into an assistant. It does not accept tasks.

**If the user wants to assign new work during a chat, they route it through MoJo
(scheduler_add_task) as always. Chat is for reading what's already known.**

---

## What Chat Mode Is

When the user opens a chat session with Rebecca:

1. **Her personality loads** — the system prompt from `~/.memory/roles/rebecca.json`
   is active. She responds as Rebecca, not as a generic assistant.

2. **Her memory is context** — before the first exchange, her private memory silo
   is queried for relevant knowledge units (from finished research) and recent
   task history summaries. This context is prepended silently.

3. **She answers from accumulated knowledge** — Rebecca can explain her Trivy
   findings, connect ideas across multiple research sessions, clarify her
   reasoning — all from `~/.memory/roles/rebecca/knowledge_units/` and her
   lessons. She does not need to re-run the research.

4. **Session continuity** — conversation history is stored per-role so the chat
   can be picked up after a disconnect. Not a new session every time.

5. **Read-only tool policy** — the only tools available in chat mode:
   - `search_memory(role_id="self")` — search own knowledge units and lessons
   - `knowledge(action="get_file", ...)` — read from the knowledge base
   - Nothing else. No scheduler, no bash, no external writes.

---

## Session Model

```
~/.memory/roles/{role_id}/chat_history/
    {session_id}.json       ← conversation history for this session
    active_session          ← symlink or pointer to current session_id
```

A `session_id` is either:
- Provided by the client (for continuity across disconnects)
- Auto-generated as `chat_{role_id}_{timestamp}` for new sessions

The session file stores:
```json
{
  "session_id": "chat_rebecca_20260326_143012",
  "role_id": "rebecca",
  "started_at": "2026-03-26T14:30:12",
  "last_active": "2026-03-26T14:47:33",
  "exchanges": [
    {
      "user": "What did you find about the Trivy attack?",
      "assistant": "The Trivy supply chain attack...",
      "timestamp": "2026-03-26T14:30:18"
    }
  ]
}
```

---

## MCP Tool: `dialog`

```
dialog(role_id, message, session_id?)
```

Parameters:
- `role_id` — which assistant to talk to (must exist in `~/.memory/roles/`)
- `message` — the user's message
- `session_id` — optional; omit to start a new session, provide to continue

Returns:
```json
{
  "role_id": "rebecca",
  "session_id": "chat_rebecca_20260326_143012",
  "response": "The Trivy supply chain attack...",
  "context_used": {
    "knowledge_units": 4,
    "task_summaries": 2
  }
}
```

**What happens internally:**
1. Load role config → system prompt
2. Load recent knowledge units from `~/.memory/roles/{role_id}/knowledge_units/`
   relevant to the message (semantic search, top-K)
3. Load recent task summaries from `~/.memory/roles/{role_id}/task_history/`
4. Load session history if `session_id` provided
5. Build prompt: system prompt + memory context + conversation history + message
6. Single LLM call — NOT an agentic loop
7. Append exchange to session history
8. Return response

---

## Implementation Scope — v1.2.7

| Component | What |
|-----------|------|
| `app/scheduler/role_chat.py` | `RoleChatSession` class — loads role, builds context, makes LLM call, stores history |
| `app/mcp/core/tools.py` | Add `dialog` to tool surface |
| `~/.memory/roles/{role_id}/chat_history/` | Session storage directory (auto-created) |
| Dashboard `/dashboard` | "Chat" tab — list available roles, open chat window with SSE response streaming |

No new dependencies. Uses existing: role config loader, JsonFileBackend for KU search,
ResourceManager for LLM selection (same pool as agentic tasks, but a single call).

---

## v1.3.2 — Full Version

v1.2.7 ships the working core. v1.3.2 adds:

- **OpenAI-compatible proxy** — `/v1/models` returns available roles; `/v1/chat/completions`
  routes to the right role's chat session. Any LLM client (OpenWebUI, Cursor, etc.)
  can talk to Rebecca directly using the OpenAI API format.
- **Personality evolution** — post-dialog NineChapter dimension refinement via
  dream pipeline. Extended conversations update the role's dimension scores over time.
- **Explicit memory capture** — "remember: X" in a chat message writes to the
  role's private lesson store. The role learns from the conversation.
- **Cross-role referral** — Rebecca can say "Ahman would know more about this"
  and the client can open a handoff chat to Ahman with context carried over.

---

## Why Not Just Use the Agentic Executor?

The agentic executor is the wrong tool for this:

1. **Loop overhead** — the executor runs N iterations with tool calls. A simple
   question gets turned into a 3-iteration loop looking for tools that don't need to run.

2. **State conflict** — if Rebecca is already running a background task,
   launching another executor session for her role creates two concurrent sessions
   writing to her private memory simultaneously.

3. **Wrong interface contract** — the executor is designed to complete a goal
   autonomously. Chat is designed to answer a question collaboratively. Same role,
   completely different interaction model.

4. **No session continuity** — each agentic task starts fresh. Chat accumulates
   across exchanges, building shared context within the session.

The right model: chat is to the executor what a REPL is to a batch job.
Both run code, but for completely different purposes.
