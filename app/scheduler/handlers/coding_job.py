"""Supervised coding jobs.  config.action: launch | check | resume | cancel.
Library and rules: app/scheduler/coding_jobs.py; spec: ~/.memory/research/specs/popo_long_running_job_spec.md"""
# [mojo-integration]
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.scheduler import coding_jobs as cj
from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult

REVIEWER_OUTPUT_LIMIT = 1500


class CodingJobHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        action = cfg.get("action")
        try:
            if action == "launch":
                job = await asyncio.to_thread(cj.launch, cfg["spec"])
                ctx.log(f"coding job {job['job_id']} launched on port {job['port']}, branch {job['branch']}")
                return TaskResult(success=True, metrics={"job_id": job["job_id"], "branch": job["branch"], "port": job["port"]})
            if action == "check":
                return TaskResult(success=True, metrics=await self._check_all(ctx))
            if action == "resume":
                return await asyncio.to_thread(self._resume, cfg["job_id"], cfg.get("message", ""))
            if action == "cancel":
                return await asyncio.to_thread(self._cancel, cfg["job_id"])
        except (cj.JobError, KeyError) as e:
            ctx.log(f"coding_job {action} failed: {e}", "error")
            return TaskResult(success=False, error_message=f"coding_job {action} failed: {e!r}")
        return TaskResult(success=False, error_message=f"unknown coding_job action: {action!r}")

    # ------------------------------------------------------------------

    @staticmethod
    def _resume(job_id: str, message: str) -> TaskResult:
        job = cj.load_job(job_id)
        oc = cj.client_for(job)
        try:
            oc.prompt(job["session_id"], message or "The owner says: carry on.")
        finally:
            oc.close()
        job.update(state="running", continues=0)
        cj.save_job(job)
        return TaskResult(success=True, metrics={"job_id": job_id, "state": "running"})

    @staticmethod
    def _cancel(job_id: str) -> TaskResult:
        job = cj.load_job(job_id)
        cj.stop_server(job)
        job["state"] = "cancelled"
        cj.save_job(job)
        return TaskResult(success=True, metrics={"job_id": job_id, "state": "cancelled"})

    async def _check_all(self, ctx: ExecutorContext) -> dict:
        summary = {}
        for job in cj.list_jobs(cj.LIVE_STATES):
            if job["state"] == "blocked":
                continue  # waits for the owner's resume/cancel; not re-reviewed
            try:
                summary[job["job_id"]] = await self._check_one(job, ctx)
            except Exception as e:
                ctx.log(f"coding job {job['job_id']} check failed: {e}", "error")
                job["checks"].append({"at": cj.now_iso(), "error": f"check failed: {e}"})
                cj.save_job(job)
                summary[job["job_id"]] = f"error: {e}"
        return summary

    async def _check_one(self, job: dict, ctx: ExecutorContext) -> str:
        oc = cj.client_for(job)
        try:
            facts = await asyncio.to_thread(cj.collect_facts, job, oc)
            unanswered = await asyncio.to_thread(cj.auto_permissions, job, facts, oc) if facts["server_up"] else []
            state = "blocked" if unanswered else cj.classify(job, facts)
            job["last_check_at"] = cj.now_iso()
            entry = {"at": job["last_check_at"], "state": state, "facts": {k: v for k, v in facts.items() if k not in ("status_md", "diff_stat", "pending_permissions")}}
            job["checks"] = (job["checks"] + [entry])[-60:]
            if state == "running":
                job["state"] = "running"
                cj.save_job(job)
                return "running"
            if state in ("over_budget", "dead"):
                job["state"] = state
                await asyncio.to_thread(cj.stop_server, job)
                cj.save_job(job)
                await self._notify(f"Job {job['job_id']} {state}", f"{state}: branch {job['branch']}, {facts['commits']} commits, PR {facts['pr_url']}.")
                return state
            # stalled / blocked / done: Paul reviews, but not more than once per gap
            reviewed = [c for c in job["checks"] if c.get("review")]
            if reviewed and state == "stalled":
                last = datetime.fromisoformat(reviewed[-1]["at"])
                if (datetime.now(timezone.utc) - last).total_seconds() < cj.CHECK_REVIEW_GAP_MIN * 60:
                    job["state"] = state
                    cj.save_job(job)
                    return "stalled (review pending)"
            decision = await self._review(job, facts, state, unanswered, ctx)
            entry["review"] = decision
            cj.log_decision(job, state, decision)
            notice = await asyncio.to_thread(cj.apply_decision, job, decision, oc)
            cj.save_job(job)
            if notice:
                await self._notify(f"Job {job['job_id']}", notice)
            return f"{state} -> {decision['decision']}"
        finally:
            oc.close()

    async def _review(self, job, facts, state, unanswered, ctx) -> dict:
        from app.llm.unified_client import UnifiedLLMClient
        rm = ctx.get_resource_manager()
        res = rm.acquire(tier_preference=["free_api", "free"], min_context=16000, max_data_scope="third_party")
        if res is None:
            raise cj.JobError("no pool resource can serve the reviewer")
        cfg = {"base_url": res.base_url, "model": res.model, "api_key": res.api_key, "provider": res.provider,
               "output_limit": REVIEWER_OUTPUT_LIMIT, "message_format": "openai"}
        t0 = time.time()
        async with rm.slot(res.id, owner="coding_job_review", max_wait_s=60):
            data = await UnifiedLLMClient().call_async(
                messages=[{"role": "user", "content": cj.review_prompt(job, facts, state, unanswered)}],
                resource_config=cfg, model_override=res.model)
        rm.record_usage(res.id, success=True, token_usage=data.get("usage"), model_served=res.model,
                        duration_ms=(time.time() - t0) * 1000, task_class="coding_job.review")
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return {**cj.parse_decision(text), "model": res.model}

    @staticmethod
    async def _notify(title: str, body: str) -> None:
        from app.mcp.adapters.hitl.manager import get_shared_manager
        await get_shared_manager().send_notification(title=title, body=body)
