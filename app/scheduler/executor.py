"""
Task Executor

Routes tasks to appropriate execution handlers based on task type.
"""

import asyncio
import json
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from app.scheduler.models import Task, TaskType, TaskResult
from app.dreaming.pipeline import DreamingPipeline
from app.llm.llm_interface import LLMInterface
from app.config.paths import get_memory_subpath, get_memory_path


class TaskExecutor:
    """
    Executes tasks by routing to appropriate handlers

    Supports:
    - Dreaming tasks (memory consolidation)
    - Scheduled tasks (user calendar events)
    - Agent tasks (OpenCode/OpenClaw)
    - Custom tasks (user-defined)
    - Agentic tasks (autonomous LLM loop)
    """

    def __init__(
        self, logger=None, llm_config_path: Optional[str] = None, memory_service=None
    ):
        """
        Initialize executor

        Args:
            logger: Optional logger instance
            llm_config_path: Path to LLM configuration file for dreaming
            memory_service: Optional memory service for agentic tool use
        """
        self.logger = logger
        self.llm_config_path = llm_config_path or "config/llm_config.json"
        self._memory_service = memory_service
        self._dreaming_pipeline = None
        self._cached_quality_level = None
        self._resource_manager = None
        self._agentic_executor = None
        self._agent_registry = None

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
            elif task.type == TaskType.ASSISTANT:
                result = await self._execute_agentic(task)
            else:
                raise ValueError(f"Unknown task type: {task.type}")

            self._log(
                f"Task {task.id} execution result: {'success' if result.success else 'failed'}"
            )
            return result

        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    def reset_pipeline(self) -> None:
        """Reset cached dreaming pipeline so next call rebuilds it with fresh config"""
        self._dreaming_pipeline = None
        self._cached_quality_level = None

    def _get_dreaming_pipeline(self, quality_level: str = "basic") -> DreamingPipeline:
        """Get or initialize dreaming pipeline, rebuilding if quality_level changed"""
        if (
            self._dreaming_pipeline is None
            or self._cached_quality_level != quality_level
        ):
            # Initialize LLM interface
            llm = LLMInterface(config_file=self.llm_config_path)

            # Create pipeline
            self._dreaming_pipeline = DreamingPipeline(
                llm_interface=llm, quality_level=quality_level, logger=self.logger
            )
            self._cached_quality_level = quality_level

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
                archive = results["stages"]["D_archive"]
                archive_path = archive.get("storage_location") or archive.get("path", "")
                metrics = {
                    "b_chunks_count": results["stages"]["B_chunks"]["count"],
                    "c_clusters_count": results["stages"]["C_clusters"]["count"],
                    "quality_level": quality_level,
                    "archive_path": archive_path,
                    "automatic": automatic,
                }

                # Optional inbox distillation pass after main pipeline
                if task.config.get("distill_inbox", False):
                    try:
                        from datetime import date, timedelta
                        from app.dreaming.inbox_distillation import run_inbox_distillation
                        from app.mcp.adapters.event_log import EventLog
                        target_date = date.today() - timedelta(days=1)
                        event_log = EventLog()
                        inbox_result = await run_inbox_distillation(
                            target_date=target_date,
                            event_log=event_log,
                            pipeline=pipeline,
                            quality_level=quality_level,
                        )
                        metrics["inbox_distillation"] = inbox_result.get("status", "unknown")
                        self._log(f"Inbox distillation: {inbox_result.get('status')} for {target_date}")
                    except Exception as e:
                        self._log(f"Inbox distillation failed (non-fatal): {e}", "warning")
                        metrics["inbox_distillation"] = "error"

                return TaskResult(
                    success=True,
                    output_file=archive_path,
                    metrics=metrics,
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

    def _build_automatic_dreaming_input(self, config: dict) -> Optional[dict]:
        """
        Build dreaming input from recent conversation memory for automatic tasks.
        Uses existing multi-model conversation store if available.
        """
        lookback = int(config.get("lookback_messages", 200))
        store_path = config.get(
            "conversation_store_path",
            get_memory_subpath("conversations_multi_model.json"),
        )
        store_candidates = [
            Path(store_path),
            Path(get_memory_subpath("conversations_multi_model.json")),
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

        Persists calendar events and optionally runs reminder commands.

        Task config supports:
        - title (str): Event title
        - details (str): Event details/notes
        - start_time (ISO datetime): Overrides task.schedule as event start
        - end_time (ISO datetime): Explicit event end time
        - duration_minutes (int): Used when end_time not provided (default: 30)
        - events_file (str): JSON event store path (default: .memory/scheduler/calendar_events.json)
        - export_ics (bool): Export a per-event .ics file (default: true)
        - reminder_command (str): Optional shell command to execute after event persist
        """
        self._log(f"Executing scheduled task {task.id}: {task.description}")

        try:
            config = task.config or {}
            title = config.get("title") or task.description or f"Scheduled Task {task.id}"
            details = config.get("details", "")

            start_time_str = config.get("start_time")
            if start_time_str:
                start_at = datetime.fromisoformat(start_time_str)
            elif task.schedule:
                start_at = task.schedule
            else:
                start_at = datetime.now()

            end_time_str = config.get("end_time")
            if end_time_str:
                end_at = datetime.fromisoformat(end_time_str)
            else:
                duration_minutes = int(config.get("duration_minutes", 30))
                from datetime import timedelta

                end_at = start_at + timedelta(minutes=duration_minutes)

            provider = config.get("provider", "local")
            if provider == "google_calendar":
                policy = self._load_google_calendar_policy()
                defaults = policy.get("defaults", {})
                rules = policy.get("rules", {})
                scopes = policy.get("scopes", {})

                scope_name = config.get(
                    "calendar_scope", defaults.get("calendar_scope", "user")
                )
                scope_cfg = scopes.get(scope_name, {})
                calendar_id = config.get(
                    "calendar_id",
                    scope_cfg.get("calendar_id", "primary"),
                )
                timezone = config.get("timezone", defaults.get("timezone", "UTC"))
                task_owner = config.get("task_owner", defaults.get("task_owner", "user"))

                if (
                    rules.get("require_explicit_opt_in_for_agent_write_to_primary", True)
                    and calendar_id == "primary"
                    and task_owner != "user"
                    and not config.get("allow_agent_write_primary", False)
                ):
                    return TaskResult(
                        success=False,
                        error_message=(
                            "Agent/system write to primary calendar is blocked by policy. "
                            "Set allow_agent_write_primary=true for explicit override."
                        ),
                    )

                google_result = await self._create_google_calendar_event(
                    calendar_id=calendar_id,
                    title=title,
                    details=details,
                    start_at=start_at,
                    end_at=end_at,
                    timezone=timezone,
                )

                if google_result.get("success"):
                    return TaskResult(
                        success=True,
                        metrics={
                            "provider": "google_calendar",
                            "calendar_scope": scope_name,
                            "calendar_id": calendar_id,
                            "event_id": google_result.get("event_id"),
                            "html_link": google_result.get("html_link"),
                            "start_at": start_at.isoformat(),
                            "end_at": end_at.isoformat(),
                        },
                    )

                if not rules.get("fallback_to_local_scheduler_files_on_google_error", True):
                    return TaskResult(
                        success=False,
                        error_message=google_result.get("error", "Google Calendar failed"),
                    )

                local_result = await self._persist_local_calendar_event(
                    task=task,
                    title=title,
                    details=details,
                    start_at=start_at,
                    end_at=end_at,
                    config=config,
                )
                local_result.metrics["provider"] = "local_fallback"
                local_result.metrics["google_error"] = google_result.get("error")
                return local_result

            return await self._persist_local_calendar_event(
                task=task,
                title=title,
                details=details,
                start_at=start_at,
                end_at=end_at,
                config=config,
            )

        except Exception as e:
            self._log(f"Error executing scheduled task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    async def _persist_local_calendar_event(
        self,
        task: Task,
        title: str,
        details: str,
        start_at: datetime,
        end_at: datetime,
        config: Dict[str, Any],
    ) -> TaskResult:
        """Persist scheduled event to local JSON/ICS files."""
        event_id = f"{task.id}_{uuid.uuid4().hex[:8]}"
        event_record = {
            "id": event_id,
            "task_id": task.id,
            "title": title,
            "details": details,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "created_at": datetime.now().isoformat(),
            "priority": task.priority.value,
            "cron_expression": task.cron_expression,
        }

        events_file = Path(
            config.get("events_file", get_memory_subpath("scheduler", "calendar_events.json"))
        ).expanduser()
        events_file.parent.mkdir(parents=True, exist_ok=True)

        events = []
        if events_file.exists():
            try:
                events = json.loads(events_file.read_text(encoding="utf-8"))
                if not isinstance(events, list):
                    events = []
            except Exception:
                events = []
        events.append(event_record)
        events_file.write_text(json.dumps(events, indent=2), encoding="utf-8")

        ics_file = None
        if config.get("export_ics", True):
            ics_dir = events_file.parent / "ics"
            ics_dir.mkdir(parents=True, exist_ok=True)
            ics_file = ics_dir / f"{event_id}.ics"
            ics_content = "\n".join(
                [
                    "BEGIN:VCALENDAR",
                    "VERSION:2.0",
                    "PRODID:-//MoJoAssistant//Scheduler//EN",
                    "BEGIN:VEVENT",
                    f"UID:{event_id}",
                    f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTSTART:{start_at.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND:{end_at.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{title}",
                    f"DESCRIPTION:{details}",
                    "END:VEVENT",
                    "END:VCALENDAR",
                    "",
                ]
            )
            ics_file.write_text(ics_content, encoding="utf-8")

        reminder_result = None
        reminder_command = config.get("reminder_command")
        if reminder_command:
            process = await asyncio.create_subprocess_shell(
                reminder_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            reminder_result = {
                "command": reminder_command,
                "return_code": process.returncode,
                "stdout": stdout.decode("utf-8", errors="ignore"),
                "stderr": stderr.decode("utf-8", errors="ignore"),
            }

        return TaskResult(
            success=True,
            output_file=str(events_file),
            metrics={
                "provider": "local",
                "event_id": event_id,
                "title": title,
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "events_file": str(events_file),
                "ics_file": str(ics_file) if ics_file else None,
                "reminder": reminder_result,
            },
        )

    def _load_google_calendar_policy(self) -> Dict[str, Any]:
        """Load Google calendar scheduler policy from config with safe defaults."""
        policy_path = Path("config/google_calendar_scheduler_policy.json")
        if policy_path.exists():
            try:
                return json.loads(policy_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "defaults": {
                "task_owner": "user",
                "calendar_scope": "user",
                "timezone": "UTC",
            },
            "scopes": {
                "user": {"calendar_id": "primary"},
                "ops": {"calendar_id": "mojo_assistant_ops"},
            },
            "rules": {
                "require_explicit_opt_in_for_agent_write_to_primary": True,
                "fallback_to_local_scheduler_files_on_google_error": True,
            },
        }

    async def _create_google_calendar_event(
        self,
        calendar_id: str,
        title: str,
        details: str,
        start_at: datetime,
        end_at: datetime,
        timezone: str,
    ) -> Dict[str, Any]:
        """Create an event via gws calendar CLI."""
        payload = {
            "summary": title,
            "description": details,
            "start": {
                "dateTime": start_at.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_at.isoformat(),
                "timeZone": timezone,
            },
        }
        params = {"calendarId": calendar_id}

        try:
            proc = await asyncio.create_subprocess_exec(
                "gws",
                "calendar",
                "events",
                "insert",
                "--params",
                json.dumps(params),
                "--json",
                json.dumps(payload),
                "--format",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_text = stdout.decode("utf-8", errors="ignore")
            stderr_text = stderr.decode("utf-8", errors="ignore")

            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"gws exit={proc.returncode}: {stderr_text or stdout_text}",
                }

            try:
                result = json.loads(stdout_text) if stdout_text.strip() else {}
            except Exception:
                return {
                    "success": False,
                    "error": f"Failed to parse gws response: {stdout_text}",
                }

            if isinstance(result, dict) and result.get("error"):
                err = result["error"]
                return {
                    "success": False,
                    "error": f"{err.get('code')}: {err.get('message')}",
                }

            return {
                "success": True,
                "event_id": result.get("id"),
                "html_link": result.get("htmlLink"),
                "raw": result,
            }
        except FileNotFoundError:
            return {"success": False, "error": "gws CLI not found in PATH"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_agent_registry(self):
        """Lazy-initialize AgentRegistry."""
        if self._agent_registry is None:
            from app.mcp.agents.registry import AgentRegistry

            self._agent_registry = AgentRegistry(logger=self.logger)
        return self._agent_registry

    async def _execute_agent(self, task: Task) -> TaskResult:
        """
        Execute agent task using unified AgentRegistry.
        """
        self._log(f"Executing agent task {task.id}: {task.description}")

        try:
            config = task.config or {}
            agent_type = config.get("agent_type", "opencode")
            operation = config.get("operation")
            identifier = (
                config.get("identifier")
                or config.get("project_name")
                or config.get("git_url")
            )
            params = config.get("params", {})

            if not operation:
                return TaskResult(
                    success=False, error_message="Missing operation in task config"
                )

            manager = self._get_agent_registry().get_manager(agent_type)
            self._log(f"Agent task: {agent_type} {operation} on {identifier}")

            if operation == "list":
                result = await manager.list_projects()
            elif operation == "start":
                if not identifier:
                    return TaskResult(
                        success=False,
                        error_message="Missing identifier/project_name/git_url for start",
                    )
                result = await manager.start_project(identifier, **params)
            elif operation == "stop":
                if not identifier:
                    return TaskResult(
                        success=False,
                        error_message="Missing identifier/project_name/git_url for stop",
                    )
                result = await manager.stop_project(identifier)
            elif operation == "restart":
                if not identifier:
                    return TaskResult(
                        success=False,
                        error_message="Missing identifier/project_name/git_url for restart",
                    )
                result = await manager.restart_project(identifier)
            elif operation == "destroy":
                if not identifier:
                    return TaskResult(
                        success=False,
                        error_message="Missing identifier/project_name/git_url for destroy",
                    )
                result = await manager.destroy_project(identifier)
            elif operation == "status":
                if not identifier:
                    return TaskResult(
                        success=False,
                        error_message="Missing identifier/project_name/git_url for status",
                    )
                result = await manager.get_status(identifier)
            elif operation == "action":
                action = config.get("action")
                if not action:
                    return TaskResult(
                        success=False, error_message="Missing action for operation=action"
                    )
                result = await manager.execute_action(action, params)
            else:
                return TaskResult(
                    success=False, error_message=f"Unknown agent operation: {operation}"
                )

            status = result.get("status")
            success = status in ("success", "ok", "already_running")
            if not success and isinstance(result.get("success"), bool):
                success = result["success"]

            return TaskResult(
                success=success,
                metrics={
                    "agent_type": agent_type,
                    "operation": operation,
                    "identifier": identifier,
                    "result": result,
                },
                error_message=None if success else result.get("message") or result.get("error"),
            )

        except Exception as e:
            self._log(f"Error executing agent task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    async def _execute_custom(self, task: Task) -> TaskResult:
        """
        Execute custom task (user-defined shell command)

        Task config should contain:
        - command: Shell command to execute
        - use_atd: Boolean, if True uses atd for service restarts (default: False)
        - at_delay: Delay in minutes for atd job (default: 1)

        When use_atd=True, command is scheduled via 'at' daemon,
        which is more reliable for service restarts that would kill the scheduler.
        """
        command = task.config.get("command")
        use_atd = task.config.get("use_atd", False)
        at_delay = task.config.get("at_delay", 1)

        if not command:
            return TaskResult(
                success=False, error_message="Missing 'command' in task config"
            )

        self._log(f"Executing custom command: {command} (use_atd={use_atd})")

        try:
            if use_atd:
                # Schedule via atd for service restarts
                # This ensures command runs even if MCP server is killed
                self._log(f"Scheduling command via atd with {at_delay} minute delay")
                process = await asyncio.create_subprocess_shell(
                    f'echo "{command}" | at now + {at_delay}min',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    at_job_id = None
                    output = stdout.decode()
                    # Extract at job ID from output like "job 42 at ..."
                    if "job" in output:
                        try:
                            at_job_id = output.split("job ")[1].split()[0]
                        except:
                            pass

                    return TaskResult(
                        success=True,
                        metrics={
                            "return_code": process.returncode,
                            "scheduled_via": "atd",
                            "at_job_id": at_job_id,
                            "at_delay_minutes": at_delay,
                            "at_output": output,
                        },
                    )
                else:
                    return TaskResult(
                        success=False,
                        error_message=stderr.decode()
                        if stderr
                        else "Failed to schedule atd job",
                    )
            else:
                # Execute synchronously (normal behavior)
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    return TaskResult(
                        success=True,
                        metrics={
                            "return_code": process.returncode,
                            "stdout_length": len(stdout),
                            "stdout": stdout.decode()[:1000],
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

    def _get_resource_manager(self):
        """Lazy-initialize the ResourceManager."""
        if self._resource_manager is None:
            from app.scheduler.resource_pool import ResourceManager

            self._resource_manager = ResourceManager(logger=self.logger)
        return self._resource_manager

    def _get_agentic_executor(self):
        """Lazy-initialize the AgenticExecutor."""
        if self._agentic_executor is None:
            from app.scheduler.agentic_executor import AgenticExecutor

            self._agentic_executor = AgenticExecutor(
                resource_manager=self._get_resource_manager(),
                logger=self.logger,
                memory_service=self._memory_service,
            )
        return self._agentic_executor

    def _get_coding_agent_executor(self):
        """Lazy-initialize the CodingAgentExecutor."""
        if not hasattr(self, "_coding_agent_executor") or self._coding_agent_executor is None:
            from app.scheduler.coding_agent_executor import CodingAgentExecutor

            self._coding_agent_executor = CodingAgentExecutor(
                resource_manager=self._get_resource_manager(),
                logger=self.logger,
                memory_service=self._memory_service,
            )
        return self._coding_agent_executor

    async def _execute_agentic(self, task: Task) -> TaskResult:
        """
        Execute an agentic task (autonomous LLM think-act loop).

        Task config should contain:
        - goal: What the agent should accomplish
        - system_prompt: Optional override for the system prompt
        - max_iterations: Optional max LLM round-trips
        - context: Optional dict of extra context
        - parallel_agents: Optional parallel fan-out config:
            {
              "enabled": true,
              "count": 3,
              "goal_variants": ["...", "..."],
              "max_concurrent": 3
            }
        """
        self._log(f"Executing agentic task {task.id}")

        # Route to CodingAgentExecutor if the role has executor="coding_agent"
        cfg = task.config or {}
        role_id = cfg.get("role_id")
        if role_id:
            try:
                from app.roles.role_manager import RoleManager
                role = RoleManager().get(role_id)
                if role and role.get("executor") == "coding_agent":
                    self._log(f"Task {task.id}: routing to CodingAgentExecutor (role={role_id})")
                    return await self._get_coding_agent_executor().execute(task)
            except Exception as e:
                self._log(f"Coding agent routing check failed for role '{role_id}': {e}", "warning")

        executor = None
        try:
            executor = self._get_agentic_executor()
            cfg = task.config or {}
            mode = str(cfg.get("mode", "normal")).strip().lower()

            if mode == "deep_research":
                cfg.setdefault("max_iterations", max(task.resources.max_iterations, 8))
                cfg.setdefault("max_duration_seconds", 600)
                cfg.setdefault("available_tools", ["memory_search"])
                cfg.setdefault(
                    "resource_policy",
                    {"enabled": True, "prefer_api_for_complex_tasks": True},
                )
                cfg.setdefault(
                    "final_answer_requirements",
                    {"min_length": 120, "must_include": ["Summary"]},
                )

            parallel_cfg = cfg.get("parallel_agents", {})
            if mode == "parallel_discovery" and not parallel_cfg:
                parallel_cfg = {"enabled": True, "count": 3, "max_concurrent": 3}

            if isinstance(parallel_cfg, dict) and parallel_cfg.get("enabled"):
                return await self._execute_agentic_parallel(task, executor, parallel_cfg)
            return await executor.execute(task)
        except Exception as e:
            import traceback
            self._log(f"Agentic task {task.id} failed: {e}\n{traceback.format_exc()}", "error")
            if executor is not None:
                session_file = str(executor._session_storage._path(task.id))
            else:
                from app.scheduler.session_storage import SessionStorage

                session_file = str(SessionStorage()._path(task.id))
            return TaskResult(
                success=False,
                output_file=session_file,
                metrics={"session_file": session_file},
                error_message=f"Agentic execution error: {e}",
            )

    async def _execute_agentic_parallel(
        self, task: Task, executor, parallel_cfg: Dict[str, Any]
    ) -> TaskResult:
        """Execute multiple agentic variants concurrently and aggregate results."""
        base_config = dict(task.config or {})
        variants = parallel_cfg.get("goal_variants")
        count = int(parallel_cfg.get("count", 0) or 0)
        max_concurrent = int(parallel_cfg.get("max_concurrent", 3) or 3)

        if isinstance(variants, list) and variants:
            goals = [str(v) for v in variants if str(v).strip()]
        else:
            if count <= 0:
                count = 2
            base_goal = str(base_config.get("goal", "")).strip()
            if not base_goal:
                return TaskResult(
                    success=False,
                    error_message="Missing goal for parallel agentic execution",
                )
            goals = [base_goal for _ in range(count)]

        if not goals:
            return TaskResult(
                success=False, error_message="No valid goals generated for parallel execution"
            )

        # Remove orchestration hint from child configs to avoid recursion.
        child_base_config = dict(base_config)
        child_base_config.pop("parallel_agents", None)

        import asyncio
        from app.scheduler.models import Task as SchedulerTask

        sem = asyncio.Semaphore(max(1, max_concurrent))

        async def _run_variant(idx: int, goal_text: str) -> Dict[str, Any]:
            async with sem:
                child_id = f"{task.id}__p{idx+1}"
                child_cfg = dict(child_base_config)
                child_cfg["goal"] = goal_text
                child_cfg["parallel_parent_task_id"] = task.id
                child_task = SchedulerTask(
                    id=child_id,
                    type=task.type,
                    priority=task.priority,
                    config=child_cfg,
                    resources=task.resources,
                    created_by=task.created_by,
                    description=f"{task.description or task.id} [parallel {idx+1}]",
                )
                result = await executor.execute(child_task)
                return {
                    "variant_index": idx + 1,
                    "task_id": child_id,
                    "goal": goal_text,
                    "success": result.success,
                    "error_message": result.error_message,
                    "output_file": result.output_file,
                    "metrics": result.metrics or {},
                }

        results = await asyncio.gather(
            *[_run_variant(i, goal) for i, goal in enumerate(goals)]
        )

        success_count = sum(1 for r in results if r["success"])
        review_report = self._build_parallel_review_report(results, parallel_cfg)
        best_task_id = review_report.get("recommended_task_id")
        best_result = next(
            (r for r in results if r.get("task_id") == best_task_id),
            next((r for r in results if r["success"]), results[0]),
        )
        all_final_answers = []
        for r in results:
            metrics = r.get("metrics") or {}
            all_final_answers.append(
                {
                    "task_id": r.get("task_id"),
                    "success": r.get("success"),
                    "final_answer": metrics.get("final_answer"),
                    "error_message": r.get("error_message"),
                    "resource_trace": [
                        {
                            "iteration": it.get("iteration"),
                            "resource": it.get("resource"),
                            "model": it.get("model"),
                            "status": it.get("status"),
                        }
                        for it in (metrics.get("iteration_log") or [])
                    ],
                }
            )

        aggregate_metrics = {
            "mode": "parallel_agents",
            "parent_task_id": task.id,
            "variant_count": len(results),
            "success_count": success_count,
            "failure_count": len(results) - success_count,
            "results": results,
            "final_answers": all_final_answers,
            "review_report": review_report,
            "selected_best_task_id": best_result.get("task_id"),
            "selected_best_answer": (best_result.get("metrics") or {}).get("final_answer"),
        }

        return TaskResult(
            success=success_count > 0,
            output_file=(best_result.get("metrics") or {}).get("session_file")
            or best_result.get("output_file"),
            metrics=aggregate_metrics,
            error_message=None
            if success_count > 0
            else "All parallel agent variants failed",
        )

    def _build_parallel_review_report(
        self, results: List[Dict[str, Any]], parallel_cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build deterministic comparison report for parallel variants."""
        review_policy = parallel_cfg.get("review_policy", {}) if isinstance(parallel_cfg, dict) else {}
        weights = {
            "format_compliance": float(review_policy.get("format_compliance", 0.40)),
            "goal_match": float(review_policy.get("goal_match", 0.30)),
            "tool_hygiene": float(review_policy.get("tool_hygiene", 0.15)),
            "latency": float(review_policy.get("latency", 0.10)),
            "cost_tier": float(review_policy.get("cost_tier", 0.05)),
        }

        # Normalize latency score against worst successful variant.
        durations = []
        for r in results:
            metrics = r.get("metrics") or {}
            dur = metrics.get("duration_seconds")
            if isinstance(dur, (int, float)):
                durations.append(float(dur))
        max_dur = max(durations) if durations else 1.0

        rm = self._get_resource_manager()
        scored = []
        for r in results:
            metrics = r.get("metrics") or {}
            final_answer = metrics.get("final_answer")
            goal = str(r.get("goal", ""))
            exact_text = self._infer_exact_text_from_goal(goal)
            iteration_log = metrics.get("iteration_log") or []

            format_compliance = 1.0 if r.get("success") and final_answer else 0.0

            if exact_text and isinstance(final_answer, str):
                norm = final_answer.strip().strip('"').strip("'")
                goal_match = 1.0 if norm == exact_text else (0.5 if exact_text in norm else 0.0)
            elif isinstance(final_answer, str) and final_answer.strip():
                goal_match = 1.0 if r.get("success") else 0.3
            else:
                goal_match = 0.0

            total_steps = max(1, len(iteration_log))
            error_steps = sum(1 for i in iteration_log if i.get("status") == "error")
            tool_hygiene = max(0.0, 1.0 - (error_steps / total_steps))

            dur = metrics.get("duration_seconds")
            if isinstance(dur, (int, float)) and max_dur > 0:
                latency = max(0.0, 1.0 - (float(dur) / max_dur))
            else:
                latency = 0.5

            # Prefer lower cost tiers (free >= free_api > paid).
            tier_score = 0.5
            if iteration_log:
                rid = iteration_log[0].get("resource")
                res = rm._resources.get(rid) if rid else None
                if res is not None:
                    tier_score = {
                        "free": 1.0,
                        "free_api": 0.8,
                        "paid": 0.2,
                    }.get(res.tier.value, 0.5)

            total = (
                weights["format_compliance"] * format_compliance
                + weights["goal_match"] * goal_match
                + weights["tool_hygiene"] * tool_hygiene
                + weights["latency"] * latency
                + weights["cost_tier"] * tier_score
            )

            scored.append(
                {
                    "task_id": r.get("task_id"),
                    "success": r.get("success"),
                    "score": round(total, 4),
                    "dimensions": {
                        "format_compliance": round(format_compliance, 4),
                        "goal_match": round(goal_match, 4),
                        "tool_hygiene": round(tool_hygiene, 4),
                        "latency": round(latency, 4),
                        "cost_tier": round(tier_score, 4),
                    },
                    "final_answer": final_answer,
                    "error_message": r.get("error_message"),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0] if scored else None

        require_human = bool(review_policy.get("require_human_review", True))
        auto_decide = bool(review_policy.get("auto_decide", False))
        decision_required = require_human or not auto_decide
        recommendation_reason = self._build_parallel_recommendation_reason(best)
        recommended_next_actions = self._build_parallel_next_actions(
            best=best,
            scored=scored,
            decision_required=decision_required,
        )
        summary = self._build_parallel_summary(
            scored=scored,
            best=best,
            decision_required=decision_required,
            recommendation_reason=recommendation_reason,
        )

        return {
            "policy": {
                "weights": weights,
                "require_human_review": require_human,
                "auto_decide": auto_decide,
            },
            "decision_required": decision_required,
            "recommended_task_id": best.get("task_id") if best else None,
            "recommended_score": best.get("score") if best else None,
            "recommendation_reason": recommendation_reason,
            "recommended_next_actions": recommended_next_actions,
            "summary": summary,
            "ranked_results": scored,
        }

    def _build_parallel_recommendation_reason(
        self, best: Optional[Dict[str, Any]]
    ) -> str:
        """Explain why the top-ranked variant was selected."""
        if not best:
            return "No successful variant was available to recommend."

        dims = best.get("dimensions") or {}
        reasons = []
        if dims.get("format_compliance", 0) >= 1.0:
            reasons.append("passed format checks")
        if dims.get("goal_match", 0) >= 1.0:
            reasons.append("matched the requested goal")
        if dims.get("tool_hygiene", 0) >= 1.0:
            reasons.append("showed clean execution with no tool/runtime errors")
        latency = dims.get("latency", 0)
        if latency >= 0.5:
            reasons.append("completed faster than competing variants")

        if not reasons:
            reasons.append("achieved the highest overall deterministic score")
        return ", ".join(reasons)

    def _build_parallel_next_actions(
        self,
        best: Optional[Dict[str, Any]],
        scored: List[Dict[str, Any]],
        decision_required: bool,
    ) -> List[str]:
        """Provide generic next actions for client/UI orchestration."""
        actions: List[str] = []
        if best:
            actions.append(
                f"Inspect recommended result from {best.get('task_id')} before proceeding."
            )
        if decision_required:
            actions.append(
                "Human decision required: review ranked_results and approve which variant should move forward."
            )

        failed = [item for item in scored if not item.get("success")]
        if failed:
            actions.append(
                "Review failed variants to identify reusable corrections or prompt-contract improvements."
            )
        else:
            actions.append(
                "All variants succeeded; compare quality and latency tradeoffs before selecting one."
            )
        return actions

    def _build_parallel_summary(
        self,
        scored: List[Dict[str, Any]],
        best: Optional[Dict[str, Any]],
        decision_required: bool,
        recommendation_reason: str,
    ) -> str:
        """Build a concise human-readable review summary."""
        total = len(scored)
        success_count = sum(1 for item in scored if item.get("success"))
        failure_count = total - success_count

        if not best:
            return (
                f"{total} variants completed with no valid recommendation. "
                f"Successes: {success_count}. Failures: {failure_count}."
            )

        return (
            f"{total} variants completed. Successes: {success_count}. "
            f"Failures: {failure_count}. Recommended: {best.get('task_id')} "
            f"(score {best.get('score')}) because it {recommendation_reason}. "
            f"{'Human decision required.' if decision_required else 'Auto-decision permitted by policy.'}"
        )

    def _infer_exact_text_from_goal(self, goal: str) -> Optional[str]:
        """Infer exact output requirement from goal text for scoring."""
        text = goal or ""
        lower = text.lower()
        markers = [
            "containing exactly:",
            "exactly:",
            "exact text:",
            "exact output:",
        ]
        for marker in markers:
            idx = lower.find(marker)
            if idx == -1:
                continue
            raw = text[idx + len(marker) :].strip()
            if not raw:
                return None
            raw = raw.splitlines()[0].strip()
            return raw.strip().strip('"').strip("'")
        return None
