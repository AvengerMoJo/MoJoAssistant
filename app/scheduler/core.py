"""
Scheduler Core - The "Game Loop"

Persistent ticker that continuously checks for work and executes tasks.
"""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from app.scheduler.queue import TaskQueue
from app.scheduler.models import Task, TaskStatus, TaskType, Schedule, TaskPriority, TaskResources
from app.scheduler.executor import TaskExecutor


class Scheduler:
    """
    Core scheduler with persistent ticker loop

    Features:
    - Continuous background processing
    - Graceful shutdown
    - Error recovery
    - Performance monitoring
    """

    def __init__(self, storage_path: str = None, tick_interval: int = 60,
                 max_concurrent: int = 3, logger=None, memory_service=None,
                 sse_notifier=None, mcp_client_manager=None):
        """
        Initialize scheduler

        Args:
            storage_path: Path to task queue JSON file
            tick_interval: Seconds between each tick (default: 60)
            max_concurrent: Maximum number of tasks running concurrently (default: 3)
            logger: Optional logger instance
            memory_service: Optional memory service for agentic tool use
            sse_notifier: Optional SSENotifier for real-time task events
            mcp_client_manager: Shared MCPClientManager for tool dispatch + lifecycle mgmt
        """
        self.queue = TaskQueue(storage_path)
        self.memory_service = memory_service
        self.executor = TaskExecutor(logger=logger, memory_service=memory_service,
                                     mcp_client_manager=mcp_client_manager, scheduler=self)
        self.tick_interval = tick_interval
        self.max_concurrent = max_concurrent
        self.logger = logger
        self._sse_notifier = sse_notifier

        # State
        self.running = False
        self.current_task: Optional[Task] = None
        self._state_lock = asyncio.Lock()  # Thread-safe state access
        self.tick_count = 0

        # Concurrent execution
        self._semaphore: Optional[asyncio.Semaphore] = None  # Created in start()
        self._running_tasks: set = set()

        # Wake signal — set by wake() to interrupt the inter-tick sleep early
        self._wake_event: Optional[asyncio.Event] = None  # Created in start()
        self._scheduler_loop: Optional[asyncio.AbstractEventLoop] = None  # loop wake() uses

        # Statistics
        self.stats = {
            "started_at": None,
            "tasks_executed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "last_tick": None,
        }

        self._log("Scheduler initialized")

    def reseed_default_tasks(self) -> None:
        """Re-read scheduler_config.json and seed any new/enabled default tasks."""
        self._seed_tasks_from_config()

    def resume_task_with_reply(self, task_id: str, reply: str) -> Dict[str, Any]:
        """
        Resume a task that is in WAITING_FOR_INPUT state by injecting the user's reply.

        The executor will pick up reply_to_question from task.config on the next run,
        inject it into the message history, and continue the agentic loop.
        """
        task = self.queue.get(task_id)
        if task is None:
            return {"success": False, "error": f"Task '{task_id}' not found"}
        if task.status != TaskStatus.WAITING_FOR_INPUT:
            return {
                "success": False,
                "error": f"Task '{task_id}' is not waiting for input (status: {task.status.value})",
            }

        # External agent HITL stubs must NOT re-enter the scheduler execution loop.
        # Route their reply via ext_agent_reply so check_reply() can consume it,
        # and keep the task in RUNNING state (never PENDING).
        if task.config.get("ext_agent_hitl"):
            task.config["ext_agent_reply"] = reply
            task.pending_question = None
            task.status = TaskStatus.RUNNING
            self.queue.update(task)
            self._log(f"Task {task_id} (ext-agent HITL) received reply")
            return {"success": True, "task_id": task_id, "status": "running"}

        task.config["reply_to_question"] = reply
        task.pending_question = None
        task.status = TaskStatus.PENDING
        self.queue.update(task)
        self._log(f"Task {task_id} resumed with user reply")
        self.wake()  # Don't wait for the next tick — run now
        return {"success": True, "task_id": task_id, "status": "pending"}

    def wake(self) -> None:
        """
        Wake the scheduler immediately to process pending work.

        Safe to call from any context — sync or async, same thread or different.
        Uses call_soon_threadsafe when called from outside the scheduler's loop
        so the asyncio.Event.set() is dispatched on the correct loop.
        No-op if the scheduler has not started yet.
        """
        if self._wake_event is None or self._scheduler_loop is None:
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._scheduler_loop:
            # Already on the scheduler's loop — set directly
            self._wake_event.set()
        else:
            # Called from a different thread/loop — must use threadsafe dispatch
            self._scheduler_loop.call_soon_threadsafe(self._wake_event.set)

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[Scheduler] {message}")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] [Scheduler] {message}")

    async def start(self):
        """
        Start the scheduler ticker loop

        Runs continuously until stopped via stop() or signal
        """
        if self.running:
            self._log("Scheduler already running", "warning")
            return

        self.running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._wake_event = asyncio.Event()
        self._scheduler_loop = asyncio.get_event_loop()
        self.stats["started_at"] = datetime.now()
        self._log(f"Scheduler started (max_concurrent={self.max_concurrent})")
        self._seed_tasks_from_config()

        # Eagerly connect external MCP servers so agent(action="list/status")
        # shows live state immediately and tool discovery is ready for first task.
        asyncio.create_task(self._connect_mcp_servers())

        await self._broadcast({
            "event_type": "system_notification",
            "severity": "info",
            "title": "Scheduler started",
            "data": {"max_concurrent": self.max_concurrent, "version": "v1.1.9-beta"},
        })

        # Set up signal handlers for graceful shutdown (only in main thread)
        try:
            import threading

            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, self._signal_handler)
                signal.signal(signal.SIGTERM, self._signal_handler)
                self._log("Signal handlers registered (main thread)")
            else:
                self._log(
                    "Running in background thread, signal handlers skipped", "debug"
                )
        except ValueError:
            # Signal registration failed, continue without it
            self._log("Signal handlers not available in this context", "debug")

        try:
            await self._ticker_loop()
        except Exception as e:
            self._log(f"Fatal error in scheduler: {e}", "error")
            raise
        finally:
            await self._drain_running_tasks()
            self._log("Scheduler stopped")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self._log(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    async def _ticker_loop(self):
        """
        Main ticker loop - "game loop" for scheduler

        Each tick:
        1. Check for ready tasks (up to concurrency limit)
        2. Launch each as a concurrent asyncio.Task
        3. Update statistics
        4. Sleep until next tick
        """
        while self.running:
            try:
                self.tick_count += 1
                self.stats["last_tick"] = datetime.now()

                self._log(f"Tick #{self.tick_count} (running: {len(self._running_tasks)})", "debug")

                # Dispatch as many ready tasks as concurrency allows
                dispatched = 0
                while len(self._running_tasks) < self.max_concurrent:
                    task = self.queue.get_next()
                    if task is None:
                        break
                    # Mark as running immediately to prevent re-dispatch
                    task.mark_started()
                    self.queue.update(task)
                    self._log(f"Dispatching task: {task.id} ({task.type.value})")
                    t = asyncio.create_task(
                        self._execute_task_concurrent(task),
                        name=f"task-{task.id}",
                    )
                    self._running_tasks.add(t)
                    t.add_done_callback(self._running_tasks.discard)
                    dispatched += 1

                if dispatched == 0 and not self._running_tasks:
                    self._log("No tasks ready", "debug")

                # Periodic cleanup: remove completed tasks older than 7 days
                if self.tick_count % 100 == 0:
                    removed = self.queue.clear_completed(older_than_days=7)
                    if removed:
                        self._log(f"Cleaned up {removed} completed task(s) older than 7 days")

                # Fast cleanup: agentic-dreaming tasks are transient — remove after 1 day
                if self.tick_count % 10 == 0:
                    removed = self.queue.clear_completed(
                        older_than_days=1, task_types=[TaskType.DREAMING]
                    )
                    if removed:
                        self._log(f"Cleaned up {removed} completed dreaming task(s)")

                # Heartbeat every 10th tick
                if self.tick_count % 10 == 0:
                    from app.scheduler.models import TaskStatus as _TS
                    pending_count = sum(
                        1 for t in self.queue.list_tasks()
                        if t.status == _TS.PENDING
                    )
                    await self._broadcast({
                        "event_type": "scheduler_tick",
                        "tick": self.tick_count,
                        "running_count": len(self._running_tasks),
                        "pending_count": pending_count,
                        "severity": "info",
                        "title": f"Scheduler heartbeat (tick #{self.tick_count})",
                    })

                # Sleep until next tick — or wake early if new work arrives.
                # asyncio.wait_for returns immediately when _wake_event is set;
                # TimeoutError means the full tick_interval passed normally.
                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(), timeout=self.tick_interval
                    )
                    self._wake_event.clear()
                    self._log("Woken early — processing pending work", "debug")
                except asyncio.TimeoutError:
                    pass  # Normal tick interval elapsed

            except Exception as e:
                self._log(f"Error in ticker loop: {e}", "error")
                # Continue running despite errors
                await asyncio.sleep(self.tick_interval)

    async def _execute_task_concurrent(self, task: Task):
        """Wrapper that acquires the semaphore before executing a task."""
        async with self._semaphore:
            await self._execute_task(task)

    def _task_routing_fields(self, task: "Task") -> Dict[str, int]:
        """Return urgency/importance fields for broadcast events (omit when None)."""
        out = {}
        if task.urgency is not None:
            out["urgency"] = task.urgency
        if task.importance is not None:
            out["importance"] = task.importance
        return out

    async def _broadcast(self, event: dict):
        """Broadcast an SSE event if notifier is available."""
        if self._sse_notifier:
            try:
                await self._sse_notifier.broadcast(event)
            except Exception:
                pass  # non-critical

    async def _execute_task(self, task: Task):
        """
        Execute a single task

        Args:
            task: Task to execute
        """
        # current_task tracks the most recently started task (informational only)
        self.current_task = task
        self.stats["tasks_executed"] += 1

        try:
            # Task is already marked as RUNNING by the ticker loop
            self._log(f"Task {task.id} started")
            await self._broadcast({
                "event_type": "task_started",
                "task_id": task.id,
                "task_type": task.type.value,
                "severity": "info",
                "title": f"Task {task.id} started",
                **self._task_routing_fields(task),
            })

            # Execute via executor
            result = await self.executor.execute(task)

            # Agent paused — waiting for user input
            if result.waiting_for_input:
                task.status = TaskStatus.WAITING_FOR_INPUT
                task.pending_question = result.waiting_for_input
                task.config["resume_from_task_id"] = task.id
                self.queue.update(task)
                notify = self._should_notify_completion(task)
                await self._broadcast({
                    "event_type": "task_waiting_for_input",
                    "task_id": task.id,
                    "task_type": task.type.value,
                    "question": result.waiting_for_input,
                    "choices": result.waiting_for_input_choices,
                    "severity": "warning",
                    "title": f"Agent is waiting for your input on task {task.id}",
                    "notify_user": notify,
                    "data": {
                        "task_id": task.id,
                        "question": result.waiting_for_input,
                        "choices": result.waiting_for_input_choices,
                        "description": task.description,
                    },
                    **self._task_routing_fields(task),
                })
                self._log(f"Task {task.id} is waiting for user input")
                return

            if result.success:
                task.mark_completed(result)
                self.stats["tasks_succeeded"] += 1
                self._log(f"Task {task.id} completed successfully")
                final_answer = (result.metrics or {}).get("final_answer")
                is_assistant = task.type == TaskType.ASSISTANT
                notify = self._should_notify_completion(task)
                title = (
                    f"{task.description or task.id} completed"
                    if is_assistant
                    else f"Task {task.id} completed"
                )
                await self._broadcast({
                    "event_type": "task_completed",
                    "task_id": task.id,
                    "task_type": task.type.value,
                    "status": "completed",
                    "final_answer": final_answer,
                    "session_file": (result.metrics or {}).get("session_file"),
                    "severity": "info",
                    "title": title,
                    "notify_user": notify,
                    **self._task_routing_fields(task),
                })

                # Auto-schedule dreaming for completed assistant tasks
                if task.type == TaskType.ASSISTANT:
                    self._schedule_dreaming_for_agentic_task(task)
                    self._store_agentic_result_to_memory(task, result)

                # Check if recurring task needs rescheduling
                if task.cron_expression:
                    from app.scheduler.triggers import CronTrigger
                    trigger = CronTrigger(task.cron_expression)
                    next_run = trigger.get_next_run_time(after=datetime.now())
                    task.status = TaskStatus.PENDING
                    task.schedule = next_run
                    task.started_at = None
                    task.completed_at = None
                    self._log(f"Task {task.id} rescheduled for {next_run.isoformat()}")
                else:
                    self._log(f"Task {task.id} completed (non-recurring)")
            else:
                # Check if can retry
                if task.can_retry():
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING  # Re-queue for retry
                    self._log(
                        f"Task {task.id} failed, will retry ({task.retry_count}/{task.max_retries})"
                    )
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.now()
                    task.result = result
                    self.stats["tasks_failed"] += 1
                    self._log(f"Task {task.id} failed permanently", "error")
                    await self._broadcast({
                        "event_type": "task_failed",
                        "task_id": task.id,
                        "task_type": task.type.value,
                        "error": result.error_message or "Unknown error",
                        "severity": "error",
                        "title": f"Task {task.id} failed",
                        "notify_user": True,
                        **self._task_routing_fields(task),
                    })

                    # Cron tasks reschedule even after permanent failure
                    if task.cron_expression:
                        from app.scheduler.triggers import CronTrigger
                        trigger = CronTrigger(task.cron_expression)
                        next_run = trigger.get_next_run_time(after=datetime.now())
                        # Preserve error info before wiping result
                        task.last_error = result.error_message
                        task.last_failed_at = datetime.now()
                        task.status = TaskStatus.PENDING
                        task.schedule = next_run
                        task.retry_count = 0
                        task.started_at = None
                        task.completed_at = None
                        task.result = None
                        self._log(f"Task {task.id} failed but rescheduled (cron) for {next_run.isoformat()}")

            # Save updated task
            self.queue.update(task)

        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            task.mark_failed(str(e))
            self.stats["tasks_failed"] += 1
            self.queue.update(task)
            await self._broadcast({
                "event_type": "task_failed",
                "task_id": task.id,
                "task_type": task.type.value,
                "error": str(e),
                "severity": "error",
                "title": f"Task {task.id} failed",
                "notify_user": True,
                **self._task_routing_fields(task),
            })

        finally:
            self.current_task = None

    def _should_notify_completion(self, task: Task) -> bool:
        """
        Decide whether a task completion should push a notification to the user.

        Priority order:
        1. Explicit per-task override: task.config["notify_on_completion"] (True/False)
        2. Role default: role["notify_on_completion"] (True/False)
        3. Fallback: notify if the task was created by a human user (not system/cron)
        """
        # 1. Explicit task-level override
        cfg = task.config or {}
        if "notify_on_completion" in cfg:
            return bool(cfg["notify_on_completion"])

        # 2. Role default (for assistant tasks with a role_id)
        role_id = cfg.get("role_id")
        if role_id and task.type == TaskType.ASSISTANT:
            try:
                from app.roles.role_manager import RoleManager
                role = RoleManager().get(role_id)
                if role and "notify_on_completion" in role:
                    return bool(role["notify_on_completion"])
            except Exception:
                pass

        # 3. Fallback: user-initiated tasks get a notification; system/cron do not
        return task.created_by == "user"

    def _schedule_dreaming_for_agentic_task(self, task: Task):
        """
        After a successful agentic task, auto-create a dreaming task
        to consolidate the session into long-term memory.
        """
        try:
            from app.scheduler.session_storage import SessionStorage

            # Load the session file
            session_file = None
            if task.result and task.result.output_file:
                session_file = task.result.output_file
            if task.result and task.result.metrics:
                session_file = session_file or task.result.metrics.get("session_file")

            if not session_file:
                self._log(f"No session file for task {task.id}, skipping dreaming", "debug")
                return

            storage = SessionStorage()
            session = storage.load_session(task.id)
            if session is None:
                self._log(f"Could not load session for task {task.id}", "warning")
                return

            # Convert messages to conversation text
            lines = []
            for msg in session.messages:
                lines.append(f"[{msg.role}] {msg.content}")
            conversation_text = "\n".join(lines)

            if not conversation_text.strip():
                self._log(f"Empty session for task {task.id}, skipping dreaming", "debug")
                return

            # Get goal and final answer for metadata
            goal = (task.config or {}).get("goal", "")
            final_answer = session.final_answer or ""
            iterations = len(session.messages)

            dreaming_task_id = f"dreaming_agentic_{task.id}"

            # Use session_compactor for better serialization and structured storage
            try:
                from app.dreaming.session_compactor import build_session_text
                compacted_text = build_session_text(task.id)
                if compacted_text:
                    conversation_text = compacted_text
            except Exception:
                pass  # fall back to the naive serialization already in conversation_text

            dreaming_task = Task(
                id=dreaming_task_id,
                type=TaskType.DREAMING,
                priority=TaskPriority.LOW,
                config={
                    "conversation_id": f"sessions/session_{task.id}",
                    "conversation_text": conversation_text,
                    "quality_level": "basic",
                    "metadata": {
                        "source": "session_compaction",
                        "original_task_id": task.id,
                        "goal": goal,
                        "final_answer": final_answer[:500] if final_answer else None,
                        "message_count": iterations,
                    },
                },
                description=f"Session compaction for task {task.id}",
                created_by="system",
            )

            if self.queue.add(dreaming_task):
                self._log(f"Scheduled dreaming task {dreaming_task_id} for agentic task {task.id}")
            else:
                self._log(f"Dreaming task {dreaming_task_id} already exists", "debug")

            # Queue atomic fact extraction if the final answer is a substantial report
            MIN_REPORT_LENGTH = 500  # chars — skip trivial or empty outputs
            role_id = (task.config or {}).get("role_id", "unknown")
            if final_answer and len(final_answer) >= MIN_REPORT_LENGTH:
                doc_task_id = f"dreaming_doc_{task.id}"
                doc_task = Task(
                    id=doc_task_id,
                    type=TaskType.DREAMING,
                    priority=TaskPriority.LOW,
                    config={
                        "mode": "document",
                        "doc_id": f"reports/{role_id}/report_{task.id}",
                        "conversation_text": final_answer,
                        "quality_level": "basic",
                        "role_id": role_id,
                        "metadata": {
                            "source": "report_extraction",
                            "original_task_id": task.id,
                            "goal": goal,
                            "role_id": role_id,
                        },
                    },
                    description=f"Atomic fact extraction for task {task.id} report",
                    created_by="system",
                )
                if self.queue.add(doc_task):
                    self._log(f"Scheduled document dreaming task {doc_task_id} for task {task.id}")

        except Exception as e:
            self._log(f"Failed to schedule dreaming for task {task.id}: {e}", "error")

    def _store_agentic_result_to_memory(self, task: Task, result) -> None:
        """
        After a successful agentic task, write the goal + final answer to memory
        so the user (and future agents) can find it without reading the session file.
        """
        try:
            if not self.memory_service:
                return
            final_answer = (result.metrics or {}).get("final_answer", "")
            goal = (task.config or {}).get("goal", task.id)
            role_id = (task.config or {}).get("role_id")
            role_tag = f" (role: {role_id})" if role_id else ""

            user_message = f"Task{role_tag}: {goal}"
            assistant_message = final_answer or "(task completed — no final answer extracted)"

            self.memory_service.add_user_message(user_message)
            self.memory_service.add_assistant_message(assistant_message)
            self._log(f"Stored result of task {task.id} to memory")
        except Exception as e:
            self._log(f"Failed to store result to memory for task {task.id}: {e}", "error")

    async def _connect_mcp_servers(self):
        """Eagerly connect all configured external MCP servers at startup."""
        try:
            mgr = self.executor._mcp_client_manager
            if mgr and mgr.has_servers():
                tool_registry = self.executor._get_agentic_executor()._tool_registry
                # discover_and_register calls connect_all() internally — don't pre-call it
                # or the second connect_all() inside sees already-connected servers and
                # returns {} causing no tools to be registered.
                count = await mgr.discover_and_register(tool_registry)
                self._log(f"MCP startup: connected {list(mgr._sessions.keys())}, registered {count} tools")
        except Exception as e:
            self._log(f"MCP server startup connect failed (non-fatal): {e}", "warning")

    def _seed_tasks_from_config(self):
        """
        Seed default recurring tasks from config/scheduler_config.json.
        Tasks already in the queue are skipped; disabled tasks are ignored.
        """
        from app.config.config_loader import load_layered_json_config
        from app.scheduler.triggers import CronTrigger

        try:
            cfg = load_layered_json_config("config/scheduler_config.json")
        except Exception as e:
            self._log(f"Could not load scheduler_config.json: {e}", "warning")
            return

        priority_map = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
        }
        type_map = {t.value: t for t in TaskType}

        for entry in cfg.get("default_tasks", []):
            if not entry.get("enabled", True):
                continue

            task_id = entry.get("id")
            if not task_id:
                self._log("Skipping default_task with no id", "warning")
                continue

            if self.queue.get(task_id):
                continue  # already seeded

            task_type_str = entry.get("type", "")
            task_type = type_map.get(task_type_str)
            if task_type is None:
                self._log(f"Unknown task type '{task_type_str}' for {task_id}", "warning")
                continue

            cron = entry.get("cron")
            priority = priority_map.get(entry.get("priority", "low"), TaskPriority.LOW)
            resources_cfg = entry.get("resources", {})

            # Compute first run from cron expression
            first_run = None
            if cron:
                try:
                    trigger = CronTrigger(cron)
                    first_run = trigger.get_next_run_time(after=datetime.now())
                except Exception as e:
                    self._log(f"Invalid cron '{cron}' for {task_id}: {e}", "warning")

            task = Task(
                id=task_id,
                type=task_type,
                schedule=first_run,
                cron_expression=cron,
                priority=priority,
                config=entry.get("config", {}),
                resources=TaskResources(**resources_cfg) if resources_cfg else TaskResources(),
                description=entry.get("description", ""),
                created_by="system",
            )
            if self.queue.add(task):
                self._log(
                    f"Seeded default task {task_id}"
                    + (f" scheduled at {first_run.isoformat()}" if first_run else "")
                )

    async def _drain_running_tasks(self, timeout: float = 30.0):
        """Wait for all running tasks to finish, with timeout."""
        if not self._running_tasks:
            return
        self._log(f"Draining {len(self._running_tasks)} running task(s) (timeout={timeout}s)")
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._running_tasks, return_exceptions=True),
                timeout=timeout,
            )
            self._log("All running tasks drained")
        except asyncio.TimeoutError:
            self._log(f"{len(self._running_tasks)} task(s) still running after timeout", "warning")

    def stop(self):
        """Stop the scheduler gracefully"""
        self._log("Stop requested")
        self.running = False

    def add_task(self, task: Task) -> bool:
        """
        Add a new task to the queue

        Args:
            task: Task to add

        Returns:
            True if added successfully
        """
        success = self.queue.add(task)
        if success:
            self._log(f"Task added: {task.id} ({task.type.value})")
            self.wake()  # Don't wait for the next tick — run now
        else:
            self._log(f"Task already exists: {task.id}", "warning")
        return success

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.queue.get(task_id)

    def remove_task(self, task_id: str) -> bool:
        """Remove task by ID"""
        success = self.queue.remove(task_id)
        if success:
            self._log(f"Task removed: {task_id}")
        return success

    def list_tasks(self, **filters) -> list:
        """List tasks with optional filters"""
        return self.queue.list_tasks(**filters)

    def get_status(self) -> Dict[str, Any]:
        """
        Get scheduler status

        Returns:
            Dictionary with current state and statistics
        """
        queue_stats = self.queue.get_statistics()

        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "tick_interval": self.tick_interval,
            "max_concurrent": self.max_concurrent,
            "running_tasks": len(self._running_tasks),
            "current_task": {
                "id": self.current_task.id,
                "type": self.current_task.type.value,
                "started_at": self.current_task.started_at.isoformat()
                if self.current_task.started_at
                else None,
            }
            if self.current_task
            else None,
            "statistics": {
                **self.stats,
                "started_at": self.stats["started_at"].isoformat()
                if self.stats["started_at"]
                else None,
                "last_tick": self.stats["last_tick"].isoformat()
                if self.stats["last_tick"]
                else None,
            },
            "queue": queue_stats,
        }
