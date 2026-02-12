# Scheduler Architecture for MoJoAssistant

## Overview

The Scheduler is a persistent "ticker" that processes tasks asynchronously, similar to how game engines work. It runs continuously, checking for work at each cycle.

## Core Components

### 1. Scheduler Core (The "Game Loop")

**Purpose:** Maintains the task queue and triggers execution.

**Responsibilities:**
- Persistent task storage (JSON)
- Time-based triggers (cron-like scheduling)
- Event-based triggers (user actions, git events)
- Task priority management
- Resource budgeting (tokens, concurrency)

**Data Structure (JSON format):**
```json
{
  "tasks": {
    "task_id_1": {
      "id": "dreaming_20250209_030000",
      "type": "dreaming",
      "schedule": "2025-02-09T03:00:00Z",
      "status": "pending|running|completed|failed",
      "priority": "high|medium|low",
      "resources": {
        "llm_provider": "local|openai|anthropic",
        "max_tokens": 10000
      },
      "result": {
        "output_file": ".memory/dreaming/output.json",
        "metrics": {},
        "created_at": "2025-02-09T03:15:00Z"
      }
    }
  }
}
```

### 2. Task Queue

**Purpose:** Holds tasks waiting to be executed.

**Operations:**
- `add(task)` - Add to queue
- `get_next()` - Get highest priority task
- `remove(task_id)` - Remove from queue
- `update_status(task_id, status)` - Update task state

### 3. Trigger Engine

**Time-Based Triggers:**
- Runs at specific times (e.g., "Every day at 3:00 AM")
- User-configurable schedules
- Similar to cron jobs

**Event-Based Triggers:**
- Memory threshold reached (4000 tokens)
- Git events (new commit, PR)
- User actions (manual trigger)
- Dreaming completion (auto-queue next run)

### 4. Task Dispatcher

**Purpose:** Routes tasks to appropriate executors.

**Task Types:**
1. **DreamingTask** - Memory consolidation (A→B→C→D pipeline)
2. **ScheduledTask** - User calendar events
3. **AgentTask** - Run OpenCode/OpenClaw operations

**Routing Logic:**
```python
if task.type == "dreaming":
    executor = DreamingExecutor()
elif task.type == "scheduled":
    executor = TaskExecutor()
elif task.type == "agent":
    if task.agent == "opencode":
        executor = OpenCodeManager()
    elif task.agent == "openclaw":
        executor = OpenClawManager()
```

### 5. Resource Manager

**Purpose:** Manages resource budgets and limits.

**Capabilities:**
- Token budgeting (per task and global)
- LLM provider routing (local → free API → paid API)
- Concurrency limits (max simultaneous tasks)
- Priority enforcement (critical tasks always run)

**Multi-Tier Routing:**
```
Background/Dreaming (Unlimited) → Free API (OpenRouter) → Paid API (OpenAI/Anthropic)
          (Local LLM)                    ↑                ↑
```

### 6. Execution Engine

**Purpose:** Executes tasks and tracks results.

**Executors:**
- `DreamingExecutor` - Runs A→B→C→D pipeline
- `TaskExecutor` - Runs user-defined tasks
- `AgentExecutor` - Manages AI agent operations

**Error Handling:**
- Automatic retry with exponential backoff
- Detailed logging of failures
- User notifications (MCP tools)
- State persistence (resume after crash)

## Integration Points

### Memory System
- Uses memory data as input for Dreaming
- Stores Dreaming results back into knowledge base
- Maintains version history (D pointers)

### AI Agents
- `OpenCodeManager` - Via MCP tools
- `OpenClawManager` - Via future integration
- Both can create/update tasks

### Git Operations
- Monitors repository for events
- Triggers tasks on commits
- Runs CI/CD pipelines as tasks

## File Structure

```
app/scheduler/
├── __init__.py
├── core.py                 # Scheduler core (ticker)
├── queue.py               # Task queue management
├── triggers.py            # Time and event triggers
├── dispatcher.py          # Task routing
├── resources.py           # Resource management
├── executor.py            # Task execution
├── dreaming.py            # Dreaming pipeline (A→B→C→D)
├── agents.py              # Agent integration
└── storage.py             # JSON storage with DuckDB queries
```

