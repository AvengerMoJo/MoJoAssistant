# Scheduler Daemon Implementation

## Overview

The scheduler daemon is now **auto-starting** when the MCP service initializes, running continuously in the background to execute scheduled tasks.

## Architecture

### Auto-Start Behavior

Similar to how OpenCode Manager works, the scheduler daemon:

1. **Auto-starts** when `ToolRegistry` is initialized
2. **Runs in background thread** with its own asyncio event loop
3. **Persists tasks** to `~/.memory/scheduler_tasks.json`
4. **Executes tasks** based on schedule and priority
5. **Can be controlled** via MCP tools

### Implementation Details

**File: `app/mcp/core/tools.py`**
- Added `_start_scheduler_daemon()` - Starts daemon in background thread
- Added `_stop_scheduler_daemon()` - Stops daemon gracefully
- Added `_restart_scheduler_daemon()` - Restart daemon
- Daemon starts automatically in `__init__` via `self._start_scheduler_daemon()`

**File: `app/scheduler/core.py`**
- Modified `start()` to skip signal handlers in background threads
- Modified ticker loop to use interruptible sleep (1s intervals) for responsive shutdown
- Scheduler runs continuously checking for tasks every 60 seconds

## MCP Tools

### Task Management Tools (Existing)

1. **scheduler_add_task** - Add task to queue
2. **scheduler_list_tasks** - List all tasks (with filters)
3. **scheduler_get_status** - Get scheduler statistics
4. **scheduler_get_task** - Get specific task details
5. **scheduler_remove_task** - Remove pending task

### Daemon Control Tools (New)

6. **scheduler_daemon_status** - Check daemon health
   - Shows: running status, thread status, tick count, queue stats

7. **scheduler_start_daemon** - Manually start daemon
   - Use if daemon was stopped or failed

8. **scheduler_stop_daemon** - Stop daemon gracefully
   - Stops ticker loop, preserves queued tasks

9. **scheduler_restart_daemon** - Restart daemon
   - Stop + Start in one operation

## Usage Examples

### Via MCP Tools

```python
# The daemon starts automatically when MCP service initializes
# No manual start needed!

# Check daemon status
{
    "tool": "scheduler_daemon_status",
    "arguments": {}
}

# Add a task (daemon will execute it)
{
    "tool": "scheduler_add_task",
    "arguments": {
        "task_id": "daily_cleanup",
        "task_type": "custom",
        "priority": "medium",
        "cron_expression": "0 3 * * *",
        "config": {"command": "cleanup.sh"},
        "description": "Daily cleanup at 3 AM"
    }
}

# Stop daemon (if needed)
{
    "tool": "scheduler_stop_daemon",
    "arguments": {}
}

# Restart daemon
{
    "tool": "scheduler_restart_daemon",
    "arguments": {}
}
```

### Daemon Lifecycle

```
MCP Service Starts
        ↓
ToolRegistry.__init__()
        ↓
_start_scheduler_daemon()
        ↓
┌─────────────────────────┐
│   Background Thread     │
│  - New event loop       │
│  - scheduler.start()    │
│  - Ticker loop (60s)    │
└─────────────────────────┘
        ↓
┌─────────────────────────┐
│   Every 60 seconds:     │
│  1. Check for tasks     │
│  2. Execute if ready    │
│  3. Update status       │
│  4. Save to disk        │
└─────────────────────────┘
```

## Task Execution Flow

```
Task Added → Queue (JSON)
                ↓
        Ticker Loop Checks
                ↓
           Task Ready?
                ↓
        Execute via Executor
                ↓
        Update Status/Result
                ↓
        Save to Disk
```

## Key Features

✅ **Auto-start** - No manual intervention needed
✅ **Persistent** - Tasks survive restarts (JSON storage)
✅ **Priority-based** - CRITICAL > HIGH > MEDIUM > LOW
✅ **Scheduled** - Supports immediate, scheduled, and cron
✅ **Graceful shutdown** - Stops within 2 seconds
✅ **Thread-safe** - Reentrant locks for concurrent access
✅ **Error recovery** - Retry logic with configurable max attempts

## Testing

Run the included tests to verify functionality:

```bash
# Test basic scheduler functionality
python test_scheduler.py

# Test MCP integration (simple, no memory service required)
python test_scheduler_mcp_tools_simple.py

# Test daemon auto-start and lifecycle
python test_scheduler_daemon.py
```

## Task Persistence

Tasks are stored at: `~/.memory/scheduler_tasks.json`

```json
{
  "tasks": {
    "task_id": {
      "id": "task_id",
      "type": "custom",
      "status": "completed",
      "priority": "high",
      "config": {...},
      "result": {...},
      "created_at": "2026-02-12T14:37:28.015344"
    }
  },
  "metadata": {
    "saved_at": "2026-02-12T14:38:25.089242",
    "total_tasks": 1
  }
}
```

## Configuration

- **Tick Interval**: 60 seconds (configurable in `Scheduler.__init__`)
- **Storage Path**: `~/.memory/scheduler_tasks.json` (configurable)
- **Max Retries**: 3 (configurable per task)
- **Shutdown Timeout**: 5 seconds for graceful thread termination

## Troubleshooting

### Check if daemon is running
```python
await registry.execute("scheduler_daemon_status", {})
```

### Daemon not running
```python
# Manually start it
await registry.execute("scheduler_start_daemon", {})
```

### Tasks not executing
1. Check daemon status - ensure `running: true`
2. Check task schedule - may not be due yet
3. Check task status - may have failed (check error in result)
4. Check logs for errors

### Restart daemon
```python
await registry.execute("scheduler_restart_daemon", {})
```

## Next Steps (Future Phases)

- Phase 2: Implement real task executors (dreaming, scheduled, agent)
- Phase 3: Add task dependencies and workflows
- Phase 4: Add performance metrics and monitoring
- Phase 5: Add task priorities and resource management
