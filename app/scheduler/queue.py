"""
Task Queue Management

Handles persistent storage and retrieval of scheduled tasks.
Uses JSON for simplicity and debuggability.
"""
# [hitl-orchestrator: generic]

import json
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import threading

from app.scheduler.models import Task, TaskStatus, TaskPriority
from app.config.paths import get_memory_subpath
from app.scheduler.log_util import emit


class QueueLoadError(RuntimeError):
    """The task queue file is unreadable and no valid backup exists. Starting with an empty
    queue would silently erase the whole schedule on the next save, so the scheduler refuses."""


class TaskQueue:
    """
    Persistent task queue with JSON storage

    Features:
    - Thread-safe operations
    - Priority-based retrieval
    - Automatic persistence
    - Task filtering and search
    """

    # Refresh the known-good backup after a save when it is older than this. A restore loses at most
    # this much schedule change; the copy is cheap (the file is ~1 MB).
    BACKUP_MAX_AGE_SECONDS = 300

    @property
    def backup_path(self) -> Path:
        return self.storage_path.with_name(self.storage_path.name + ".bak")

    def __init__(self, storage_path: str = None):
        """
        Initialize task queue

        Args:
            storage_path: Path to JSON file for task storage
        """
        if storage_path is None:
            storage_path = get_memory_subpath("scheduler_tasks.json")

        self.storage_path = Path(storage_path)
        self.lock = threading.RLock()  # Reentrant lock for nested operations

        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing tasks
        self.tasks: Dict[str, Task] = {}
        # Raw entries that failed to parse. Kept and re-written unchanged on every save, so one
        # bad entry (or a newer schema) can never be silently dropped from the file.
        self._unloadable: Dict[str, Any] = {}
        self._load_from_disk()

    def _read_queue_file(self, path: Path) -> Dict[str, Any]:
        with open(path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get('tasks'), dict):
            raise ValueError("queue file has no 'tasks' object")
        return data

    def _recover_from_corruption(self, error: Exception) -> Dict[str, Any]:
        """The queue file is unreadable. Quarantine it (never overwrite it), then restore the last
        known-good backup if one parses -- loudly. With no valid backup, refuse to start: an empty
        queue would be written over the damaged file and erase the schedule."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        quarantine = self.storage_path.with_name(f"{self.storage_path.name}.corrupt-{stamp}")
        os.replace(self.storage_path, quarantine)
        emit(None, "TaskQueue", f"{self.storage_path.name} is unreadable ({type(error).__name__}: {error}); "
                                f"quarantined as {quarantine.name}", "error")
        if self.backup_path.exists():
            try:
                data = self._read_queue_file(self.backup_path)
            except Exception as be:
                raise QueueLoadError(
                    f"{self.storage_path} was corrupt (quarantined as {quarantine.name}) and the backup "
                    f"{self.backup_path.name} is also unreadable: {be}") from error
            age_min = (time.time() - self.backup_path.stat().st_mtime) / 60
            shutil.copy2(self.backup_path, self.storage_path)
            emit(None, "TaskQueue", f"RESTORED the queue from {self.backup_path.name} "
                                    f"({len(data['tasks'])} tasks, backup is {age_min:.0f} min old); "
                                    "changes since then are lost", "error")
            return data
        raise QueueLoadError(
            f"{self.storage_path} was corrupt (quarantined as {quarantine.name}) and there is no backup. "
            "Refusing to start with an empty queue; restore the file by hand.") from error

    def _load_from_disk(self):
        """Load tasks from JSON file (see _recover_from_corruption for the unreadable-file policy)."""
        if not self.storage_path.exists():
            self.tasks = {}
            return

        try:
            data = self._read_queue_file(self.storage_path)
        except Exception as e:
            data = self._recover_from_corruption(e)

        self.tasks = {}
        self._unloadable = {}
        for task_id, task_data in data['tasks'].items():
            try:
                self.tasks[task_id] = Task.from_dict(task_data)
            except Exception as e:
                self._unloadable[task_id] = task_data
                emit(None, "TaskQueue", f"task {task_id} could not be loaded ({type(e).__name__}: {e}); "
                                        "kept unchanged in the file", "error")

        emit(None, "TaskQueue", f"Loaded {len(self.tasks)} tasks from {self.storage_path}"
                                + (f" ({len(self._unloadable)} unloadable kept as-is)" if self._unloadable else ""))

    def _save_to_disk(self):
        """Save tasks to JSON file"""
        try:
            # Convert tasks to dict
            data = {
                'tasks': {
                    **self._unloadable,
                    **{task_id: task.to_dict() for task_id, task in self.tasks.items()},
                },
                'metadata': {
                    'saved_at': datetime.now().isoformat(),
                    'total_tasks': len(self.tasks)
                }
            }

            # Write to temp file first, then rename (atomic operation)
            temp_path = self.storage_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            # Atomic rename
            os.replace(temp_path, self.storage_path)

            # Keep a recent known-good copy: the file just written is complete, so it is a safe
            # restore point for _recover_from_corruption.
            if (not self.backup_path.exists()
                    or time.time() - self.backup_path.stat().st_mtime > self.BACKUP_MAX_AGE_SECONDS):
                shutil.copy2(self.storage_path, self.backup_path)

        except Exception as e:
            import logging, traceback
            logging.getLogger(__name__).error(
                f"[TaskQueue] Failed to save tasks to {self.storage_path}: {e}\n{traceback.format_exc()}"
            )
            print(f"Error saving tasks to {self.storage_path}: {e}")

    def add(self, task: Task) -> bool:
        """
        Add a task to the queue

        Args:
            task: Task to add

        Returns:
            True if added successfully, False if task already exists
        """
        with self.lock:
            if task.id in self.tasks:
                return False

            self.tasks[task.id] = task
            self._save_to_disk()
            return True

    def get(self, task_id: str) -> Optional[Task]:
        """
        Get a specific task by ID

        Args:
            task_id: Task identifier

        Returns:
            Task if found, None otherwise
        """
        with self.lock:
            return self.tasks.get(task_id)

    def update(self, task: Task):
        """
        Update an existing task

        Args:
            task: Updated task object
        """
        with self.lock:
            if task.id not in self.tasks:
                raise ValueError(f"Task {task.id} not found")

            self.tasks[task.id] = task
            self._save_to_disk()

    def remove(self, task_id: str) -> bool:
        """
        Remove a task from the queue

        Args:
            task_id: Task identifier

        Returns:
            True if removed, False if not found
        """
        with self.lock:
            if task_id not in self.tasks:
                return False

            del self.tasks[task_id]
            self._save_to_disk()
            return True

    def get_next(self) -> Optional[Task]:
        """
        Get the next task to execute

        Priority order:
        1. Status: PENDING only
        2. Is due (schedule <= now)
        3. Priority (CRITICAL > HIGH > MEDIUM > LOW)
        4. Created time (FIFO within same priority)

        Returns:
            Next task to execute, or None if no tasks ready
        """
        with self.lock:
            # Filter pending tasks that are due
            ready_tasks = [
                task for task in self.tasks.values()
                if task.status == TaskStatus.PENDING and task.is_due()
            ]

            if not ready_tasks:
                return None

            # Sort by priority (CRITICAL first), then by created_at (FIFO)
            priority_order = {
                TaskPriority.CRITICAL: 0,
                TaskPriority.HIGH: 1,
                TaskPriority.MEDIUM: 2,
                TaskPriority.LOW: 3
            }

            ready_tasks.sort(
                key=lambda t: (priority_order[t.priority], t.created_at)
            )

            return ready_tasks[0]

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        limit: Optional[int] = None
    ) -> List[Task]:
        """
        List tasks with optional filtering

        Args:
            status: Filter by status
            priority: Filter by priority
            limit: Maximum number of tasks to return (None = no limit)

        Returns:
            List of tasks matching criteria
        """
        with self.lock:
            tasks = list(self.tasks.values())

            # Apply filters
            if status:
                tasks = [t for t in tasks if t.status == status]
            if priority:
                tasks = [t for t in tasks if t.priority == priority]

            # Sort by created_at (most recent first)
            tasks.sort(key=lambda t: t.created_at, reverse=True)

            return tasks if limit is None else tasks[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get queue statistics

        Returns:
            Dictionary with task counts by status and priority
        """
        with self.lock:
            stats = {
                'total': len(self.tasks),
                'by_status': {},
                'by_priority': {},
                'by_type': {}
            }

            for task in self.tasks.values():
                # Count by status
                status_key = task.status.value
                stats['by_status'][status_key] = stats['by_status'].get(status_key, 0) + 1

                # Count by priority
                priority_key = task.priority.value
                stats['by_priority'][priority_key] = stats['by_priority'].get(priority_key, 0) + 1

                # Count by type
                type_key = task.type.value
                stats['by_type'][type_key] = stats['by_type'].get(type_key, 0) + 1

            return stats

    def clear_completed(self, older_than_days: int = 7,
                        task_types: Optional[List] = None) -> int:
        """
        Remove completed tasks older than specified days

        Args:
            older_than_days: Remove tasks completed more than this many days ago
            task_types: If given, only remove tasks whose type is in this list

        Returns:
            Number of tasks removed
        """
        with self.lock:
            from datetime import timedelta
            cutoff = datetime.now() - timedelta(days=older_than_days)

            to_remove = [
                task_id for task_id, task in self.tasks.items()
                if task.status == TaskStatus.COMPLETED
                and task.completed_at
                and task.completed_at < cutoff
                and (task_types is None or task.type in task_types)
            ]

            for task_id in to_remove:
                del self.tasks[task_id]

            if to_remove:
                self._save_to_disk()

            return len(to_remove)
