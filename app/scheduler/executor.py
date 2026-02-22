"""
Task Executor

Routes tasks to appropriate execution handlers based on task type.
"""

import asyncio
import json
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

            self._log(
                f"Task {task.id} execution result: {'success' if result.success else 'failed'}"
            )
            return result

        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    def _get_dreaming_pipeline(self, quality_level: str = "basic") -> DreamingPipeline:
        """Get or initialize dreaming pipeline"""
        if self._dreaming_pipeline is None:
            # Initialize LLM interface
            llm = LLMInterface(config_file=self.llm_config_path)

            # Create pipeline
            self._dreaming_pipeline = DreamingPipeline(
                llm_interface=llm, quality_level=quality_level, logger=self.logger
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
            conversation_id = task.config.get("conversation_id")
            conversation_text = task.config.get("conversation_text")
            quality_level = task.config.get("quality_level", "basic")
            automatic = bool(task.config.get("automatic", False))
            enforce_off_peak = bool(task.config.get("enforce_off_peak", automatic))
            off_peak_start = task.config.get("off_peak_start", "01:00")
            off_peak_end = task.config.get("off_peak_end", "05:00")

            if enforce_off_peak and not self._is_within_off_peak(
                off_peak_start, off_peak_end
            ):
                return TaskResult(
                    success=True,
                    metrics={
                        "skipped": True,
                        "reason": "outside_off_peak_window",
                        "off_peak_start": off_peak_start,
                        "off_peak_end": off_peak_end,
                        "executed_at": datetime.now().isoformat(),
                    },
                )

            if automatic and (not conversation_id or not conversation_text):
                auto_input = self._build_automatic_dreaming_input(task.config)
                if auto_input is None:
                    return TaskResult(
                        success=True,
                        metrics={
                            "skipped": True,
                            "reason": "no_recent_conversation_data",
                            "executed_at": datetime.now().isoformat(),
                        },
                    )
                conversation_id = auto_input["conversation_id"]
                conversation_text = auto_input["conversation_text"]
                auto_metadata = auto_input.get("metadata", {})
            else:
                auto_metadata = {}

            if not conversation_id or not conversation_text:
                return TaskResult(
                    success=False,
                    error_message="Missing conversation_id or conversation_text in task config",
                )

            # Get pipeline
            pipeline = self._get_dreaming_pipeline(quality_level)

            # Process conversation through A→B→C→D pipeline
            results = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata={**task.config.get("metadata", {}), **auto_metadata},
            )

            if results.get("status") == "success":
                return TaskResult(
                    success=True,
                    output_file=results["stages"]["D_archive"]["path"],
                    metrics={
                        "b_chunks_count": results["stages"]["B_chunks"]["count"],
                        "c_clusters_count": results["stages"]["C_clusters"]["count"],
                        "quality_level": quality_level,
                        "archive_path": results["stages"]["D_archive"]["path"],
                        "automatic": automatic,
                    },
                )
            else:
                return TaskResult(
                    success=False,
                    error_message=results.get("error", "Unknown error during dreaming"),
                )

        except Exception as e:
            self._log(f"Dreaming task {task.id} failed: {e}", "error")
            return TaskResult(
                success=False, error_message=f"Dreaming execution error: {e}"
            )

    def _is_within_off_peak(self, start_hhmm: str, end_hhmm: str) -> bool:
        """Check if current local time is inside off-peak window."""
        now = datetime.now()
        try:
            start_hour, start_min = [int(x) for x in start_hhmm.split(":")]
            end_hour, end_min = [int(x) for x in end_hhmm.split(":")]
        except Exception:
            # Invalid config: treat as always allowed
            return True

        now_minutes = now.hour * 60 + now.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min

        # Handle windows that cross midnight.
        if start_minutes <= end_minutes:
            return start_minutes <= now_minutes <= end_minutes
        return now_minutes >= start_minutes or now_minutes <= end_minutes

    def _build_automatic_dreaming_input(
        self, config: dict
    ) -> Optional[dict]:
        """
        Build dreaming input from recent conversation memory for automatic tasks.
        Uses existing multi-model conversation store if available.
        """
        lookback = int(config.get("lookback_messages", 200))
        store_path = config.get(
            "conversation_store_path",
            ".memory/conversations_multi_model.json",
        )
        store_candidates = [
            Path(store_path),
            Path.home() / ".memory" / "conversations_multi_model.json",
        ]

        data = None
        used_path = None
        for candidate in store_candidates:
            if not candidate.exists():
                continue
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
                    used_path = candidate
                    break
            except Exception:
                continue

        if not data:
            return None

        recent = data[-lookback:] if len(data) > lookback else data
        lines = []
        for msg in recent:
            role = msg.get("message_type", "unknown")
            content = str(msg.get("text_content", "")).strip()
            if content:
                lines.append(f"[{role}] {content}")

        if not lines:
            return None

        now = datetime.now()
        conversation_id = f"auto_dream_{now.strftime('%Y%m%d_%H%M%S')}"
        return {
            "conversation_id": conversation_id,
            "conversation_text": "\n".join(lines),
            "metadata": {
                "trigger": "scheduler_automatic",
                "source": str(used_path) if used_path else "unknown",
                "message_count": len(lines),
                "generated_at": now.isoformat(),
                "original_text": "\n".join(lines),
            },
        }

    async def _execute_scheduled(self, task: Task) -> TaskResult:
        """
        Execute scheduled task (user calendar event)

        Executes user-scheduled calendar events like meetings, deadlines, reminders
        """
        self._log(f"Executing scheduled task {task.id}: {task.description}")

        try:
            # Parse schedule to understand when to run
            from app.scheduler.models import Schedule
            from app.scheduler.triggers import CronTrigger

            # Handle different schedule formats
            if isinstance(task.schedule, Schedule):
                # Already a Schedule object
                schedule_obj = task.schedule
                trigger = (
                    CronTrigger(schedule_obj.cron_expression)
                    if schedule_obj.cron_expression
                    else None
                )

                # Calculate run time
                if schedule_obj.when:
                    # Specific datetime schedule (e.g., "run at 2025-02-10T14:00")
                    run_at = schedule_obj.when
                else:
                    # Recurring cron schedule (e.g., "daily at 3pm")
                    if schedule_obj.cron_expression:
                        trigger = CronTrigger(schedule_obj.cron_expression)
                        run_at = trigger.get_next_run_time()
                    else:
                        # No trigger, run immediately (shouldn't happen for scheduled tasks)
                        self._log(
                            f"Warning: Task {task.id} has invalid schedule", "warning"
                        )
                        return TaskResult(
                            success=False,
                            error_message="Invalid schedule: must have cron_expression or when datetime",
                        )

            # Log when task will run
            self._log(f"Scheduled task {task.id} will run at {run_at.isoformat()}")

            # Mark as running
            task.mark_started()

            # Execute action based on task description
            # For now, just log execution (TODO: implement actual calendar integration)
            await asyncio.sleep(1)

            # Mark as completed
            task.mark_completed()
            self.stats["tasks_succeeded"] += 1
            self._log(f"Task {task.id} completed successfully")

            # Return success
            return TaskResult(
                success=True,
                output_file=None,
                metrics={
                    "executed_at": run_at.isoformat(),
                    "schedule_type": "datetime" if schedule_obj.when else "cron",
                },
            )

        except Exception as e:
            self._log(f"Error executing scheduled task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    async def _execute_agent(self, task: Task) -> TaskResult:
        """
        Execute agent task (OpenCode/OpenClaw operation)

        Integrates with OpenCode Manager to perform automated code operations
        """
        self._log(f"Executing agent task {task.id}: {task.description}")

        try:
            # Parse task config
            agent_type = task.config.get("agent_type", "opencode")  # opencode, openclaw
            operation = task.config.get(
                "operation"
            )  # start, stop, restart, destroy, list

            # Get project name from config
            project_name = task.config.get("project_name")

            # Validate required config
            if not project_name:
                return TaskResult(
                    success=False, error_message="Missing project_name in task config"
                )

            self._log(f"Agent task: {agent_type} {operation} on {project_name}")

            # Import OpenCode Manager
            from app.mcp.opencode.manager import OpenCodeManager

            manager = OpenCodeManager()

            # Execute operation
            if agent_type == "opencode":
                if operation == "start":
                    result = await manager.start_project(
                        project_name,
                        task.config.get("git_url"),
                        task.config.get("ssh_key_path"),
                    )
                elif operation == "stop":
                    result = await manager.stop_project(project_name)
                elif operation == "restart":
                    result = await manager.restart_project(project_name)
                elif operation == "destroy":
                    result = await manager.destroy_project(project_name)
                elif operation == "status":
                    result = await manager.get_status(project_name)
                elif operation == "list":
                    projects = await manager.list_projects()
                    result = TaskResult(
                        success=True,
                        metrics={"projects": len(projects.get("projects", []))},
                    )
                else:
                    return TaskResult(
                        success=False, error_message=f"Unknown operation: {operation}"
                    )

            if result.get("success", False):
                self._log(f"Agent task {task.id} completed successfully")
            else:
                self._log(f"Agent task {task.id} failed")

            return result

        except Exception as e:
            self._log(f"Error executing agent task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

        try:
            # Execute shell command
            process = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return TaskResult(
                    success=True,
                    metrics={
                        "return_code": process.returncode,
                        "stdout_length": len(stdout),
                    },
                )
            else:
                return TaskResult(
                    success=False,
                    error_message=stderr.decode() if stderr else "Command failed",
                )

        except Exception as e:
            return TaskResult(
                success=False, error_message=f"Failed to execute command: {e}"
            )
