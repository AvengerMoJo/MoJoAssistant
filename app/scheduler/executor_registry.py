"""
Executor registry — pluggable handler dispatch for HITLOrchestrator.

ExecutorContext: shared lazy state passed to every handler.
TaskHandler: ABC each handler implements.
HandlerRegistry: TaskType → TaskHandler map; dispatch entry point.
"""
# [hitl-orchestrator: generic]
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from app.scheduler.models import Task, TaskResult, TaskType
from app.config.paths import get_memory_subpath


class TaskHandler(ABC):
    """Pluggable handler for one task type."""

    @abstractmethod
    async def execute(self, task: Task, ctx: "ExecutorContext") -> TaskResult:
        ...


class HandlerRegistry:
    """Maps TaskType to TaskHandler. New type = one register() call."""

    def __init__(self) -> None:
        self._handlers: Dict[TaskType, TaskHandler] = {}

    def register(self, task_type: TaskType, handler: TaskHandler) -> None:
        self._handlers[task_type] = handler

    async def dispatch(self, task: Task, ctx: "ExecutorContext") -> TaskResult:
        handler = self._handlers.get(task.type)
        if handler is None:
            raise ValueError(f"No handler registered for task type: {task.type}")
        return await handler.execute(task, ctx)


class ExecutorContext:
    """
    Shared lazy state for all task handlers.

    Handlers receive this instead of a TaskExecutor reference — keeps the
    registry generic and the HITLOrchestrator layer free of host-app imports.
    """

    def __init__(
        self,
        logger=None,
        llm_config_path: Optional[str] = None,
        memory_service=None,
        mcp_client_manager=None,
        scheduler=None,
    ) -> None:
        self.logger = logger
        self.llm_config_path = llm_config_path or "config/llm_config.json"
        self._memory_service = memory_service
        self._mcp_client_manager = mcp_client_manager
        self._scheduler = scheduler

        # Lazy-initialized shared objects
        self._dreaming_pipeline = None
        self._cached_quality_level: Optional[str] = None
        self._resource_manager = None
        self._agentic_executor = None
        self._agent_registry = None
        self._coding_agent_executor = None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        if self.logger:
            getattr(self.logger, level)(f"[Executor] {message}")

    # ------------------------------------------------------------------
    # Lazy resource accessors
    # ------------------------------------------------------------------

    def get_resource_manager(self):
        if self._resource_manager is None:
            from app.scheduler.resource_pool import ResourceManager
            self._resource_manager = ResourceManager(logger=self.logger)
        return self._resource_manager

    def get_agentic_executor(self):
        if self._agentic_executor is None:
            from app.scheduler.agentic_executor import AgenticExecutor
            self._agentic_executor = AgenticExecutor(
                resource_manager=self.get_resource_manager(),
                logger=self.logger,
                memory_service=self._memory_service,
                mcp_client_manager=self._mcp_client_manager,
                scheduler=self._scheduler,
            )
        return self._agentic_executor

    def get_agent_registry(self):
        if self._agent_registry is None:
            from app.mcp.agents.registry import AgentRegistry
            self._agent_registry = AgentRegistry(logger=self.logger)
        return self._agent_registry

    def get_coding_agent_executor(self):
        if self._coding_agent_executor is None:
            from app.scheduler.coding_agent_executor import CodingAgentExecutor
            self._coding_agent_executor = CodingAgentExecutor(
                resource_manager=self.get_resource_manager(),
                logger=self.logger,
                memory_service=self._memory_service,
            )
        return self._coding_agent_executor

    def get_dreaming_pipeline(self, quality_level: str = "basic"):
        if (
            self._dreaming_pipeline is None
            or self._cached_quality_level != quality_level
        ):
            from app.dreaming.pipeline import DreamingPipeline
            self._dreaming_pipeline = DreamingPipeline(
                llm_interface=self._build_dreaming_llm(),
                quality_level=quality_level,
                logger=self.logger,
                storage_path=Path(get_memory_subpath("dreams")),
            )
            self._cached_quality_level = quality_level
        return self._dreaming_pipeline

    def _build_dreaming_llm(self) -> Any:
        from app.llm.llm_interface import LLMInterface
        try:
            from app.scheduler.resource_pool import ResourceManager
            from app.llm.resource_pool_interface import ResourcePoolLLMInterface
            rm = self.get_resource_manager()
            if rm and rm._resources:
                return ResourcePoolLLMInterface(rm)
        except Exception as e:
            self.log(
                f"ResourcePool LLM unavailable, falling back to llm_config: {e}", "warning"
            )
        return LLMInterface(config_file=self.llm_config_path)

    def reset_pipeline(self) -> None:
        self._dreaming_pipeline = None
        self._cached_quality_level = None
