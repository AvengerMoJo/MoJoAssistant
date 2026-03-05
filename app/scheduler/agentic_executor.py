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
from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession
from app.scheduler.planning_prompt_manager import PlanningPromptManager
from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
from app.scheduler.safety_policy import SafetyPolicy

DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous assistant working on a specific goal.
Think step by step. When you have completed the goal, wrap your final answer in \
<FINAL_ANSWER> tags like this:

<FINAL_ANSWER>
Your complete answer here.
</FINAL_ANSWER>

If you need more steps to reach the answer, continue reasoning. \
Do not use FINAL_ANSWER until you are confident the goal is fully addressed.

You may have tools available. Use them when needed to gather information."""

# Tool definitions for the agentic loop - dynamically loaded from registry
BUILTIN_TOOLS = {
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search the user's memory (conversations, documents, knowledge base) for relevant context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant context",
                    },
                },
                "required": ["query"],
            },
        },
    },
}

CONTINUE_PROMPT = (
    "Continue working toward the goal. "
    "If you are done, provide your answer inside <FINAL_ANSWER> tags."
)


class AgenticExecutor:
    """Executes agentic tasks via an autonomous LLM think-act loop."""

    def __init__(
        self, resource_manager: ResourceManager, logger=None, memory_service=None
    ):
        self._rm = resource_manager
        self._logger = logger
        self._memory_service = memory_service
        self._session_storage = SessionStorage()
        self._planning_manager = PlanningPromptManager()
        self._tool_registry = DynamicToolRegistry()
        self._tool_registry.set_memory_service(memory_service)
        self._policy = SafetyPolicy()

    def _log(self, message: str, level: str = "info"):
        if self._logger:
            getattr(self._logger, level)(f"[AgenticExecutor] {message}")

    def _record(self, task_id: str, role: str, content: str, iteration: int, **kwargs):
        """Append a message to the session log."""
        self._session_storage.append_message(
            task_id,
            SessionMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                iteration=iteration,
                **kwargs,
            ),
        )

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
            resume_from_task_id (str, optional): Load previous session and continue.
        """
        config = task.config or {}
        goal = config.get("goal", "")
        if not goal:
            return TaskResult(
                success=False, error_message="Missing 'goal' in task config"
            )

        # Load planning prompt based on task type or use default
        planning_prompt_name = config.get("planning_prompt", "agentic_planning")
        planning_prompt = self._planning_manager.get_prompt(
            planning_prompt_name, version="latest"
        )

        if planning_prompt:
            system_prompt = planning_prompt.content
            self._log(
                f"Using planning prompt: {planning_prompt_name} v{planning_prompt.version}"
            )
        else:
            system_prompt = config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
            self._log(
                f"Using default system prompt (no planning prompt found: {planning_prompt_name})"
            )

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

        # Load tools from dynamic registry (fallback to builtins)
        enabled_tool_names = config.get("available_tools", ["memory_search"])
        tool_defs = []

        for tool_name in enabled_tool_names:
            # Check dynamic registry first
            tool = self._tool_registry.get_tool(tool_name)
            if tool:
                tool_defs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                        },
                    }
                )
            # Fallback to builtins
            elif tool_name in BUILTIN_TOOLS:
                tool_defs.append(BUILTIN_TOOLS[tool_name])

        # --- Resume support ---
        resume_from = config.get("resume_from_task_id")
        if resume_from:
            messages, start_iteration = self._load_resume_messages(
                resume_from, system_prompt
            )
            if messages is None:
                return TaskResult(
                    success=False,
                    error_message=f"Cannot resume: session '{resume_from}' not found",
                )
            # Add a continuation prompt so the LLM knows we're resuming
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous attempt ran out of time or failed. "
                        "Continue working toward the original goal. "
                        "If you are done, provide your answer inside <FINAL_ANSWER> tags."
                    ),
                }
            )
        else:
            start_iteration = 0
            # Build initial messages
            messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
            ]
            # Build first user message with goal + optional context
            user_content = f"Goal: {goal}"
            context = config.get("context")
            if context:
                user_content += (
                    f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
                )
            messages.append({"role": "user", "content": user_content})

        # --- Create session ---
        session = TaskSession(
            task_id=task.id,
            status="running",
            messages=[],
            started_at=datetime.now().isoformat(),
            metadata={
                "goal": goal,
                "max_iterations": max_iterations,
                "resume_from": resume_from,
            },
        )
        self._session_storage.save_session(session)

        # Record initial messages
        for msg in messages:
            role = msg.get("role", msg.get("type", "unknown"))
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content, default=str)
            self._record(task.id, role, content or "", iteration=0)

        iteration_log: List[Dict[str, Any]] = []
        start_time = time.time()
        final_answer: Optional[str] = None

        self._log(
            f"Starting agentic loop for task {task.id} (max {max_iterations} iterations)"
        )

        for iteration in range(1, max_iterations + 1):
            abs_iteration = start_iteration + iteration
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                self._log(
                    f"Task {task.id}: time budget exhausted at iteration {iteration}"
                )
                self._session_storage.update_status(
                    task.id,
                    "timed_out",
                    error_message="Time budget exhausted",
                )
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
                    iteration_log.append(
                        {
                            "iteration": iteration,
                            "status": "no_resource",
                            "elapsed_s": round(time.time() - start_time, 1),
                        }
                    )
                    break

            # Call LLM
            self._log(
                f"Iteration {iteration}: calling {resource.model} via {resource.id}"
            )
            iter_start = time.time()
            try:
                response = await self._call_llm(
                    resource, messages, tools=tool_defs or None
                )
                self._rm.record_usage(resource.id, success=True)
            except Exception as e:
                self._rm.record_usage(resource.id, success=False)
                self._log(f"LLM call failed: {e}", "error")
                iteration_log.append(
                    {
                        "iteration": iteration,
                        "resource": resource.id,
                        "status": "error",
                        "error": str(e),
                        "elapsed_s": round(time.time() - iter_start, 1),
                    }
                )
                continue  # Try next iteration with potentially different resource

            message = response["choices"][0]["message"]
            response_text = message.get("content", "") or ""
            tool_calls = message.get("tool_calls")

            # Handle tool calls if present
            if tool_calls:
                # Append assistant message with tool calls
                messages.append(message)
                self._record(
                    task.id,
                    "assistant",
                    response_text,
                    iteration=abs_iteration,
                    metadata={
                        "tool_calls": [tc["function"]["name"] for tc in tool_calls]
                    },
                )

                tool_results = await self._execute_tool_calls(tool_calls)
                for tc, result_content in zip(tool_calls, tool_results):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        }
                    )
                    self._record(
                        task.id,
                        "tool",
                        result_content,
                        iteration=abs_iteration,
                        tool_call_id=tc["id"],
                        tool_name=tc["function"]["name"],
                    )

                iteration_log.append(
                    {
                        "iteration": iteration,
                        "resource": resource.id,
                        "model": resource.model,
                        "status": "tool_use",
                        "tool_calls": [tc["function"]["name"] for tc in tool_calls],
                        "elapsed_s": round(time.time() - iter_start, 1),
                    }
                )
                continue  # Next iteration will get the LLM's response to tool results

            # Append assistant response
            messages.append({"role": "assistant", "content": response_text})
            self._record(task.id, "assistant", response_text, iteration=abs_iteration)

            # Check for final answer
            final_answer = self._parse_final_answer(response_text)
            iteration_log.append(
                {
                    "iteration": iteration,
                    "resource": resource.id,
                    "model": resource.model,
                    "status": "final" if final_answer else "continue",
                    "response_length": len(response_text),
                    "elapsed_s": round(time.time() - iter_start, 1),
                }
            )

            if final_answer:
                self._log(f"Task {task.id}: got final answer at iteration {iteration}")
                self._session_storage.update_status(
                    task.id,
                    "completed",
                    final_answer=final_answer,
                )
                break

            # Append continue prompt for next iteration
            messages.append({"role": "user", "content": CONTINUE_PROMPT})
            self._record(task.id, "user", CONTINUE_PROMPT, iteration=abs_iteration)

        total_elapsed = round(time.time() - start_time, 1)
        success = final_answer is not None

        # Finalize session status if not already set
        current_session = self._session_storage.load_session(task.id)
        if current_session and current_session.status == "running":
            if success:
                self._session_storage.update_status(
                    task.id,
                    "completed",
                    final_answer=final_answer,
                )
            else:
                self._session_storage.update_status(
                    task.id,
                    "failed",
                    error_message="Agent did not produce a final answer within limits",
                )

        session_file = str(self._session_storage._path(task.id))

        return TaskResult(
            success=success,
            output_file=session_file,
            metrics={
                "iterations": len(iteration_log),
                "iteration_log": iteration_log,
                "duration_seconds": total_elapsed,
                "final_answer": final_answer,
                "session_file": session_file,
            },
            error_message=None
            if success
            else "Agent did not produce a final answer within limits",
        )

    def _load_resume_messages(
        self, task_id: str, system_prompt: str
    ) -> tuple[Optional[List[Dict]], int]:
        """
        Load messages from a previous session for resumption.
        Returns (messages, last_iteration) or (None, 0) if session not found.
        """
        session = self._session_storage.load_session(task_id)
        if session is None:
            return None, 0

        messages: List[Dict] = []
        max_iteration = 0
        for msg in session.messages:
            max_iteration = max(max_iteration, msg.iteration)
            entry: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages.append(entry)

        return messages, max_iteration

    async def _call_llm(
        self,
        resource: LLMResource,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> Dict:
        """Make an OpenAI-compatible chat completion request. Returns the full response dict."""
        url = f"{resource.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if resource.api_key:
            headers["Authorization"] = f"Bearer {resource.api_key}"

        payload: Dict[str, Any] = {
            "model": resource.model,
            "messages": messages,
            "max_tokens": resource.output_limit,
            "temperature": 0.7,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("LLM returned no choices")
        return data

    async def _execute_tool_calls(self, tool_calls: List[Dict]) -> List[str]:
        """Execute tool calls and return results as strings."""
        results = []
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                fn_args = {}

            try:
                result = await self._execute_single_tool(fn_name, fn_args)
                results.append(json.dumps(result, default=str))
            except Exception as e:
                self._log(f"Tool {fn_name} failed: {e}", "error")
                results.append(json.dumps({"error": str(e)}))
        return results

    async def _execute_single_tool(self, name: str, args: Dict) -> Any:
        """Execute a single tool from dynamic registry or built-in tools."""
        # Get tool from registry for policy check
        tool = self._tool_registry.get_tool(name)

        # Check safety policy before execution
        if tool:
            policy_check = self._policy.check_tool_execution(name, tool.to_dict(), args)
            if not policy_check["allowed"]:
                self._log(
                    f"Tool {name} blocked by policy: {policy_check['reason']}",
                    "warning",
                )
                self._policy.track_operation(
                    operation="execute",
                    tool_name=name,
                    success=False,
                    reason=policy_check["reason"],
                )
                return {"error": f"Policy violation: {policy_check['reason']}"}

        # Try dynamic registry first
        try:
            result = await self._tool_registry.execute_tool(name, args)
            if result.get("success"):
                self._policy.track_operation(
                    operation="execute", tool_name=name, success=True
                )
                return result
        except Exception as e:
            self._log(f"Dynamic tool {name} failed: {e}", "error")

        # Fallback to built-in tools
        if name == "memory_search" and self._memory_service:
            query = args.get("query", "")
            results = await self._memory_service.get_context_for_query_async(
                query, max_items=5
            )
            return {"query": query, "results": results, "count": len(results)}

        return {"error": f"Unknown or unavailable tool: {name}"}

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
