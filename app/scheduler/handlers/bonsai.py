"""BRIDLE Bonsai handler — role growth cycle (one-on-one → drift → snapshot → HITL).

This is the scheduler seam for the BRIDLE growth system.  Dreaming owns memory
refinement; this handler owns personality evolution and owner validation.

Two modes dispatched via config["mode"]:
  "growth"      — weekly run: collect signals, compute drift, create snapshot, send HITL
  "pin_review"  — owner reply: pin or discard the candidate snapshot
"""
# [mojo-integration]
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath
from app.scheduler.bonsai import BonsaiEngine, GrowthSnapshot, SnapshotManager
from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult, TaskStatus, TaskType

logger = logging.getLogger(__name__)

_WATERMARK_FILE = "growth_watermark.json"


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------

def _read_watermark(role_id: str) -> Dict[str, Any]:
    path = Path(get_memory_subpath("roles")) / role_id / _WATERMARK_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_watermark(role_id: str, data: Dict[str, Any]) -> None:
    path = Path(get_memory_subpath("roles")) / role_id / _WATERMARK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Signal extraction (v1 — keyword heuristic from chat sessions)
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS = [
    "exactly right", "perfect", "that's what i want", "keep doing", "love how",
    "this is great", "well done", "exactly what i needed",
]
_CORRECTION_KEYWORDS = [
    "too cautious", "too aggressive", "don't do that", "stop", "instead",
    "not what i wanted", "wrong", "incorrect", "change how you",
]
_CALIBRATION_KEYWORDS = [
    "always", "when you see", "for investors", "lead with", "focus on",
    "prioritize", "whenever", "make sure to", "remember to",
]

_DIMENSION_HINTS: Dict[str, List[str]] = {
    "core_values": ["honest", "evidence", "rigorous", "accurate", "transparent"],
    "cognitive_style": ["analytical", "structured", "systematic", "detail", "precise"],
    "social_orientation": ["audience", "investor", "stakeholder", "team", "framing"],
    "emotional_reaction": ["cautious", "aggressive", "assertive", "calm", "direct"],
    "adaptability": ["flexible", "adapt", "adjust", "when uncertain", "escalate"],
}


