"""Agentic task handler — autonomous LLM think-act loop, including parallel fan-out."""
# [mojo-integration]
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult


class AgenticHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        ctx.log(f"Executing agentic task {task.id}")

        cfg = task.config or {}
        role_id = cfg.get("role_id")
        if role_id:
            try:
                from app.roles.role_manager import RoleManager
                role = RoleManager().get(role_id)
                # Task-level executor override takes precedence over role default
                task_executor = cfg.get("executor")
                if task_executor == "agentic":
                    # Force agentic executor regardless of role's executor setting
                    ctx.log(f"Task {task.id}: using agentic executor (task override)")
                elif role and role.get("executor") == "coding_agent":
                    ctx.log(
                        f"Task {task.id}: routing to CodingAgentExecutor (role={role_id})"
                    )
                    return await ctx.get_coding_agent_executor().execute(task)
            except Exception as e:
                ctx.log(
                    f"Coding agent routing check failed for role '{role_id}': {e}", "warning"
                )

        # Task routing — optional plugin, off by default.
        # Enable via scheduler_config.json: {"task_routing": {"enabled": true}}
        _routing_enabled = False
        try:
            from app.config.paths import load_layered_json_config
            _sched_cfg = load_layered_json_config("config/scheduler_config.json")
            _routing_enabled = bool((_sched_cfg.get("task_routing") or {}).get("enabled", False))
        except Exception:
            pass
        if _routing_enabled:
            try:
                from app.scheduler.task_router import TaskRouter
                router = TaskRouter.load()
                routing = router.classify_and_route(
                    goal=cfg.get("goal", ""),
                    role_id=role_id or "",
                    declared_tools=cfg.get("available_tools", []),
                )
                cfg["_routing"] = routing
                ctx.log(f"Task routed to cell={routing['cell']} model={routing['model_id']} "
                        f"confidence={routing['confidence']:.2f}")
            except Exception as e:
                ctx.log(f"TaskRouter failed: {e}", "warning")

        # Sandbox provisioning — same lifecycle pattern as ResourcePool for LLMs.
        # If the task needs a container (git_url present, sandbox_required, or
        # task_type matches auto_provision rules), acquire one before the loop.
        # All bash_exec / read_file / write_file calls then route through it.
        _sandbox_handle = None
        _sandbox_token = None
        try:
            from app.scheduler.sandbox.manager import SandboxManager
            from app.scheduler.sandbox.context import _cv_sandbox_handle
            _mgr = SandboxManager.load()
            if _mgr.should_provision(task):
                _cfg_pre = task.config or {}
                _git_url = _cfg_pre.get("git_url")
                # Also extract from goal text when not explicit in config
                if not _git_url:
                    import re as _re
                    _goal_text = _cfg_pre.get("goal", "")
                    _m = _re.search(
                        r"(git@\S+\.git|https?://(?:github|gitlab|bitbucket)\.com/\S+(?:\.git)?)",
                        _goal_text,
                    )
                    if _m:
                        _git_url = _m.group(0).rstrip(".,)")
                _sandbox_handle = await _mgr.acquire(
                    task_id=task.id,
                    git_url=_git_url,
                    working_dir=_cfg_pre.get("working_dir"),
                    role_id=role_id,
                    backend_override=_cfg_pre.get("sandbox_backend"),
                )
                _sandbox_token = _cv_sandbox_handle.set(_sandbox_handle)
                ctx.log(
                    f"Sandbox provisioned: backend={_sandbox_handle.backend} "
                    f"id={_sandbox_handle.sandbox_id} workdir={_sandbox_handle.working_dir}"
                )
                # Auto-grant shell/file tools for this task — the sandbox IS
                # the isolation layer so these are safe inside the container.
                _shell_tools = ["bash_exec", "read_file", "write_file", "list_files"]
                _existing = list(_cfg_pre.get("available_tools") or [])
                for _t in _shell_tools:
                    if _t not in _existing:
                        _existing.append(_t)
                _cfg_pre["available_tools"] = _existing
                task.config = _cfg_pre
        except Exception as _se:
            ctx.log(f"Sandbox provisioning failed: {_se}", "warning")
            if (task.config or {}).get("sandbox_required"):
                return TaskResult(success=False, error_message=f"Sandbox required but failed: {_se}")

        executor = None
        try:
            executor = ctx.get_agentic_executor()
            cfg = task.config or {}
            mode = str(cfg.get("mode", "normal")).strip().lower()

            if mode == "deep_research":
                cfg.setdefault("max_iterations", max(task.resources.max_iterations, 8))
                cfg.setdefault("max_duration_seconds", 600)
                cfg.setdefault("available_tools", ["memory_search"])
                cfg.setdefault(
                    "resource_policy",
                    {"enabled": True, "prefer_api_for_complex_tasks": True},
                )
                cfg.setdefault(
                    "final_answer_requirements",
                    {"min_length": 120, "must_include": ["Summary"]},
                )

            parallel_cfg = cfg.get("parallel_agents", {})
            if mode == "parallel_discovery" and not parallel_cfg:
                parallel_cfg = {"enabled": True, "count": 3, "max_concurrent": 3}

            if isinstance(parallel_cfg, dict) and parallel_cfg.get("enabled"):
                return await self._execute_agentic_parallel(task, ctx, executor, parallel_cfg)
            return await executor.execute(task)

        except Exception as e:
            import traceback
            ctx.log(
                f"Agentic task {task.id} failed: {e}\n{traceback.format_exc()}", "error"
            )
            if executor is not None:
                session_file = str(executor._session_storage._path(task.id))
            else:
                from app.scheduler.session_storage import SessionStorage
                session_file = str(SessionStorage()._path(task.id))
            return TaskResult(
                success=False,
                output_file=session_file,
                metrics={"session_file": session_file},
                error_message=f"Agentic execution error: {e}",
            )
        finally:
            # Sandbox teardown — always runs whether task succeeded or failed.
            if _sandbox_token is not None:
                from app.scheduler.sandbox.context import _cv_sandbox_handle
                _cv_sandbox_handle.reset(_sandbox_token)
            if _sandbox_handle is not None:
                try:
                    from app.scheduler.sandbox.manager import SandboxManager
                    teardown = (task.config or {}).get("sandbox_teardown", "pause")
                    await SandboxManager.load().release(_sandbox_handle, mode=teardown)
                except Exception as _re:
                    ctx.log(f"Sandbox release failed (non-fatal): {_re}", "warning")

    # ------------------------------------------------------------------
    # Parallel fan-out
    # ------------------------------------------------------------------

    async def _execute_agentic_parallel(
        self, task: Task, ctx: ExecutorContext, executor, parallel_cfg: Dict[str, Any]
    ) -> TaskResult:
        base_config = dict(task.config or {})
        variants = parallel_cfg.get("goal_variants")
        count = int(parallel_cfg.get("count", 0) or 0)
        max_concurrent = int(parallel_cfg.get("max_concurrent", 3) or 3)

        if isinstance(variants, list) and variants:
            goals = [str(v) for v in variants if str(v).strip()]
        else:
            if count <= 0:
                count = 2
            base_goal = str(base_config.get("goal", "")).strip()
            if not base_goal:
                return TaskResult(
                    success=False,
                    error_message="Missing goal for parallel agentic execution",
                )
            goals = [base_goal for _ in range(count)]

        if not goals:
            return TaskResult(
                success=False,
                error_message="No valid goals generated for parallel execution",
            )

        child_base_config = dict(base_config)
        child_base_config.pop("parallel_agents", None)

        from app.scheduler.models import Task as SchedulerTask

        sem = asyncio.Semaphore(max(1, max_concurrent))

        async def _run_variant(idx: int, goal_text: str) -> Dict[str, Any]:
            async with sem:
                child_id = f"{task.id}__p{idx+1}"
                child_cfg = dict(child_base_config)
                child_cfg["goal"] = goal_text
                child_cfg["parallel_parent_task_id"] = task.id
                child_task = SchedulerTask(
                    id=child_id,
                    type=task.type,
                    priority=task.priority,
                    config=child_cfg,
                    resources=task.resources,
                    created_by=task.created_by,
                    description=f"{task.description or task.id} [parallel {idx+1}]",
                )
                result = await executor.execute(child_task)
                return {
                    "variant_index": idx + 1,
                    "task_id": child_id,
                    "goal": goal_text,
                    "success": result.success,
                    "error_message": result.error_message,
                    "output_file": result.output_file,
                    "metrics": result.metrics or {},
                }

        results = await asyncio.gather(
            *[_run_variant(i, goal) for i, goal in enumerate(goals)]
        )

        success_count = sum(1 for r in results if r["success"])
        review_report = self._build_parallel_review_report(ctx, results, parallel_cfg)
        best_task_id = review_report.get("recommended_task_id")
        best_result = next(
            (r for r in results if r.get("task_id") == best_task_id),
            next((r for r in results if r["success"]), results[0]),
        )
        all_final_answers = []
        for r in results:
            metrics = r.get("metrics") or {}
            all_final_answers.append(
                {
                    "task_id": r.get("task_id"),
                    "success": r.get("success"),
                    "final_answer": metrics.get("final_answer"),
                    "error_message": r.get("error_message"),
                    "resource_trace": [
                        {
                            "iteration": it.get("iteration"),
                            "resource": it.get("resource"),
                            "model": it.get("model"),
                            "status": it.get("status"),
                        }
                        for it in (metrics.get("iteration_log") or [])
                    ],
                }
            )

        aggregate_metrics = {
            "mode": "parallel_agents",
            "parent_task_id": task.id,
            "variant_count": len(results),
            "success_count": success_count,
            "failure_count": len(results) - success_count,
            "results": results,
            "final_answers": all_final_answers,
            "review_report": review_report,
            "selected_best_task_id": best_result.get("task_id"),
            "selected_best_answer": (best_result.get("metrics") or {}).get("final_answer"),
        }

        return TaskResult(
            success=success_count > 0,
            output_file=(best_result.get("metrics") or {}).get("session_file")
            or best_result.get("output_file"),
            metrics=aggregate_metrics,
            error_message=None
            if success_count > 0
            else "All parallel agent variants failed",
        )

    # ------------------------------------------------------------------
    # Review report
    # ------------------------------------------------------------------

    def _build_parallel_review_report(
        self,
        ctx: ExecutorContext,
        results: List[Dict[str, Any]],
        parallel_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        review_policy = (
            parallel_cfg.get("review_policy", {}) if isinstance(parallel_cfg, dict) else {}
        )
        weights = {
            "format_compliance": float(review_policy.get("format_compliance", 0.40)),
            "goal_match": float(review_policy.get("goal_match", 0.30)),
            "tool_hygiene": float(review_policy.get("tool_hygiene", 0.15)),
            "latency": float(review_policy.get("latency", 0.10)),
            "cost_tier": float(review_policy.get("cost_tier", 0.05)),
        }

        durations = []
        for r in results:
            metrics = r.get("metrics") or {}
            dur = metrics.get("duration_seconds")
            if isinstance(dur, (int, float)):
                durations.append(float(dur))
        max_dur = max(durations) if durations else 1.0

        rm = ctx.get_resource_manager()
        scored = []
        for r in results:
            metrics = r.get("metrics") or {}
            final_answer = metrics.get("final_answer")
            goal = str(r.get("goal", ""))
            exact_text = self._infer_exact_text_from_goal(goal)
            iteration_log = metrics.get("iteration_log") or []

            format_compliance = 1.0 if r.get("success") and final_answer else 0.0

            if exact_text and isinstance(final_answer, str):
                norm = final_answer.strip().strip('"').strip("'")
                goal_match = 1.0 if norm == exact_text else (0.5 if exact_text in norm else 0.0)
            elif isinstance(final_answer, str) and final_answer.strip():
                goal_match = 1.0 if r.get("success") else 0.3
            else:
                goal_match = 0.0

            total_steps = max(1, len(iteration_log))
            error_steps = sum(1 for i in iteration_log if i.get("status") == "error")
            tool_hygiene = max(0.0, 1.0 - (error_steps / total_steps))

            dur = metrics.get("duration_seconds")
            if isinstance(dur, (int, float)) and max_dur > 0:
                latency = max(0.0, 1.0 - (float(dur) / max_dur))
            else:
                latency = 0.5

            tier_score = 0.5
            if iteration_log:
                rid = iteration_log[0].get("resource")
                res = rm._resources.get(rid) if rid else None
                if res is not None:
                    tier_score = {
                        "free": 1.0,
                        "free_api": 0.8,
                        "paid": 0.2,
                    }.get(res.tier.value, 0.5)

            total = (
                weights["format_compliance"] * format_compliance
                + weights["goal_match"] * goal_match
                + weights["tool_hygiene"] * tool_hygiene
                + weights["latency"] * latency
                + weights["cost_tier"] * tier_score
            )

            scored.append(
                {
                    "task_id": r.get("task_id"),
                    "success": r.get("success"),
                    "score": round(total, 4),
                    "dimensions": {
                        "format_compliance": round(format_compliance, 4),
                        "goal_match": round(goal_match, 4),
                        "tool_hygiene": round(tool_hygiene, 4),
                        "latency": round(latency, 4),
                        "cost_tier": round(tier_score, 4),
                    },
                    "final_answer": final_answer,
                    "error_message": r.get("error_message"),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0] if scored else None

        require_human = bool(review_policy.get("require_human_review", True))
        auto_decide = bool(review_policy.get("auto_decide", False))
        decision_required = require_human or not auto_decide
        recommendation_reason = self._build_parallel_recommendation_reason(best)
        recommended_next_actions = self._build_parallel_next_actions(
            best=best, scored=scored, decision_required=decision_required
        )
        summary = self._build_parallel_summary(
            scored=scored,
            best=best,
            decision_required=decision_required,
            recommendation_reason=recommendation_reason,
        )

        return {
            "policy": {
                "weights": weights,
                "require_human_review": require_human,
                "auto_decide": auto_decide,
            },
            "decision_required": decision_required,
            "recommended_task_id": best.get("task_id") if best else None,
            "recommended_score": best.get("score") if best else None,
            "recommendation_reason": recommendation_reason,
            "recommended_next_actions": recommended_next_actions,
            "summary": summary,
            "ranked_results": scored,
        }

    @staticmethod
    def _build_parallel_recommendation_reason(best: Optional[Dict[str, Any]]) -> str:
        if not best:
            return "No successful variant was available to recommend."
        dims = best.get("dimensions") or {}
        reasons = []
        if dims.get("format_compliance", 0) >= 1.0:
            reasons.append("passed format checks")
        if dims.get("goal_match", 0) >= 1.0:
            reasons.append("matched the requested goal")
        if dims.get("tool_hygiene", 0) >= 1.0:
            reasons.append("showed clean execution with no tool/runtime errors")
        if dims.get("latency", 0) >= 0.5:
            reasons.append("completed faster than competing variants")
        if not reasons:
            reasons.append("achieved the highest overall deterministic score")
        return ", ".join(reasons)

    @staticmethod
    def _build_parallel_next_actions(
        best: Optional[Dict[str, Any]],
        scored: List[Dict[str, Any]],
        decision_required: bool,
    ) -> List[str]:
        actions: List[str] = []
        if best:
            actions.append(
                f"Inspect recommended result from {best.get('task_id')} before proceeding."
            )
        if decision_required:
            actions.append(
                "Human decision required: review ranked_results and approve which variant "
                "should move forward."
            )
        failed = [item for item in scored if not item.get("success")]
        if failed:
            actions.append(
                "Review failed variants to identify reusable corrections or "
                "prompt-contract improvements."
            )
        else:
            actions.append(
                "All variants succeeded; compare quality and latency tradeoffs before selecting one."
            )
        return actions

    @staticmethod
    def _build_parallel_summary(
        scored: List[Dict[str, Any]],
        best: Optional[Dict[str, Any]],
        decision_required: bool,
        recommendation_reason: str,
    ) -> str:
        total = len(scored)
        success_count = sum(1 for item in scored if item.get("success"))
        failure_count = total - success_count

        if not best:
            return (
                f"{total} variants completed with no valid recommendation. "
                f"Successes: {success_count}. Failures: {failure_count}."
            )

        return (
            f"{total} variants completed. Successes: {success_count}. "
            f"Failures: {failure_count}. Recommended: {best.get('task_id')} "
            f"(score {best.get('score')}) because it {recommendation_reason}. "
            f"{'Human decision required.' if decision_required else 'Auto-decision permitted by policy.'}"
        )

    @staticmethod
    def _infer_exact_text_from_goal(goal: str) -> Optional[str]:
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
            raw = text[idx + len(marker):].strip()
            if not raw:
                return None
            raw = raw.splitlines()[0].strip()
            return raw.strip().strip('"').strip("'")
        return None
