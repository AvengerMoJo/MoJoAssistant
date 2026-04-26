"""
Task Executor

Thin dispatcher: routes tasks to pluggable handlers via HandlerRegistry.
Handler logic lives in app/scheduler/handlers/.

External callers (core.py, tools.py) access executor state through the
backward-compat properties and methods below — those interfaces are stable.
"""
# [hitl-orchestrator: generic]

from typing import Optional

from app.scheduler.models import Task, TaskResult
from app.scheduler.executor_registry import ExecutorContext, HandlerRegistry
from app.scheduler.handlers import build_registry


class TaskExecutor:
    """
    Executes tasks by routing to appropriate handlers.

    Supports:
    - Dreaming tasks (memory consolidation)
    - Scheduled tasks (user calendar events)
    - Agent tasks (OpenCode/OpenClaw)
    - Custom tasks (user-defined)
    - Agentic tasks (autonomous LLM loop)
    """

    def __init__(
        self,
        logger=None,
        llm_config_path: Optional[str] = None,
        memory_service=None,
        mcp_client_manager=None,
        scheduler=None,
    ):
        self._ctx = ExecutorContext(
            logger=logger,
            llm_config_path=llm_config_path,
            memory_service=memory_service,
            mcp_client_manager=mcp_client_manager,
            scheduler=scheduler,
        )
        self._registry: HandlerRegistry = build_registry()

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    def _log(self, message: str, level: str = "info") -> None:
        self._ctx.log(message, level)

    async def execute(self, task: Task) -> TaskResult:
        self._log(f"Executing task {task.id} of type {task.type.value}")
        try:
            result = await self._registry.dispatch(task, self._ctx)
            self._log(
                f"Task {task.id} execution result: {'success' if result.success else 'failed'}"
            )
            return result
        except Exception as e:
            self._log(f"Error executing task {task.id}: {e}", "error")
            return TaskResult(success=False, error_message=str(e))

    # ------------------------------------------------------------------
    # Backward-compat pass-throughs for core.py and tools.py callers
    # ------------------------------------------------------------------

    @property
    def logger(self):
        return self._ctx.logger

    @property
    def _mcp_client_manager(self):
        return self._ctx._mcp_client_manager

    @property
    def _resource_manager(self):
        return self._ctx._resource_manager

    @property
    def _agentic_executor(self):
        return self._ctx._agentic_executor

    def _get_resource_manager(self):
        return self._ctx.get_resource_manager()

    def _get_agentic_executor(self):
        return self._ctx.get_agentic_executor()

    def reset_pipeline(self) -> None:
        self._ctx.reset_pipeline()
