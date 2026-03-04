## Agentic Scheduler — Autonomous LLM Task Engine

This release introduces a three-phase agentic scheduler that turns MoJoAssistant into an autonomous task execution platform. Background LLM agents can now pursue goals, use tools, persist their conversations, resume after failures, and automatically consolidate results into long-term memory.

### Highlights

**Autonomous Agent Loop** — Schedule a goal, and the system autonomously acquires LLM resources, reasons step-by-step, calls tools (memory search), and produces a final answer — all in the background.

**Persistent Session Memory** — Every agentic task records its full conversation trail to `~/.memory/task_sessions/`. Sessions are queryable in real-time (even while running) and resumable after timeout or failure.

**Resource Pool** — Tier-based LLM resource management (free → free_api → paid) with rate limiting, budget tracking, round-robin selection, and explicit approval for paid endpoints.

**Automatic Dreaming** — When an agentic task completes, a dreaming consolidation task is auto-scheduled to archive the conversation into long-term memory.

**Real-time SSE Notifications** — `GET /events/tasks` streams task lifecycle events (started, completed, failed) to any SSE client.

---

### New MCP Tools

| Tool | Description |
|------|-------------|
| `task_session_read` | Read full conversation trail for any agentic task (live or completed) |
| `scheduler_resume_task` | Resume a failed/timed-out agentic task from where it left off |
| `resource_pool_status` | View all LLM resources, their tiers, rate limits, and usage stats |
| `resource_pool_approve` | Approve a paid LLM resource for agentic use |
| `resource_pool_revoke` | Revoke approval for a paid resource |
| `config` | Generic config tool (replaces 3 rigid LLM tools) — help/get/set with dot-paths |

### New Files

| File | Purpose |
|------|---------|
| `app/scheduler/resource_pool.py` | LLM resource management with tier selection and budgets |
| `app/scheduler/agentic_executor.py` | Autonomous think-act loop with session logging |
| `app/scheduler/session_storage.py` | Per-task conversation trail persistence |
| `app/mcp/adapters/sse.py` | SSE notification fan-out via asyncio queues |
| `config/resource_pool_config.json` | Resource pool endpoint configuration |

### Changes since v1.1.4-beta

`14 commits, 72 files changed, 4254 insertions(+), 4138 deletions(-)`

### Quickstart

```bash
# Schedule an agentic task
scheduler_add_task(task_id="my_task", task_type="agentic", config={"goal": "Research X and summarize"})

# Watch it live
task_session_read(task_id="my_task")

# Stream events
curl -N http://localhost:8000/events/tasks

# Resume if it times out
scheduler_resume_task(task_id="my_task")
```
