"""External agent task handler — OpenCode / AgentRegistry dispatch."""
# [mojo-integration]
from __future__ import annotations

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult


class AgentHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        ctx.log(f"Executing agent task {task.id}: {task.description}")

        try:
            config = task.config or {}

            if config.get("ext_agent_hitl"):
                ctx.log(f"Agent task {task.id}: ext_agent_hitl stub — no-op")
                return TaskResult(success=True, metrics={"note": "ext_agent_hitl stub"})

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

            manager = ctx.get_agent_registry().get_manager(agent_type)
            ctx.log(f"Agent task: {agent_type} {operation} on {identifier}")

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
            ctx.log(f"Error executing agent task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))
