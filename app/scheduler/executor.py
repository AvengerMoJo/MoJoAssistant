"""
Task Executor

Routes tasks to appropriate execution handlers based on task type.
"""

import asyncio
from typing import Optional
from datetime import datetime
from pathlib import Path

from app.scheduler.models import Task, TaskType, TaskResult
from app.dreaming.pipeline import DreamingPipeline
from app.llm.llm_interface import LLMInterface


class TaskExecutor:
    """
    Executes tasks by routing to appropriate handlers

    Supports:
    - Dreaming tasks (memory consolidation)
    - Scheduled tasks (user calendar events)
    - Agent tasks (OpenCode/OpenClaw)
    - Custom tasks (user-defined)
    """

    def __init__(self, logger=None, llm_config_path: Optional[str] = None):
        """
        Initialize executor

        Args:
            logger: Optional logger instance
            llm_config_path: Path to LLM configuration file for dreaming
        """
        self.logger = logger
        self.llm_config_path = llm_config_path or "config/llm_config.json"
        self._dreaming_pipeline = None

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

    def _get_dreaming_pipeline(self, quality_level: str = "basic") -> DreamingPipeline:
        """Get or initialize dreaming pipeline"""
        if self._dreaming_pipeline is None:
            # Initialize LLM interface
            llm = LLMInterface(config_file=self.llm_config_path)

            # Set active interface for dreaming tasks
            if 'qwen-coder-small' in llm.interfaces:
                llm.set_active_interface('qwen-coder-small')

            # Create pipeline
            self._dreaming_pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level=quality_level,
                logger=self.logger
            )

        return self._dreaming_pipeline

    async def _execute_dreaming(self, task: Task) -> TaskResult:
        """
        Execute dreaming task (memory consolidation)

        Task config should contain:
        - conversation_id: Unique ID for the conversation
        - conversation_text: Raw conversation content
        - quality_level: Optional quality level (basic/good/premium)
        """
        self._log(f"Dreaming task {task.id} - processing conversation")

        try:
            # Extract configuration
            conversation_id = task.config.get('conversation_id')
            conversation_text = task.config.get('conversation_text')
            quality_level = task.config.get('quality_level', 'basic')

            if not conversation_id or not conversation_text:
                return TaskResult(
                    success=False,
                    error_message="Missing conversation_id or conversation_text in task config"
                )

            # Get pipeline
            pipeline = self._get_dreaming_pipeline(quality_level)

            # Process conversation through A→B→C→D pipeline
            results = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata=task.config.get('metadata', {})
            )

            if results.get('status') == 'success':
                return TaskResult(
                    success=True,
                    output_file=results['stages']['D_archive']['path'],
                    metrics={
                        'b_chunks_count': results['stages']['B_chunks']['count'],
                        'c_clusters_count': results['stages']['C_clusters']['count'],
                        'quality_level': quality_level,
                        'archive_path': results['stages']['D_archive']['path']
                    }
                )
            else:
                return TaskResult(
                    success=False,
                    error_message=results.get('error', 'Unknown error during dreaming')
                )

        except Exception as e:
            self._log(f"Dreaming task {task.id} failed: {e}", "error")
            return TaskResult(
                success=False,
                error_message=f"Dreaming execution error: {e}"
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
