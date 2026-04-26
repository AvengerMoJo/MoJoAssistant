"""
Task handler registry — one register() call per TaskType.

New task type: add a handler file here, call registry.register() below.
"""
from app.scheduler.executor_registry import HandlerRegistry
from app.scheduler.models import TaskType
from app.scheduler.handlers.dreaming import DreamingHandler
from app.scheduler.handlers.scheduled import ScheduledHandler
from app.scheduler.handlers.agent import AgentHandler
from app.scheduler.handlers.custom import CustomHandler
from app.scheduler.handlers.agentic import AgenticHandler


def build_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register(TaskType.DREAMING, DreamingHandler())
    registry.register(TaskType.SCHEDULED, ScheduledHandler())
    registry.register(TaskType.EXTERNAL_AGENT, AgentHandler())
    registry.register(TaskType.CUSTOM, CustomHandler())
    registry.register(TaskType.INTERNAL_ASSIGNMENT, AgenticHandler())
    return registry
