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

    def __init__(self, storage_path: str = None, tick_interval: int = 60, logger=None):
        """
        Initialize scheduler

        Args:
            storage_path: Path to task queue JSON file
            tick_interval: Seconds between each tick (default: 60)
            logger: Optional logger instance
        """
        self.queue = TaskQueue(storage_path)
        self.executor = TaskExecutor(logger=logger)
        self.tick_interval = tick_interval
        self.logger = logger

        # State
        self.running = False
        self.current_task: Optional[Task] = None
        self._state_lock = asyncio.Lock()  # Thread-safe state access
        self.tick_count = 0

        # Statistics
        self.stats = {
            "started_at": None,
            "tasks_executed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "last_tick": None,
        }

        self._log("Scheduler initialized")

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
        self.stats["started_at"] = datetime.now()
        self._log("Scheduler started")
        self._ensure_default_dreaming_task()

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
            self._log("Scheduler stopped")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self._log(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    async def _ticker_loop(self):
        """
        Main ticker loop - "game loop" for scheduler

        Each tick:
        1. Check for next task
        2. Execute if found
        3. Update statistics
        4. Sleep until next tick
        """
        while self.running:
            try:
                self.tick_count += 1
                self.stats["last_tick"] = datetime.now()

                self._log(f"Tick #{self.tick_count}", "debug")

                # Get next task to execute
                task = self.queue.get_next()

                if task:
                    self._log(f"Executing task: {task.id} ({task.type.value})")
                    await self._execute_task(task)
                else:
                    self._log("No tasks ready", "debug")

                # Sleep until next tick (in 1-second increments for responsiveness)
                # This allows for quicker shutdown when stop() is called
                remaining = self.tick_interval
                while remaining > 0 and self.running:
                    sleep_time = min(1, remaining)
                    await asyncio.sleep(sleep_time)
                    remaining -= sleep_time

            except Exception as e:
                self._log(f"Error in ticker loop: {e}", "error")
                # Continue running despite errors
                await asyncio.sleep(self.tick_interval)

    async def _execute_task(self, task: Task):
        """
        Execute a single task

        Args:
            task: Task to execute
        """
        self.current_task = task
        self.stats["tasks_executed"] += 1

        try:
            # Mark task as running
            task.mark_started()
            self.queue.update(task)

            self._log(f"Task {task.id} started")

            # Execute via executor
            result = await self.executor.execute(task)
            if result.success:
                task.mark_completed(result)
                self.stats["tasks_succeeded"] += 1
                self._log(f"Task {task.id} completed successfully")

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
                    task.mark_failed(result.error_message or "Unknown error")
                    self.stats["tasks_failed"] += 1
                    self._log(f"Task {task.id} failed permanently", "error")

            # Save updated task
            self.queue.update(task)

        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            task.mark_failed(str(e))
            self.stats["tasks_failed"] += 1
            self.queue.update(task)

        finally:
            self.current_task = None

    def _ensure_default_dreaming_task(self):
        """
        Ensure there is a default recurring off-peak Dreaming task.
        This keeps Dreaming automation background-first without manual setup.
        """
        task_id = "dreaming_nightly_offpeak_default"
        if self.queue.get(task_id):
            return

        now = datetime.now()
        first_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if first_run <= now:
            from datetime import timedelta
            first_run = first_run + timedelta(days=1)

        task = Task(
            id=task_id,
            type=TaskType.DREAMING,
            schedule=first_run,
            cron_expression="0 3 * * *",
            priority=TaskPriority.LOW,
            config={
                "automatic": True,
                "quality_level": "basic",
                "off_peak_start": "01:00",
                "off_peak_end": "05:00",
                "enforce_off_peak": True,
                "lookback_messages": 200,
            },
            resources=TaskResources(requires_gpu=True),
            description="Automatic nightly Dreaming consolidation (off-peak)",
            created_by="system",
        )
        if self.queue.add(task):
            self._log(
                f"Created default Dreaming task {task_id} scheduled at {first_run.isoformat()}"
            )

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