def _extract_signals_from_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keyword heuristic v1 — extract growth signals from chat exchanges."""
    signals = []
    for session in sessions:
        for exchange in session.get("exchanges", []):
            user_msg = (exchange.get("user") or "").lower()

            signal_type = None
            if any(kw in user_msg for kw in _POSITIVE_KEYWORDS):
                signal_type = "reinforcement"
                direction = "up"
                strength = 0.4
            elif any(kw in user_msg for kw in _CORRECTION_KEYWORDS):
                signal_type = "correction"
                direction = "down"
                strength = 0.6
            elif any(kw in user_msg for kw in _CALIBRATION_KEYWORDS):
                signal_type = "calibration"
                direction = "up"
                strength = 0.5

            if signal_type is None:
                continue

            # Find the most likely dimension
            best_dim = "social_orientation"  # default for calibration
            best_count = 0
            for dim, hints in _DIMENSION_HINTS.items():
                count = sum(1 for h in hints if h in user_msg)
                if count > best_count:
                    best_count = count
                    best_dim = dim

            signals.append({
                "dimension": best_dim,
                "direction": direction,
                "strength": strength,
                "reason": f"{signal_type}: {user_msg[:120]}",
                "session_id": session.get("session_id", ""),
            })

    return signals


# ---------------------------------------------------------------------------
# Session collector
# ---------------------------------------------------------------------------

def _collect_owner_sessions(role_id: str, since_iso: Optional[str]) -> List[Dict[str, Any]]:
    """Return OWNER_ONE_ON_ONE sessions for the role updated after since_iso."""
    chat_dir = Path(get_memory_subpath("roles")) / role_id / "chat_history"
    if not chat_dir.exists():
        return []

    sessions = []
    for f in sorted(chat_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("session_type") != "owner_one_on_one":
            continue
        if since_iso:
            last_active = data.get("last_active") or data.get("created_at") or ""
            if last_active and last_active <= since_iso:
                continue
        if data.get("exchanges"):
            sessions.append(data)

    return sessions


# ---------------------------------------------------------------------------
# BonsaiGrowthHandler
# ---------------------------------------------------------------------------

class BonsaiGrowthHandler(TaskHandler):
    """Weekly growth run: collect signals → compute drift → create snapshot → HITL."""

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        mode = cfg.get("mode", "growth")

        if mode == "pin_review":
            return await BonsaiPinReviewHandler().execute(task, ctx)

        return await self._run_growth(task, cfg, ctx)

    async def _run_growth(
        self, task: Task, cfg: Dict[str, Any], ctx: ExecutorContext
    ) -> TaskResult:
        notify_owner = bool(cfg.get("notify_owner", True))
        role_ids: List[str] = cfg.get("roles") or self._discover_roles()

        summaries = []
        for role_id in role_ids:
            try:
                summary = await self._process_role(role_id, notify_owner, task.id, ctx)
                summaries.append(summary)
            except Exception as e:
                logger.error(f"[bonsai] Growth run failed for role {role_id}: {e}")
                summaries.append({"role_id": role_id, "status": "error", "error": str(e)})

        roles_with_snapshots = sum(1 for s in summaries if s.get("snapshot_version"))
        ctx.log(
            f"Bonsai growth run complete: {len(summaries)} roles, "
            f"{roles_with_snapshots} new snapshots"
        )
        return TaskResult(
            success=True,
            metrics={"roles": summaries, "roles_processed": len(summaries)},
        )

    async def _process_role(
        self, role_id: str, notify_owner: bool, task_id: str, ctx: ExecutorContext
    ) -> Dict[str, Any]:
        watermark = _read_watermark(role_id)
        since_iso = watermark.get("last_growth_run")

        sessions = _collect_owner_sessions(role_id, since_iso)
        if not sessions:
            return {"role_id": role_id, "status": "no_new_sessions", "snapshot_version": None}

        signals = _extract_signals_from_sessions(sessions)
        engine = BonsaiEngine(role_id)
        sm = SnapshotManager(role_id)
        old_snapshot = sm.get_pinned()

        # Current dimensions: from pinned snapshot or role file
        if old_snapshot:
            current_dims = old_snapshot.dimensions
            current_prompt = old_snapshot.system_prompt
        else:
            current_dims, current_prompt = self._dims_from_role(role_id)

        new_dims = engine.compute_dimension_drift(current_dims, signals) if signals else current_dims
        validation = engine.validate_growth(current_dims, new_dims)
        if not validation["valid"]:
            logger.warning(f"[bonsai] Growth validation issues for {role_id}: {validation['issues']}")

        new_snapshot = engine.create_snapshot(
            dimensions=new_dims,
            system_prompt=current_prompt,
            trigger="owner_one_on_one",
        )

        signal_summaries = [s["reason"] for s in signals[:5]]
        report = engine.generate_growth_report(old_snapshot, new_dims, signals=signal_summaries)

        _write_watermark(role_id, {
            "last_growth_run": datetime.now().isoformat(),
            "pending_version": new_snapshot.version,
            "sessions_processed": [s.get("session_id") for s in sessions],
        })

        if notify_owner:
            await self._send_hitl(role_id, new_snapshot.version, report, task_id, ctx)

        return {
            "role_id": role_id,
            "status": "snapshot_created",
            "snapshot_version": new_snapshot.version,
            "signals_found": len(signals),
            "sessions_processed": len(sessions),
            "validation_warnings": validation.get("warnings", []),
        }

    async def _send_hitl(
        self, role_id: str, version: int, report: str, parent_task_id: str, ctx: ExecutorContext
    ) -> None:
        """Dispatch a bonsai_pin_review task and send HITL to owner."""
        from app.scheduler.models import TaskPriority
        from app.scheduler.queue import TaskQueue

        review_task_id = f"bonsai_pin_review_{role_id}_v{version}"
        review_task = Task(
            id=review_task_id,
            type=TaskType.GROWTH,
            priority=TaskPriority.HIGH,
            status=TaskStatus.WAITING_FOR_INPUT,
            config={
                "mode": "pin_review",
                "role_id": role_id,
                "pending_version": version,
                "growth_report": report,
                "parent_task_id": parent_task_id,
            },
            description=f"Bonsai growth approval for {role_id} v{version}",
            created_by="system",
        )
        review_task.pending_question = (
            f"Growth snapshot v{version} ready for {role_id}.\n"
            f"Reply 'accept' to pin or 'reject' to discard."
        )

        scheduler = ctx._scheduler
        if scheduler and hasattr(scheduler, "queue"):
            scheduler.queue.add(review_task)

        try:
            from app.mcp.adapters.hitl.manager import HITLManager
            mgr = HITLManager.load_from_config()
            if scheduler:
                mgr.set_scheduler(scheduler)
            short_report = report[:1200] + ("\n…(truncated)" if len(report) > 1200 else "")
            await mgr.send_hitl(
                task_id=review_task_id,
                question=f"**Bonsai Growth Report — {role_id} v{version}**\n\n{short_report}",
                options=["accept", "reject"],
            )
        except Exception as e:
            logger.warning(f"[bonsai] HITL send failed for {role_id} v{version}: {e}")

    def _discover_roles(self) -> List[str]:
        """Return role IDs that have a growth_snapshots directory."""
        roles_dir = Path(get_memory_subpath("roles"))
        if not roles_dir.exists():
            return []
        return [
            d.name for d in roles_dir.iterdir()
            if d.is_dir() and (d / "growth_snapshots").exists()
        ]

    def _dims_from_role(self, role_id: str):
        """Load base dimensions from role file, falling back to neutral defaults."""
        try:
            from app.roles.role_manager import RoleManager
            role = RoleManager().get(role_id) or {}
            dims = role.get("dimensions") or {}
            prompt = role.get("system_prompt") or ""
            if dims:
                return dims, prompt
        except Exception:
            pass
        defaults = {
            dim: {"score": 75, "summary": ""}
            for dim in ("core_values", "cognitive_style", "social_orientation",
                        "emotional_reaction", "adaptability")
        }
        return defaults, ""


# ---------------------------------------------------------------------------
# BonsaiPinReviewHandler
# ---------------------------------------------------------------------------

class BonsaiPinReviewHandler(TaskHandler):
    """Handle owner Accept/Reject reply for a pending growth snapshot."""

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        role_id = cfg.get("role_id", "")
        version = int(cfg.get("pending_version") or 0)
        reply = (cfg.get("reply") or cfg.get("ext_agent_reply") or "").strip().lower()

        if not role_id or not version:
            return TaskResult(
                success=False,
                error_message="Missing role_id or pending_version in task config",
            )

        if reply in ("accept", "yes", "y", "approve", "pin"):
            ok = SnapshotManager(role_id).pin_snapshot(version)
            if ok:
                watermark = _read_watermark(role_id)
                watermark.pop("pending_version", None)
                watermark["pinned_version"] = version
                watermark["pinned_at"] = datetime.now().isoformat()
                _write_watermark(role_id, watermark)
                msg = f"Snapshot v{version} pinned for {role_id}."
                logger.info(f"[bonsai] {msg}")
            else:
                msg = f"pin_snapshot({version}) failed for {role_id} — version file missing."
                logger.warning(f"[bonsai] {msg}")
            return TaskResult(success=ok, metrics={"message": msg})

        elif reply in ("reject", "no", "n", "discard"):
            watermark = _read_watermark(role_id)
            watermark.pop("pending_version", None)
            watermark["rejected_version"] = version
            watermark["rejected_at"] = datetime.now().isoformat()
            _write_watermark(role_id, watermark)
            msg = f"Snapshot v{version} rejected for {role_id}. Previous state preserved."
            logger.info(f"[bonsai] {msg}")
            return TaskResult(success=True, metrics={"message": msg})

        else:
            msg = f"Unrecognised reply '{reply}' for bonsai pin review. Expected accept/reject."
            logger.warning(f"[bonsai] {msg}")
            # Stay WAITING_FOR_INPUT so owner can reply again
            task.status = TaskStatus.WAITING_FOR_INPUT
            return TaskResult(success=False, error_message=msg)
