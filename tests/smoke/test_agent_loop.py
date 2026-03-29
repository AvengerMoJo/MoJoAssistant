"""
Smoke — Agent loop end-to-end (no network, stub LLM)

Verifies that AgenticExecutor can run a complete think-act loop and extract a
FINAL_ANSWER without making any real network calls or API requests.

The LLM is replaced with a synchronous stub that returns a canned response on
the first call.  ResourceManager is seeded with a fake free local resource so
no config file is needed.

No external services required.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.scheduler.models import Task, TaskType, TaskPriority


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_resource():
    """Return a minimal LLMResource for a fake local endpoint."""
    from app.scheduler.resource_pool import LLMResource, ResourceTier
    return LLMResource(
        id="stub-local",
        type="local",
        provider="openai",
        base_url="http://127.0.0.1:9999/v1",  # nothing running here
        model="stub-model",
        tier=ResourceTier.FREE,
        enabled=True,
        api_key=None,
    )


def _make_llm_response(content: str) -> dict:
    """Wrap a plain-text reply in the OpenAI chat completions wire format."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _make_resource_manager(resource):
    """Create a ResourceManager with a single injected stub resource."""
    from app.scheduler.resource_pool import ResourceManager, UsageRecord

    rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
    rm._resources[resource.id] = resource
    rm._usage[resource.id] = UsageRecord()
    return rm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_loop_completes_with_final_answer(isolated_memory_path):
    """Agent loop extracts FINAL_ANSWER and returns success=True."""
    from app.scheduler.agentic_executor import AgenticExecutor

    stub_resource = _make_stub_resource()
    rm = _make_resource_manager(stub_resource)
    executor = AgenticExecutor(resource_manager=rm)

    task = Task(
        id="smoke-agent-1",
        type=TaskType.ASSISTANT,
        priority=TaskPriority.LOW,
        config={
            "goal": "Say hello",
            "available_tools": [],
            "max_iterations": 3,
        },
    )

    stub_reply = (
        "Let me answer that.\n\n"
        "<FINAL_ANSWER>\nHello, world!\n</FINAL_ANSWER>"
    )

    with patch(
        "app.llm.unified_client.UnifiedLLMClient.call_async",
        new_callable=AsyncMock,
        return_value=_make_llm_response(stub_reply),
    ):
        result = await executor.execute(task)

    assert result.success is True
    assert result.error_message is None


@pytest.mark.asyncio
async def test_agent_loop_fails_gracefully_when_no_resource(isolated_memory_path):
    """Agent loop returns failure when the resource pool is empty."""
    from app.scheduler.agentic_executor import AgenticExecutor
    from app.scheduler.resource_pool import ResourceManager

    rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
    # Intentionally leave _resources empty
    executor = AgenticExecutor(resource_manager=rm)

    task = Task(
        id="smoke-agent-no-resource",
        type=TaskType.ASSISTANT,
        priority=TaskPriority.LOW,
        config={
            "goal": "This should fail gracefully",
            "available_tools": [],
            "max_iterations": 1,
        },
    )

    result = await executor.execute(task)
    # Should not raise — must return a TaskResult with success=False
    assert result.success is False


@pytest.mark.asyncio
async def test_agent_loop_missing_goal_returns_failure(isolated_memory_path):
    """A task config without 'goal' fails immediately without calling the LLM."""
    from app.scheduler.agentic_executor import AgenticExecutor

    stub_resource = _make_stub_resource()
    rm = _make_resource_manager(stub_resource)
    executor = AgenticExecutor(resource_manager=rm)

    task = Task(
        id="smoke-agent-no-goal",
        type=TaskType.ASSISTANT,
        priority=TaskPriority.LOW,
        config={},  # no "goal" key
    )

    result = await executor.execute(task)
    assert result.success is False
    assert "goal" in (result.error_message or "").lower()
