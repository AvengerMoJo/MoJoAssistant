"""Supervised coding jobs.  config.action: launch | check | resume | cancel | decision_report | owner_reply | rules_reply.
Library and rules: app/scheduler/coding_jobs.py; calibration: app/scheduler/bonsai_calibration.py;
spec: ~/.memory/research/specs/popo_long_running_job_spec.md"""
# [mojo-integration]
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.scheduler import coding_jobs as cj
from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskPriority, TaskResult, TaskStatus, TaskType

REVIEWER_OUTPUT_LIMIT = 4000  # a thinking model spends most of a small budget before it answers
TERMINAL = ("done", "over_budget", "dead")


class CodingJobHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        action = cfg.get("action")
        try:
            if action == "launch":
                job = await asyncio.to_thread(cj.launch, cfg["spec"])
                ctx.log(f"coding job {job['job_id']} launched on port {job['port']}, branch {job['branch']}, budget {job['budget']} ({job['budget_source']})")
                return TaskResult(success=True, metrics={"job_id": job["job_id"], "branch": job["branch"], "port": job["port"], "budget_source": job["budget_source"]})
            if action == "check":
                return TaskResult(success=True, metrics=await self._check_all(ctx))
            if action == "decision_report":
                return await self._decision_report(cfg, ctx)
            if action == "owner_reply":
                return await asyncio.to_thread(self._owner_reply, cfg)
            if action == "rules_reply":
                return await asyncio.to_thread(self._rules_reply, cfg)
            if action == "resume":
                return await asyncio.to_thread(self._resume, cfg["job_id"], cfg.get("message", ""))
            if action == "cancel":
                return await asyncio.to_thread(self._cancel, cfg["job_id"])
        except (cj.JobError, KeyError) as e:
            ctx.log(f"coding_job {action} failed: {e}", "error")
            return TaskResult(success=False, error_message=f"coding_job {action} failed: {e!r}")
        return TaskResult(success=False, error_message=f"unknown coding_job action: {action!r}")

    # ------------------------------------------------------------------ owner actions

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

    @staticmethod
    def _owner_reply(cfg: dict) -> TaskResult:
        """The owner answered Paul's question: tell the agent, rate the question by the answer, resume."""
        reply = (cfg.get("reply") or cfg.get("ext_agent_reply") or "").strip()
        if not reply:
            return TaskResult(success=False, error_message="empty owner reply")
        job = cj.load_job(cfg["job_id"])
        rating = cj.rate_owner_reply(reply, cfg.get("recommendation", ""))
        oc = cj.client_for(job)
        try:
            oc.prompt(job["session_id"], f"The owner answered the question your PM raised: {reply}\nContinue accordingly.")
        finally:
            oc.close()
        job.update(state="running", continues=0)
        cj.save_job(job)
        cj.log_feedback(job["job_id"], cfg["decided_at"], rating)
        return TaskResult(success=True, metrics={"job_id": job["job_id"], "rating": rating})

    @staticmethod
    def _rules_reply(cfg: dict) -> TaskResult:
        """Accept / reject on Bonsai's weekly proposal to change Paul's escalation rules."""
        reply = (cfg.get("reply") or cfg.get("ext_agent_reply") or "").strip().lower()
        if reply in ("accept", "yes", "y", "approve"):
            cj.add_escalation_rule(cfg["role_id"], cfg["key"], cfg["rule"])
            return TaskResult(success=True, metrics={"message": f"rule added to {cfg['role_id']}.{cfg['key']}"})
        if reply in ("reject", "no", "n", "discard"):
            return TaskResult(success=True, metrics={"message": "proposal rejected; rules unchanged"})
        return TaskResult(success=False, error_message=f"unrecognised reply {reply!r}; expected accept/reject")

    # ------------------------------------------------------------------ weekly Bonsai step

    async def _decision_report(self, cfg: dict, ctx: ExecutorContext) -> TaskResult:
        rep = cj.weekly_report(int(cfg.get("days", 7)))
        if rep["proposal"]:
            week = datetime.now(timezone.utc).strftime("%Y%m%d")
            tid = f"bonsai_rules_paul_{week}"
            task = Task(
                id=tid, type=TaskType.CODING_JOB, priority=TaskPriority.HIGH, status=TaskStatus.WAITING_FOR_INPUT,
                config={"action": "rules_reply", "role_id": "paul", "key": "do_not_escalate_when", "rule": rep["proposal"]},
                description="Bonsai weekly: proposed change to Paul's escalation rules", created_by="system")
            task.pending_question = rep["text"] + "\n\nReply 'accept' to add the rule or 'reject'."
            ctx._scheduler.queue.add(task)
            from app.mcp.adapters.hitl.manager import get_shared_manager
            await get_shared_manager().send_hitl(task_id=tid, question="**Bonsai weekly: Paul's job decisions**\n\n" + rep["text"], choices=["accept", "reject"])
        else:
            await self._notify("Weekly review of Paul's job decisions", rep["text"])
        return TaskResult(success=True, metrics={"decisions": rep["rows"], "asks": rep["asks"], "unnecessary": rep["unnecessary"], "proposal": bool(rep["proposal"])})

    # ------------------------------------------------------------------ the checker

    async def _check_all(self, ctx: ExecutorContext) -> dict:
        summary = {}
        for job in cj.list_jobs(cj.LIVE_STATES):
            if job["state"] == "blocked":
                continue  # waits for the owner's reply/cancel; not re-reviewed
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
                await self._finish(job, state, facts, ctx, entry)
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
            self._remember(ctx, "paul", cj.decision_document(job, state, decision), {"type": "pm_job_decision", "job_id": job["job_id"], "decision": decision["decision"]}, entry)
            notice = await asyncio.to_thread(cj.apply_decision, job, decision, oc)
            if job["state"] == "done" or (job["state"] == "blocked" and decision["decision"] != "ASK_OWNER"):
                await self._finish(job, "done" if job["state"] == "done" else "blocked", facts, ctx, entry)
            if decision["decision"] == "ASK_OWNER":
                await self._ask_owner(job, decision, entry["at"], ctx)
            elif notice:
                await self._notify(f"Job {job['job_id']}", notice)
            cj.save_job(job)
            return f"{state} -> {decision['decision']}"
        finally:
            oc.close()

    async def _finish(self, job: dict, state: str, facts: dict, ctx: ExecutorContext, entry: dict) -> None:
        out = await asyncio.to_thread(cj.finish, job, state, facts, getattr(ctx, "_memory_service", None))
        entry["end_reason"] = out["reason"]
        if out["errors"]:
            entry["finish_errors"] = out["errors"]
            ctx.log(f"coding job {job['job_id']}: learning writes failed: {out['errors']}", "error")

    @staticmethod
    def _remember(ctx: ExecutorContext, role: str, doc: str, meta: dict, entry: dict) -> None:
        try:
            ctx._memory_service.add_to_knowledge_base(doc, {**meta, "role": role}, role_id=role)
        except Exception as e:  # Log must not vanish: record the failure on the check itself
            entry["memory_error"] = str(e)[:200]
            ctx.log(f"coding job memory write failed: {e}", "error")

    async def _ask_owner(self, job: dict, decision: dict, decided_at: str, ctx: ExecutorContext) -> None:
        tid = f"jobask_{job['job_id']}_{int(time.time())}"
        task = Task(
            id=tid, type=TaskType.CODING_JOB, priority=TaskPriority.HIGH, status=TaskStatus.WAITING_FOR_INPUT,
            config={"action": "owner_reply", "job_id": job["job_id"], "decided_at": decided_at, "recommendation": decision.get("recommendation", "")},
            description=f"Paul needs the owner on job {job['job_id']}", created_by="system")
        question = (f"**Job {job['job_id']}** — Paul needs you.\n{decision['message'] or decision['reason']}\n"
                    f"Paul would choose: {decision.get('recommendation') or '(no recommendation)'}")
        task.pending_question = question
        ctx._scheduler.queue.add(task)
        from app.mcp.adapters.hitl.manager import get_shared_manager
        choices = decision.get("options") or ([decision["recommendation"]] if decision.get("recommendation") else [])
        await get_shared_manager().send_hitl(task_id=tid, question=question, choices=choices)

    async def _review(self, job, facts, state, unanswered, ctx) -> dict:
        from app.llm.unified_client import UnifiedLLMClient
        from app.scheduler.resource_pool import ResourceTier
        rm = ctx.get_resource_manager()
        allowed = set(cj.reviewer_resources())
        skip = [rid for rid in rm._resources if rid not in allowed]
        res = rm.acquire(tier_preference=[ResourceTier.FREE_API, ResourceTier.FREE, ResourceTier.PAID], exclude_ids=skip,
                         min_context=16000, max_data_scope="third_party")
        if res is None:
            raise cj.JobError(f"none of the configured reviewer resources is available: {sorted(allowed)}")
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
