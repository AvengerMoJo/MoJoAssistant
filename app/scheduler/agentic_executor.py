"""
Agentic Executor

Autonomous think-act loop that drives LLM conversations to completion
using resources from the ResourceManager.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.scheduler.models import Task, TaskResult
from app.scheduler.resource_pool import LLMResource, ResourceManager, ResourceTier

DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous assistant working on a specific goal.
Think step by step. When you have completed the goal, wrap your final answer in \
<FINAL_ANSWER> tags like this:

<FINAL_ANSWER>
Your complete answer here.
</FINAL_ANSWER>

If you need more steps to reach the answer, continue reasoning. \
Do not use FINAL_ANSWER until you are confident the goal is fully addressed."""

CONTINUE_PROMPT = (
    "Continue working toward the goal. "
    "If you are done, provide your answer inside <FINAL_ANSWER> tags."
)


class AgenticExecutor:
    """Executes agentic tasks via an autonomous LLM think-act loop."""

    def __init__(self, resource_manager: ResourceManager, logger=None):
        self._rm = resource_manager
        self._logger = logger

    def _log(self, message: str, level: str = "info"):
        if self._logger:
            getattr(self._logger, level)(f"[AgenticExecutor] {message}")

    async def execute(self, task: Task) -> TaskResult:
        """
        Run the agentic loop for a task.

        Task config keys:
            goal (str): What the agent should accomplish.
            system_prompt (str, optional): Override default system prompt.
            max_iterations (int, optional): Max LLM round-trips (default from resources).
            context (dict, optional): Extra context injected into first user message.
            max_duration_seconds (int, optional): Wall-clock time budget.
            tier_preference (list[str], optional): Resource tier preference.
        """
        config = task.config or {}
        goal = config.get("goal", "")
        if not goal:
            return TaskResult(success=False, error_message="Missing 'goal' in task config")

        system_prompt = config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        max_iterations = config.get("max_iterations", task.resources.max_iterations)
        max_duration = config.get(
            "max_duration_seconds",
            task.resources.max_duration_seconds or 300,
        )

        tier_pref_raw = config.get("tier_preference", task.resources.tier_preference)
        if tier_pref_raw:
            tier_preference = [ResourceTier(t) for t in tier_pref_raw]
        else:
            tier_preference = [ResourceTier.FREE, ResourceTier.FREE_API]

        # Build initial messages
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Build first user message with goal + optional context
        user_content = f"Goal: {goal}"
        context = config.get("context")
        if context:
            user_content += f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
        messages.append({"role": "user", "content": user_content})

        iteration_log: List[Dict[str, Any]] = []
        start_time = time.time()
        final_answer: Optional[str] = None

        self._log(f"Starting agentic loop for task {task.id} (max {max_iterations} iterations)")

        for iteration in range(1, max_iterations + 1):
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                self._log(f"Task {task.id}: time budget exhausted at iteration {iteration}")
                break

            # Acquire a resource
            resource = self._rm.acquire(tier_preference=tier_preference)
            if resource is None:
                self._log(f"No resource available, waiting 30s (iteration {iteration})")
                # Wait and retry once
                import asyncio
                await asyncio.sleep(30)
                resource = self._rm.acquire(tier_preference=tier_preference)
                if resource is None:
                    self._log("Still no resource available, aborting")
                    iteration_log.append({
                        "iteration": iteration,
                        "status": "no_resource",
                        "elapsed_s": round(time.time() - start_time, 1),
                    })
                    break

            # Call LLM
            self._log(f"Iteration {iteration}: calling {resource.model} via {resource.id}")
            iter_start = time.time()
            try:
                response_text = await self._call_llm(resource, messages)
                self._rm.record_usage(resource.id, success=True)
            except Exception as e:
                self._rm.record_usage(resource.id, success=False)
                self._log(f"LLM call failed: {e}", "error")
                iteration_log.append({
                    "iteration": iteration,
                    "resource": resource.id,
                    "status": "error",
                    "error": str(e),
                    "elapsed_s": round(time.time() - iter_start, 1),
                })
                continue  # Try next iteration with potentially different resource

            # Append assistant response
            messages.append({"role": "assistant", "content": response_text})

            # Check for final answer
            final_answer = self._parse_final_answer(response_text)
            iteration_log.append({
                "iteration": iteration,
                "resource": resource.id,
                "model": resource.model,
                "status": "final" if final_answer else "continue",
                "response_length": len(response_text),
                "elapsed_s": round(time.time() - iter_start, 1),
            })

            if final_answer:
                self._log(f"Task {task.id}: got final answer at iteration {iteration}")
                break

            # Append continue prompt for next iteration
            messages.append({"role": "user", "content": CONTINUE_PROMPT})

        total_elapsed = round(time.time() - start_time, 1)
        success = final_answer is not None

        return TaskResult(
            success=success,
            metrics={
                "iterations": len(iteration_log),
                "iteration_log": iteration_log,
                "duration_seconds": total_elapsed,
                "final_answer": final_answer,
            },
            error_message=None if success else "Agent did not produce a final answer within limits",
        )

    async def _call_llm(self, resource: LLMResource, messages: List[Dict[str, str]]) -> str:
        """Make an OpenAI-compatible chat completion request."""
        url = f"{resource.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if resource.api_key:
            headers["Authorization"] = f"Bearer {resource.api_key}"

        payload = {
            "model": resource.model,
            "messages": messages,
            "max_tokens": resource.output_limit,
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("LLM returned no choices")
        return choices[0]["message"]["content"]

    def _parse_final_answer(self, text: str) -> Optional[str]:
        """Extract content between <FINAL_ANSWER> tags, if present."""
        tag_open = "<FINAL_ANSWER>"
        tag_close = "</FINAL_ANSWER>"
        start = text.find(tag_open)
        if start == -1:
            return None
        start += len(tag_open)
        end = text.find(tag_close, start)
        if end == -1:
            # Tag opened but not closed — treat the rest as the answer
            return text[start:].strip()
        return text[start:end].strip()
