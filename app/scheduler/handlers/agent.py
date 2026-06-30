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

            # Sandbox provisioning for external agents — provision a container
            # so OpenCode / Claude Code run in isolation instead of on the host.
            _sandbox_handle = None
            git_url = config.get("git_url") or config.get("identifier")
            if git_url and git_url.startswith(("git@", "https://", "http://")):
                try:
                    from app.scheduler.sandbox.manager import SandboxManager
                    _mgr = SandboxManager.load()
                    _sandbox_handle = await _mgr.acquire(
                        task_id=task.id,
                        git_url=git_url,
                        working_dir=config.get("working_dir"),
                        role_id=config.get("role_id"),
                        backend_override=config.get("sandbox_backend"),
                    )
                    # Pass working_dir and container URL into agent config so the
                    # external agent manager can find the right environment.
                    config["working_dir"] = _sandbox_handle.working_dir or config.get("working_dir")
                    config["_sandbox_handle"] = _sandbox_handle
                    ctx.log(
                        f"Agent task {task.id}: sandbox provisioned "
                        f"backend={_sandbox_handle.backend} id={_sandbox_handle.sandbox_id}"
                    )
                except Exception as _se:
                    ctx.log(f"Agent task {task.id}: sandbox provisioning failed (non-fatal): {_se}", "warning")

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
        finally:
            if _sandbox_handle is not None:
                try:
                    from app.scheduler.sandbox.manager import SandboxManager
                    teardown = config.get("sandbox_teardown", "pause")
                    await SandboxManager.load().release(_sandbox_handle, mode=teardown)
                except Exception as _re:
                    ctx.log(f"Agent sandbox release failed (non-fatal): {_re}", "warning")
