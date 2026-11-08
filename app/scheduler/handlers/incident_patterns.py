"""Daily BRIDLE step: read the incident log, write the pattern report, tell the owner once.

The handler is deliberately thin: `app/scheduler/incident_patterns.py` owns the logic (grouping,
threshold arithmetic, the daily cap, the state file) and this file only turns a scheduled task
into a call of it. It never disables, excludes or re-ranks a resource -- it reports.

Config (in config/scheduler_config.json, merged with ~/.memory/config/scheduler_config.json by
task id, so `enabled: false` in the personal layer turns the step off):

    {
      "id": "incident_patterns_daily",
      "type": "incident_patterns",
      "cron": "0 8 * * *",
      "priority": "low",
      "enabled": true,
      "config": {"min_tasks": 2, "window_days": 14, "notify_threshold": 3}
    }
"""
# [mojo-integration]
from __future__ import annotations

from typing import Any, Dict

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult


class IncidentPatternsHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        from app.scheduler.incident_patterns import (
            DEFAULT_MIN_TASKS,
            DEFAULT_NOTIFY_THRESHOLD,
            DEFAULT_WINDOW_DAYS,
            scan_patterns,
        )

        cfg: Dict[str, Any] = task.config or {}
        min_tasks = int(cfg.get("min_tasks", DEFAULT_MIN_TASKS))
        window_days = int(cfg.get("window_days", DEFAULT_WINDOW_DAYS))
        notify_threshold = int(cfg.get("notify_threshold", DEFAULT_NOTIFY_THRESHOLD))

        try:
            summary = await scan_patterns(
                min_tasks=min_tasks,
                window_days=window_days,
                notify_threshold=notify_threshold,
                notify=self._notify,
            )
        except Exception as e:
            ctx.log(f"incident pattern scan failed: {e}", "error")
            return TaskResult(success=False, error_message=f"incident pattern scan failed: {e}")

        ctx.log(
            f"incident patterns: {summary['pattern_count']} pattern(s), "
            f"{len(summary['reportable'])} to report, notified={summary['notified']}, "
            f"pending={len(summary['pending'])} -> {summary['state_path']}"
        )
        return TaskResult(success=True, metrics=summary)

    @staticmethod
    async def _notify(title: str, body: str) -> None:
        from app.mcp.adapters.hitl.manager import get_shared_manager
        await get_shared_manager().send_notification(title=title, body=body)