## API Interface

### CLI Commands
```bash
scheduler start              # Start scheduler daemon
scheduler stop               # Stop scheduler
scheduler status             # View running status
scheduler add <task>        # Add manual task
scheduler list              # List all tasks
scheduler remove <task_id>   # Remove task
scheduler config             # Configure settings
```

### MCP Tools
```python
scheduler_add_task(task_config)
scheduler_list_tasks()
scheduler_get_status(task_id)
scheduler_remove_task(task_id)
scheduler_configure(settings)
```

## Priority System

**Priority Levels:**
- `critical` - System tasks, must run immediately
- `high` - User-initiated, urgent
- `medium` - Scheduled maintenance
- `low` - Background, non-urgent

**Priority Rules:**
1. Critical tasks always run first
2. Within same priority, FIFO order
3. User tasks > System tasks (within same priority)
4. Dreaming uses its own priority logic

## Failure Handling

**Retry Strategy:**
- Immediate retry for transient errors (network)
- Exponential backoff (1s, 2s, 4s, 8s, 16s)
- Max 3 retries before marking failed
- Alert on final failure

**Failure Recovery:**
- Log detailed error information
- Update task status to "failed"
- Store error context in task result
- Create follow-up task if needed

## Concurrency

**Limits:**
- Max 2 dreaming tasks (to avoid overwhelming CPU)
- Max 3 concurrent agent tasks
- User tasks always run (no limit)
- Critical tasks bypass limits

## Resource Management

**Token Budgeting:**
```json
{
  "budgets": {
    "daily_dreaming": 100000,
    "background_tasks": 50000,
    "agent_tasks": {
      "opencode": 10000,
      "openclaw": 10000
    }
  },
  "usage": {
    "today_dreaming": 50000,
    "background_remaining": 15000,
    "agent_opencode": 2500
  }
}
```

**LLM Provider Routing:**
- Local model: Unlimited (but CPU-bound)
- Free API (OpenRouter): Daily budget limits
- Paid API (OpenAI/Anthropic): Pay-per-use

**Routing Decision Tree:**
```
Task Priority?
├─ Critical → Local model (fastest, free)
├─ High     → Free API (if budget available)
└─ Low      → Paid API (best quality)
```

## Configuration

### Storage Path
```env
SCHEDULER_DB_PATH=~/.memory/scheduler_tasks.json
DREAMING_OUTPUT_PATH=.memory/dreaming/
LOG_PATH=.memory/scheduler.log
```

### Runtime Configuration
```json
{
  "ticker_interval": 60,              # Check every 60 seconds
  "dreaming_schedule": "0 3 * * *",    # 3 AM daily
  "max_concurrent_tasks": 5,
  "enable_dreaming": true,
  "enable_scheduled_tasks": true,
  "enable_agent_tasks": true
}
```

## MCP Integration

**Server Tools:**
```python
{
  "name": "scheduler_add_task",
  "description": "Add a new task to scheduler",
  "inputSchema": { ... }
}
```

**Client (MCP Client):**
- Can query scheduler status
- Can add tasks via tools
- Receives notifications on task completion
- Integrates with MoJoAssistant memory

## Logging

**Log Levels:**
- `DEBUG` - Detailed execution trace
- `INFO` - Task lifecycle events
- `WARNING` - Resource limits, retry attempts
- `ERROR` - Task failures

**Log Format:**
```json
{
  "timestamp": "2025-02-09T03:00:00Z",
  "level": "INFO",
  "task_id": "dreaming_...",
  "event": "started",
  "details": { ... }
}
```

## Migration Path

**From v1.1.0 to v1.2.0:**
1. Install scheduler module
2. Import existing JSON task files
3. Configure triggers
4. Start scheduler daemon
5. Verify task execution

**Backward Compatibility:**
- Existing JSON storage format preserved
- CLI commands remain functional
- MCP tools work independently
- No breaking changes to memory system
