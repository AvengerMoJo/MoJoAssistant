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
        self._openrouter_model_cache: Dict[str, Dict[str, Any]] = {}
        self._openrouter_model_cache_ttl_seconds = 600

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

        # Load role personality if role_id is specified
        role_prefix = ""
        role_model_preference = None
        role_id = config.get("role_id")
        if role_id:
            try:
                from app.roles.role_manager import RoleManager
                role = RoleManager().get(role_id)
                if role:
                    role_prefix = role.get("system_prompt", "")
                    role_model_preference = role.get("model_preference")
                    self._log(f"Loaded role: {role.get('name')} (id={role_id})")
                else:
                    self._log(f"Role '{role_id}' not found — continuing without role")
            except Exception as e:
                self._log(f"Failed to load role '{role_id}': {e}")

        # Load planning prompt — default to role_task when a role is active
        default_prompt = "role_task" if role_id else "agentic_planning"
        planning_prompt_name = config.get("planning_prompt", default_prompt)
        planning_prompt = self._planning_manager.get_prompt(
            planning_prompt_name, version="latest"
        )

        if planning_prompt:
            workflow_prompt = planning_prompt.content
            self._log(
                f"Using planning prompt: {planning_prompt_name} v{planning_prompt.version}"
            )
        else:
            workflow_prompt = config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
            self._log(
                f"Using default system prompt (no planning prompt found: {planning_prompt_name})"
            )

        # Combine: role personality first, then workflow instructions
        if role_prefix:
            system_prompt = role_prefix + "\n\n---\n\n" + workflow_prompt
        else:
            system_prompt = workflow_prompt

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

            # Acquire a resource (dynamic policy can reorder tiers per iteration)
            iter_tiers, selection_reason = self._determine_tier_preference_for_iteration(
                base_tiers=tier_preference,
                goal=goal,
                config=config,
                iteration_log=iteration_log,
            )
            resource = self._rm.acquire(tier_preference=iter_tiers)
            if resource is None:
                self._log(f"No resource available, waiting 30s (iteration {iteration})")
                # Wait and retry once
                import asyncio

                await asyncio.sleep(30)
                resource = self._rm.acquire(tier_preference=iter_tiers)
                if resource is None:
                    self._log("Still no resource available, aborting")
                    iteration_log.append(
                        {
                            "iteration": iteration,
                            "status": "no_resource",
                            "tier_preference": [t.value for t in iter_tiers],
                            "selection_reason": selection_reason,
                            "elapsed_s": round(time.time() - start_time, 1),
                        }
                    )
                    break

            # Call LLM
            effective_model = role_model_preference or resource.model
            self._log(
                f"Iteration {iteration}: calling {effective_model} via {resource.id}"
            )
            iter_start = time.time()
            try:
                response = await self._call_llm(
                    resource, messages, tools=tool_defs or None,
                    model_override=role_model_preference,
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
                        "tier_preference": [t.value for t in iter_tiers],
                        "selection_reason": selection_reason,
                        "error": str(e),
                        "elapsed_s": round(time.time() - iter_start, 1),
                    }
                )
                continue  # Try next iteration with potentially different resource

            message = response["choices"][0]["message"]
            used_model = response.get("_selected_model", resource.model)
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
                        "model": used_model,
                        "tier_preference": [t.value for t in iter_tiers],
                        "selection_reason": selection_reason,
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
            candidate_final_answer = self._parse_final_answer(response_text)
            final_validation_error = None
            final_answer = None
            if candidate_final_answer is not None:
                is_valid, validation_error = self._validate_final_answer(
                    final_answer=candidate_final_answer,
                    goal=goal,
                    config=config,
                )
                if is_valid:
                    final_answer = candidate_final_answer
                else:
                    final_validation_error = validation_error
            iteration_log.append(
                {
                    "iteration": iteration,
                    "resource": resource.id,
                    "model": used_model,
                    "tier_preference": [t.value for t in iter_tiers],
                    "selection_reason": selection_reason,
                    "status": (
                        "final"
                        if final_answer
                        else ("final_rejected" if final_validation_error else "continue")
                    ),
                    "response_length": len(response_text),
                    "validation_error": final_validation_error,
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
            if final_validation_error:
                correction_prompt = (
                    "Your previous <FINAL_ANSWER> was rejected by validation: "
                    f"{final_validation_error}. "
                    "Return a corrected <FINAL_ANSWER> only."
                )
                messages.append({"role": "user", "content": correction_prompt})
                self._record(task.id, "user", correction_prompt, iteration=abs_iteration)
                continue

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
        model_override: Optional[str] = None,
    ) -> Dict:
        """Make an OpenAI-compatible chat completion request. Returns the full response dict."""
        url = f"{resource.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if resource.api_key:
            headers["Authorization"] = f"Bearer {resource.api_key}"

        selected_model = model_override or await self._resolve_model_for_resource(resource, headers)
        payload: Dict[str, Any] = {
            "model": selected_model,
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
            data["_selected_model"] = selected_model

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("LLM returned no choices")
        return data

    async def _resolve_model_for_resource(
        self, resource: LLMResource, headers: Dict[str, str]
    ) -> str:
        """Resolve the effective model for a resource."""
        model = resource.model or ""
        if not self._is_openrouter_auto(resource):
            return model

        free_model = await self._get_cached_openrouter_free_model(resource, headers)
        if free_model:
            return free_model
        return model

    def _is_openrouter_auto(self, resource: LLMResource) -> bool:
        """Return True if this resource should auto-resolve OpenRouter free model."""
        base = (resource.base_url or "").rstrip("/")
        return base.startswith("https://openrouter.ai/api/v1") and (
            resource.model == "openrouter/auto"
        )

    async def _get_cached_openrouter_free_model(
        self, resource: LLMResource, headers: Dict[str, str]
    ) -> Optional[str]:
        """Fetch/cached OpenRouter free model id for this resource."""
        if not resource.api_key:
            return None

        now = time.time()
        cache_entry = self._openrouter_model_cache.get(resource.id)
        if cache_entry and now - cache_entry["fetched_at"] < self._openrouter_model_cache_ttl_seconds:
            return cache_entry.get("model")

        models_url = f"{resource.base_url.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(models_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            self._log(f"OpenRouter model discovery failed for {resource.id}: {e}", "warning")
            return None

        model_id = self._pick_openrouter_free_model(data)
        if model_id:
            self._openrouter_model_cache[resource.id] = {
                "model": model_id,
                "fetched_at": now,
            }
            self._log(f"Resolved OpenRouter free model for {resource.id}: {model_id}")
        return model_id

    def _pick_openrouter_free_model(self, models_payload: Dict[str, Any]) -> Optional[str]:
        """Pick a free model id from OpenRouter /models payload."""
        models = models_payload.get("data")
        if not isinstance(models, list):
            return None

        free_ids: List[str] = []
        zero_price_ids: List[str] = []

        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue

            if model_id.endswith(":free"):
                free_ids.append(model_id)

            pricing = model.get("pricing")
            if isinstance(pricing, dict):
                prompt = str(pricing.get("prompt", ""))
                completion = str(pricing.get("completion", ""))
                request = str(pricing.get("request", "0"))
                image = str(pricing.get("image", "0"))
                if (
                    prompt in {"0", "0.0", "0.00"}
                    and completion in {"0", "0.0", "0.00"}
                    and request in {"0", "0.0", "0.00"}
                    and image in {"0", "0.0", "0.00"}
                ):
                    zero_price_ids.append(model_id)

        if free_ids:
            return sorted(set(free_ids))[0]
        if zero_price_ids:
            return sorted(set(zero_price_ids))[0]
        return None

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
            # Preserve concrete tool error for the LLM instead of masking it.
            return {"error": result.get("error", f"Tool '{name}' failed")}
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

    def _determine_tier_preference_for_iteration(
        self,
        base_tiers: List[ResourceTier],
        goal: str,
        config: Dict[str, Any],
        iteration_log: List[Dict[str, Any]],
    ) -> tuple[List[ResourceTier], str]:
        """Dynamically choose tier order per iteration based on task complexity and recent failures."""
        policy = config.get("resource_policy", {})
        if not policy.get("enabled", True):
            return base_tiers, "static_policy_disabled"

        complexity = self._estimate_task_complexity(goal, config)
        prefer_api_for_complex = bool(
            policy.get("prefer_api_for_complex_tasks", True)
        )
        allow_paid_for_complex = bool(
            policy.get("allow_paid_for_complex_tasks", False)
        )

        if complexity >= 3 and prefer_api_for_complex:
            dynamic_tiers: List[ResourceTier] = [ResourceTier.FREE_API, ResourceTier.FREE]
        else:
            dynamic_tiers = [ResourceTier.FREE, ResourceTier.FREE_API]

        if allow_paid_for_complex and complexity >= 4:
            dynamic_tiers.append(ResourceTier.PAID)

        # Respect user-provided tier list as an allowlist.
        allow = set(base_tiers)
        dynamic_tiers = [t for t in dynamic_tiers if t in allow]
        if not dynamic_tiers:
            dynamic_tiers = base_tiers

        # If recent iterations show repeated failure on first tier, flip order.
        recent = iteration_log[-3:]
        if len(recent) >= 2:
            first_tier = dynamic_tiers[0]
            failed = 0
            for item in recent:
                rid = item.get("resource")
                if item.get("status") == "error" and rid:
                    r = self._rm._resources.get(rid)
                    if r and r.tier == first_tier:
                        failed += 1
            if failed >= 2 and len(dynamic_tiers) > 1:
                dynamic_tiers = dynamic_tiers[1:] + dynamic_tiers[:1]
                return (
                    dynamic_tiers,
                    f"dynamic_flip_after_{failed}_recent_{first_tier.value}_errors",
                )

        return dynamic_tiers, f"dynamic_complexity_{complexity}"

    def _estimate_task_complexity(self, goal: str, config: Dict[str, Any]) -> int:
        """Estimate task complexity on a small 1-5 scale."""
        text = (goal or "").lower()
        score = 1
        if len(text) > 300:
            score += 1
        hard_keywords = [
            "architecture",
            "refactor",
            "debug",
            "investigate",
            "analyze",
            "design",
            "multi-step",
            "integration",
            "policy",
        ]
        if any(k in text for k in hard_keywords):
            score += 2
        if config.get("available_tools"):
            score += 1
        max_iter = int(config.get("max_iterations", 1) or 1)
        if max_iter >= 6:
            score += 1
        return max(1, min(score, 5))

    def _validate_final_answer(
        self, final_answer: str, goal: str, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate final answer quality gates before marking task completed."""
        if not final_answer or not final_answer.strip():
            return False, "empty final answer"

        answer = final_answer.strip()
        if "<FINAL_ANSWER>" in answer or "</FINAL_ANSWER>" in answer:
            return False, "nested FINAL_ANSWER tags are not allowed"

        req = config.get("final_answer_requirements", {})
        min_length = int(req.get("min_length", 1))
        max_length = req.get("max_length")
        if len(answer) < min_length:
            return False, f"answer shorter than min_length={min_length}"
        if isinstance(max_length, int) and len(answer) > max_length:
            return False, f"answer longer than max_length={max_length}"

        must_include = req.get("must_include", [])
        if isinstance(must_include, list):
            for token in must_include:
                if token and token not in answer:
                    return False, f"missing required token '{token}'"

        exact_text = req.get("exact_text") or self._infer_exact_text_from_goal(goal)
        if exact_text:
            normalized = answer.strip().strip('"').strip("'")
            if normalized != exact_text:
                return False, f"must equal exact_text '{exact_text}'"

        # Guard against leaking planning boilerplate into final answer for "exact" asks.
        if exact_text and ("## Phase" in answer or "Phase 1:" in answer):
            return False, "final answer contains planning boilerplate"

        return True, None

    def _infer_exact_text_from_goal(self, goal: str) -> Optional[str]:
        """Infer exact output requirement from goal text when user asks for exact output."""
        text = goal or ""
        lower = text.lower()
        markers = [
            "containing exactly:",
            "exactly:",
            "exact text:",
            "exact output:",
        ]
        for marker in markers:
            idx = lower.find(marker)
            if idx == -1:
                continue
            raw = text[idx + len(marker) :].strip()
            if not raw:
                return None
            # Stop at first line break to avoid capturing extra instructions.
            raw = raw.splitlines()[0].strip()
            return raw.strip().strip('"').strip("'")
        return None
