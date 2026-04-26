"""Scheduled task handler — calendar events (local JSON/ICS and Google Calendar)."""
# [mojo-integration]
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult
from app.config.paths import get_memory_subpath


class ScheduledHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        ctx.log(f"Executing scheduled task {task.id}: {task.description}")

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
                from datetime import timedelta
                duration_minutes = int(config.get("duration_minutes", 30))
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
                tz = config.get("timezone", defaults.get("timezone", "UTC"))
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
                    timezone=tz,
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
            ctx.log(f"Error executing scheduled task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _persist_local_calendar_event(
        self,
        task: Task,
        title: str,
        details: str,
        start_at: datetime,
        end_at: datetime,
        config: Dict[str, Any],
    ) -> TaskResult:
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
            config.get(
                "events_file",
                get_memory_subpath("scheduler", "calendar_events.json"),
            )
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
                    f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
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

    @staticmethod
    def _load_google_calendar_policy() -> Dict[str, Any]:
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

    @staticmethod
    async def _create_google_calendar_event(
        calendar_id: str,
        title: str,
        details: str,
        start_at: datetime,
        end_at: datetime,
        timezone: str,
    ) -> Dict[str, Any]:
        payload = {
            "summary": title,
            "description": details,
            "start": {"dateTime": start_at.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_at.isoformat(), "timeZone": timezone},
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
