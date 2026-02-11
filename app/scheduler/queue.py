"""
Task Queue Management

Handles persistent storage and retrieval of scheduled tasks.
Uses JSON for simplicity and debuggability.
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import threading

from app.scheduler.models import Task, TaskStatus, TaskPriority


class TaskQueue:
    """
    Persistent task queue with JSON storage

    Features:
    - Thread-safe operations
    - Priority-based retrieval
    - Automatic persistence
    - Task filtering and search
    """

    def __init__(self, storage_path: str = None):
        """
        Initialize task queue

        Args:
            storage_path: Path to JSON file for task storage
        """
        if storage_path is None:
            storage_path = os.path.expanduser("~/.memory/scheduler_tasks.json")

        self.storage_path = Path(storage_path)
        self.lock = threading.RLock()  # Reentrant lock for nested operations

        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing tasks
        self.tasks: Dict[str, Task] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        """Load tasks from JSON file"""
        if not self.storage_path.exists():
            self.tasks = {}
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            # Convert dict to Task objects
            self.tasks = {}
            for task_id, task_data in data.get('tasks', {}).items():
                try:
                    self.tasks[task_id] = Task.from_dict(task_data)
                except Exception as e:
                    print(f"Warning: Failed to load task {task_id}: {e}")

            print(f"Loaded {len(self.tasks)} tasks from {self.storage_path}")

        except Exception as e:
            print(f"Error loading tasks from {self.storage_path}: {e}")
            self.tasks = {}

    def _save_to_disk(self):
        """Save tasks to JSON file"""
        try:
            # Convert tasks to dict
            data = {
                'tasks': {
                    task_id: task.to_dict()
                    for task_id, task in self.tasks.items()
                },
                'metadata': {
                    'saved_at': datetime.now().isoformat(),
                    'total_tasks': len(self.tasks)
                }
            }

            # Write to temp file first, then rename (atomic operation)
            temp_path = self.storage_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic rename
            os.replace(temp_path, self.storage_path)

        except Exception as e:
            print(f"Error saving tasks to {self.storage_path}: {e}")
            raise

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
        limit: int = 100
    ) -> List[Task]:
        """
        List tasks with optional filtering

        Args:
            status: Filter by status
            priority: Filter by priority
            limit: Maximum number of tasks to return

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

            return tasks[:limit]

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

    def clear_completed(self, older_than_days: int = 7) -> int:
        """
        Remove completed tasks older than specified days

        Args:
            older_than_days: Remove tasks completed more than this many days ago

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
            ]

            for task_id in to_remove:
                del self.tasks[task_id]

            if to_remove:
                self._save_to_disk()

            return len(to_remove)
