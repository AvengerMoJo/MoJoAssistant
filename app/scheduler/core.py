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
                 sse_notifier=None):
        """
        Initialize scheduler

        Args:
            storage_path: Path to task queue JSON file
            tick_interval: Seconds between each tick (default: 60)
            max_concurrent: Maximum number of tasks running concurrently (default: 3)
            logger: Optional logger instance
            memory_service: Optional memory service for agentic tool use
            sse_notifier: Optional SSENotifier for real-time task events
        """
        self.queue = TaskQueue(storage_path)
        self.executor = TaskExecutor(logger=logger, memory_service=memory_service)
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
        self.stats["started_at"] = datetime.now()
        self._log(f"Scheduler started (max_concurrent={self.max_concurrent})")
        self._seed_tasks_from_config()

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

                # Sleep until next tick (in 1-second increments for responsiveness)
                remaining = self.tick_interval
                while remaining > 0 and self.running:
                    sleep_time = min(1, remaining)
                    await asyncio.sleep(sleep_time)
                    remaining -= sleep_time

            except Exception as e:
                self._log(f"Error in ticker loop: {e}", "error")
                # Continue running despite errors
                await asyncio.sleep(self.tick_interval)

    async def _execute_task_concurrent(self, task: Task):
        """Wrapper that acquires the semaphore before executing a task."""
        async with self._semaphore:
            await self._execute_task(task)

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
            })

            # Execute via executor
            result = await self.executor.execute(task)
            if result.success:
                task.mark_completed(result)
                self.stats["tasks_succeeded"] += 1
                self._log(f"Task {task.id} completed successfully")
                await self._broadcast({
                    "event_type": "task_completed",
                    "task_id": task.id,
                    "task_type": task.type.value,
                    "status": "completed",
                    "final_answer": (result.metrics or {}).get("final_answer"),
                    "session_file": (result.metrics or {}).get("session_file"),
                    "severity": "info",
                    "title": f"Task {task.id} completed",
                })

                # Auto-schedule dreaming for completed agentic tasks
                if task.type == TaskType.AGENTIC:
                    self._schedule_dreaming_for_agentic_task(task)

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
                    })

                    # Cron tasks reschedule even after permanent failure
                    if task.cron_expression:
                        from app.scheduler.triggers import CronTrigger
                        trigger = CronTrigger(task.cron_expression)
                        next_run = trigger.get_next_run_time(after=datetime.now())
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
            })

        finally:
            self.current_task = None

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

            dreaming_task = Task(
                id=dreaming_task_id,
                type=TaskType.DREAMING,
                priority=TaskPriority.LOW,
                config={
                    "conversation_id": f"agentic_{task.id}",
                    "conversation_text": conversation_text,
                    "quality_level": "basic",
                    "metadata": {
                        "source": "agentic_task",
                        "original_task_id": task.id,
                        "goal": goal,
                        "final_answer": final_answer[:500] if final_answer else None,
                        "message_count": iterations,
                    },
                },
                description=f"Dreaming consolidation for agentic task {task.id}",
                created_by="system",
            )

            if self.queue.add(dreaming_task):
                self._log(f"Scheduled dreaming task {dreaming_task_id} for agentic task {task.id}")
            else:
                self._log(f"Dreaming task {dreaming_task_id} already exists", "debug")

        except Exception as e:
            self._log(f"Failed to schedule dreaming for task {task.id}: {e}", "error")

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
