"""
Task Executor

Routes tasks to appropriate execution handlers based on task type.
"""

import asyncio
from typing import Optional
from datetime import datetime

from app.scheduler.models import Task, TaskType, TaskResult


class TaskExecutor:
    """
    Executes tasks by routing to appropriate handlers

    Supports:
    - Dreaming tasks (memory consolidation)
    - Scheduled tasks (user calendar events)
    - Agent tasks (OpenCode/OpenClaw)
    - Custom tasks (user-defined)
    """

    def __init__(self, logger=None):
        """
        Initialize executor

        Args:
            logger: Optional logger instance
        """
        self.logger = logger

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[Executor] {message}")

    async def execute(self, task: Task) -> TaskResult:
        """
        Execute a task

        Args:
            task: Task to execute

        Returns:
            TaskResult with success/failure and output
        """
        self._log(f"Executing task {task.id} of type {task.type.value}")

        try:
            # Route to appropriate handler
            if task.type == TaskType.DREAMING:
                result = await self._execute_dreaming(task)
            elif task.type == TaskType.SCHEDULED:
                result = await self._execute_scheduled(task)
            elif task.type == TaskType.AGENT:
                result = await self._execute_agent(task)
            elif task.type == TaskType.CUSTOM:
                result = await self._execute_custom(task)
            else:
                raise ValueError(f"Unknown task type: {task.type}")

            self._log(f"Task {task.id} execution result: {'success' if result.success else 'failed'}")
            return result

        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            return TaskResult(
                success=False,
                error_message=str(e)
            )

    async def _execute_dreaming(self, task: Task) -> TaskResult:
        """
        Execute dreaming task (memory consolidation)

        TODO: Implement full A→B→C→D pipeline
        For now, returns placeholder result
        """
        self._log(f"Dreaming task {task.id} - not yet implemented", "warning")

        # Simulate work
        await asyncio.sleep(1)

        return TaskResult(
            success=True,
            output_file=None,
            metrics={'placeholder': True},
            error_message=None
        )

    async def _execute_scheduled(self, task: Task) -> TaskResult:
        """
        Execute scheduled task (user calendar event)

        TODO: Implement task execution logic
        """
        self._log(f"Scheduled task {task.id} - not yet implemented", "warning")

        # Simulate work
        await asyncio.sleep(1)

        return TaskResult(
            success=True,
            output_file=None,
            metrics={'placeholder': True}
        )

    async def _execute_agent(self, task: Task) -> TaskResult:
        """
        Execute agent task (OpenCode/OpenClaw operation)

        TODO: Integrate with OpenCodeManager
        """
        self._log(f"Agent task {task.id} - not yet implemented", "warning")

        # Simulate work
        await asyncio.sleep(1)

        return TaskResult(
            success=True,
            output_file=None,
            metrics={'placeholder': True}
        )

    async def _execute_custom(self, task: Task) -> TaskResult:
        """
        Execute custom user-defined task

        Custom tasks should have a 'command' in their config
        """
        self._log(f"Custom task {task.id}")

        command = task.config.get('command')
        if not command:
            return TaskResult(
                success=False,
                error_message="Custom task missing 'command' in config"
            )

        try:
            # Execute shell command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return TaskResult(
                    success=True,
                    metrics={
                        'return_code': process.returncode,
                        'stdout_length': len(stdout)
                    }
                )
            else:
                return TaskResult(
                    success=False,
                    error_message=stderr.decode() if stderr else "Command failed"
                )

        except Exception as e:
            return TaskResult(
                success=False,
                error_message=f"Failed to execute command: {e}"
            )
