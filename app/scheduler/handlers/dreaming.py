"""Dreaming task handler — memory consolidation via the ABCD pipeline."""
# [mojo-integration]
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult
from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)


class DreamingHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        ctx.log(f"Dreaming task {task.id} - processing conversation")

        try:
            mode = task.config.get("mode", "conversation")
            conversation_id = task.config.get("conversation_id") or (
                task.config.get("doc_id") if mode == "document" else None
            )
            conversation_text = task.config.get("conversation_text")
            quality_level = task.config.get("quality_level", "basic")
            automatic = bool(task.config.get("automatic", False))
            enforce_off_peak = bool(task.config.get("enforce_off_peak", automatic))
            off_peak_start = task.config.get("off_peak_start", "01:00")
            off_peak_end = task.config.get("off_peak_end", "05:00")

            if enforce_off_peak and not self._is_within_off_peak(off_peak_start, off_peak_end):
                return TaskResult(
                    success=True,
                    metrics={
                        "skipped": True,
                        "reason": "outside_off_peak_window",
                        "off_peak_start": off_peak_start,
                        "off_peak_end": off_peak_end,
                        "executed_at": datetime.now().isoformat(),
                    },
                )

            if automatic and (not conversation_id or not conversation_text):
                auto_input = self._build_automatic_dreaming_input(task.config)
                if auto_input is None:
                    return TaskResult(
                        success=True,
                        metrics={
                            "skipped": True,
                            "reason": "no_recent_conversation_data",
                            "executed_at": datetime.now().isoformat(),
                        },
                    )
                conversation_id = auto_input["conversation_id"]
                conversation_text = auto_input["conversation_text"]
                auto_metadata = auto_input.get("metadata", {})
            else:
                auto_metadata = {}

            if not conversation_id or not conversation_text:
                return TaskResult(
                    success=False,
                    error_message="Missing conversation_id or conversation_text in task config",
                )

            metadata = {**task.config.get("metadata", {}), **auto_metadata}

            if mode == "document":
                from app.services.storage_factory import resolve_storage_backend
                role_id = task.config.get("role_id", "unknown")
                storage_path = (
                    Path(get_memory_subpath("roles")) / role_id / "knowledge_units"
                )
                pipeline = ctx.get_dreaming_pipeline(quality_level)
                pipeline.storage = resolve_storage_backend(storage_path=storage_path)

                doc_id = task.config.get("doc_id") or conversation_id
                results = await pipeline.process_document(
                    doc_id=doc_id,
                    document_text=conversation_text,
                    metadata=metadata,
                )

                if results.get("status") == "success":
                    ku_stage = results["stages"]["knowledge_units"]
                    return TaskResult(
                        success=True,
                        metrics={
                            "mode": "document",
                            "doc_id": doc_id,
                            "knowledge_units_count": ku_stage["count"],
                            "total_links": ku_stage["total_links"],
                            "quality_level": quality_level,
                            "role_id": role_id,
                        },
                    )
                else:
                    return TaskResult(
                        success=False,
                        error_message=results.get(
                            "error", "Unknown error during document dreaming"
                        ),
                    )

            if mode == "chat_bridge":
                return await self._execute_chat_bridge(task, ctx, quality_level)

            if mode == "relationship_update":
                return await self._execute_relationship_update(task, ctx)

            pipeline = ctx.get_dreaming_pipeline(quality_level)
            conv_role_id = task.config.get("role_id")
            if conv_role_id:
                try:
                    from app.services.storage_factory import resolve_storage_backend
                    role_storage_path = (
                        Path(get_memory_subpath("roles")) / conv_role_id / "knowledge_units"
                    )
                    pipeline.storage = resolve_storage_backend(storage_path=role_storage_path)
                except Exception as _e:
                    ctx.log(
                        f"Could not set role-scoped storage for dreaming: {_e}", "warning"
                    )

            results = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata=metadata,
            )

            if results.get("status") == "success":
                archive = results["stages"]["D_archive"]
                archive_path = archive.get("storage_location") or archive.get("path", "")
                metrics = {
                    "b_chunks_count": results["stages"]["B_chunks"]["count"],
                    "c_clusters_count": results["stages"]["C_clusters"]["count"],
                    "quality_level": quality_level,
                    "archive_path": archive_path,
                    "automatic": automatic,
                }

                if ctx._memory_service:
                    indexed = self._index_clusters_to_knowledge_base(
                        ctx=ctx,
                        pipeline=pipeline,
                        conversation_id=conversation_id,
                        role_id=conv_role_id,
                        source=task.config.get("metadata", {}).get("source", "dreaming"),
                    )
                    metrics["clusters_indexed"] = indexed

                if task.config.get("distill_inbox", False):
                    try:
                        from datetime import date, timedelta
                        from app.dreaming.inbox_distillation import run_inbox_distillation
                        from app.mcp.adapters.event_log import EventLog
                        target_date = date.today() - timedelta(days=1)
                        event_log = EventLog()
                        inbox_result = await run_inbox_distillation(
                            target_date=target_date,
                            event_log=event_log,
                            pipeline=pipeline,
                            quality_level=quality_level,
                        )
                        metrics["inbox_distillation"] = inbox_result.get("status", "unknown")
                        ctx.log(
                            f"Inbox distillation: {inbox_result.get('status')} for {target_date}"
                        )
                    except Exception as e:
                        ctx.log(f"Inbox distillation failed (non-fatal): {e}", "warning")
                        metrics["inbox_distillation"] = "error"

                return TaskResult(
                    success=True,
                    output_file=archive_path,
                    metrics=metrics,
                )
            else:
                return TaskResult(
                    success=False,
                    error_message=results.get("error", "Unknown error during dreaming"),
                )

        except Exception as e:
            ctx.log(f"Dreaming task {task.id} failed: {e}", "error")
            return TaskResult(
                success=False, error_message=f"Dreaming execution error: {e}"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _index_clusters_to_knowledge_base(
        self,
        ctx: ExecutorContext,
        pipeline,
        conversation_id: str,
        role_id: Optional[str],
        source: str = "dreaming",
    ) -> int:
        indexed = 0
        try:
            archive = pipeline.get_archive(conversation_id)
            if not archive:
                return 0

            clusters = archive.get("c_clusters", [])
            knowledge_units = archive.get("knowledge_units", [])

            import inspect as _inspect
            sig = _inspect.signature(ctx._memory_service.add_to_knowledge_base)
            supports_role_id = "role_id" in sig.parameters

            def _store(content: str, meta: dict) -> None:
                if supports_role_id:
                    ctx._memory_service.add_to_knowledge_base(content, meta, role_id=role_id)
                else:
                    ctx._memory_service.add_to_knowledge_base(content, meta)

            for cluster in clusters:
                content = (cluster.get("content") or cluster.get("theme") or "").strip()
                if not content or len(content) < 20:
                    continue
                meta = {
                    "type": "dreaming_cluster",
                    "source": source,
                    "conversation_id": conversation_id,
                    "cluster_type": cluster.get("cluster_type", "unknown"),
                    "role_id": role_id or "unknown",
                }
                _store(content, meta)
                indexed += 1

            for unit in knowledge_units:
                content = (unit.get("content") or unit.get("fact") or "").strip()
                if not content or len(content) < 20:
                    continue
                meta = {
                    "type": "dreaming_knowledge_unit",
                    "source": source,
                    "conversation_id": conversation_id,
                    "role_id": role_id or "unknown",
                }
                _store(content, meta)
                indexed += 1

            if indexed:
                ctx.log(
                    f"Indexed {indexed} dreaming clusters into knowledge base (role={role_id})"
                )
        except Exception as e:
            ctx.log(f"Cluster indexing failed (non-fatal): {e}", "warning")
        return indexed

    async def _execute_chat_bridge(
        self,
        task: Task,
        ctx: ExecutorContext,
        quality_level: str,
    ) -> TaskResult:
        """Process new chat sessions through the dreaming pipeline (Gap 4).

        Scans all roles under ~/.memory/roles/ for unprocessed chat sessions,
        converts them to conversation text, and runs them through the ABCD
        pipeline.  Results are indexed into the role's knowledge store so
        _orient_from_memory can retrieve them at next task start.

        Watermark tracking at ~/.memory/roles/{role_id}/chat_dream_watermark.json
        prevents re-processing already-dreamed sessions.
        """
        roles_dir = Path(get_memory_subpath("roles"))
        if not roles_dir.is_dir():
            return TaskResult(
                success=True,
                metrics={"skipped": True, "reason": "no_roles_dir"},
            )

        total_sessions = 0
        total_indexed = 0
        roles_processed = 0
        errors: list[str] = []

        for role_dir in sorted(roles_dir.iterdir()):
            if not role_dir.is_dir():
                continue
            role_id = role_dir.name
            chat_dir = role_dir / "chat_history"
            if not chat_dir.is_dir():
                continue

            watermark_path = role_dir / "chat_dream_watermark.json"
            watermark = self._load_watermark(watermark_path)
            processed_ids = set(watermark.get("processed_session_ids", []))

            session_files = sorted(chat_dir.glob("*.json"))
            new_sessions = [
                f for f in session_files
                if f.stem not in processed_ids
            ]

            if not new_sessions:
                continue

            roles_processed += 1
            # Create a fresh pipeline per role to avoid shared storage mutation
            pipeline = ctx.get_dreaming_pipeline(quality_level)
            try:
                from app.services.storage_factory import resolve_storage_backend
                role_storage_path = role_dir / "knowledge_units"
                pipeline = ctx.get_dreaming_pipeline(quality_level)
                pipeline.storage = resolve_storage_backend(storage_path=role_storage_path)
            except Exception as e:
                ctx.log(f"Chat bridge: could not set role storage for {role_id}: {e}", "warning")

            for session_file in new_sessions:
                try:
                    session_data = json.loads(session_file.read_text(encoding="utf-8"))
                except Exception as e:
                    errors.append(f"{session_file.name}: {e}")
                    continue

                exchanges = session_data.get("exchanges", [])
                if len(exchanges) < 2:
                    continue

                lines = []
                for ex in exchanges:
                    user_msg = (ex.get("user") or "").strip()
                    asst_msg = (ex.get("assistant") or "").strip()
                    if user_msg:
                        lines.append(f"[user] {user_msg}")
                    if asst_msg:
                        lines.append(f"[{role_id}] {asst_msg}")

                if not lines:
                    continue

                conversation_text = "\n".join(lines)
                conversation_id = f"chat_bridge_{session_file.stem}"

                metadata = {
                    "source": "chat_bridge",
                    "role_id": role_id,
                    "session_file": str(session_file),
                    "exchange_count": len(exchanges),
                    "bridged_at": datetime.now().isoformat(),
                    "original_text": conversation_text,
                }

                results = await pipeline.process_conversation(
                    conversation_id=conversation_id,
                    conversation_text=conversation_text,
                    metadata=metadata,
                )

                if results.get("status") == "success":
                    total_sessions += 1
                    if ctx._memory_service:
                        indexed = self._index_clusters_to_knowledge_base(
                            ctx=ctx,
                            pipeline=pipeline,
                            conversation_id=conversation_id,
                            role_id=role_id,
                            source="chat_bridge",
                        )
                        total_indexed += indexed
                else:
                    err = results.get("error", "unknown error")
                    errors.append(f"{session_file.name}: {err}")

                processed_ids.add(session_file.stem)
                # Write watermark after each session for exactly-once processing
                self._save_watermark(watermark_path, {
                    "last_processed_at": datetime.now().isoformat(),
                    "processed_session_ids": sorted(processed_ids),
                })

            # Final watermark update (redundant but ensures consistency)
            self._save_watermark(watermark_path, {
                "last_processed_at": datetime.now().isoformat(),
                "processed_session_ids": sorted(processed_ids),
            })

        metrics = {
            "mode": "chat_bridge",
            "roles_processed": roles_processed,
            "sessions_dreamed": total_sessions,
            "clusters_indexed": total_indexed,
            "quality_level": quality_level,
            "errors": errors,
            "error_count": len(errors),
        }
        if errors:
            ctx.log(f"Chat bridge completed with {len(errors)} errors", "warning")

        return TaskResult(success=True, metrics=metrics)

    @staticmethod
    def _load_watermark(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _save_watermark(path: Path, data: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save chat dream watermark: {e}")

    async def _execute_relationship_update(
        self,
        task: Task,
        ctx: ExecutorContext,
    ) -> TaskResult:
        """Analyze task history and update owner profile assistant_relationships.

        Reads recent task reports for each role, identifies focus areas and
        interaction patterns, and updates the owner profile's
        assistant_relationships field accordingly.  Authored values are
        preserved as seeds; this only adds or strengthens focus areas that
        appear consistently in task outcomes.
        """
        owner_path = Path(get_memory_subpath("owner_profile.json"))
        if not owner_path.exists():
            return TaskResult(
                success=True,
                metrics={"skipped": True, "reason": "no_owner_profile"},
            )

        try:
            owner_profile = json.loads(owner_path.read_text(encoding="utf-8"))
        except Exception as e:
            return TaskResult(success=False, error_message=f"Failed to read owner profile: {e}")

        relationships = owner_profile.get("assistant_relationships", {})
        roles_dir = Path(get_memory_subpath("roles"))
        if not roles_dir.is_dir():
            return TaskResult(
                success=True,
                metrics={"skipped": True, "reason": "no_roles_dir"},
            )

        updated_roles: list[str] = []

        for role_dir in sorted(roles_dir.iterdir()):
            if not role_dir.is_dir():
                continue
            role_id = role_dir.name

            # Read task history
            task_history_dir = role_dir / "task_history"
            if not task_history_dir.is_dir():
                continue

            recent_reports = []
            for report_file in sorted(task_history_dir.glob("*.json"), reverse=True)[:20]:
                try:
                    report = json.loads(report_file.read_text(encoding="utf-8"))
                    recent_reports.append(report)
                except Exception:
                    continue

            if not recent_reports:
                continue

            # Analyze task goals to extract focus patterns
            focus_counts: Dict[str, int] = {}
            for report in recent_reports:
                goal = (report.get("goal") or "").lower()
                final_answer = (report.get("final_answer") or "").lower()
                combined = f"{goal} {final_answer}"

                # Count topic keywords
                topic_keywords = {
                    "analysis": ["analyze", "analysis", "compare", "evaluate", "assess"],
                    "research": ["research", "investigate", "find", "search", "study"],
                    "implementation": ["implement", "build", "create", "code", "write"],
                    "review": ["review", "audit", "check", "validate", "verify"],
                    "infrastructure": ["infrastructure", "server", "deploy", "config", "system"],
                    "security": ["security", "vulnerability", "threat", "protect", "safe"],
                    "testing": ["test", "spec", "coverage", "assert", "validate"],
                    "documentation": ["document", "explain", "describe", "guide", "readme"],
                    "debugging": ["debug", "fix", "error", "issue", "bug", "troubleshoot"],
                    "design": ["design", "architect", "plan", "structure", "pattern"],
                }

                for topic, keywords in topic_keywords.items():
                    if any(kw in combined for kw in keywords):
                        focus_counts[topic] = focus_counts.get(topic, 0) + 1

            if not focus_counts:
                continue

            # Get top focus areas (appearing in 20%+ of tasks)
            threshold = max(2, len(recent_reports) * 0.2)
            top_focus = [
                topic for topic, count in sorted(focus_counts.items(), key=lambda x: -x[1])
                if count >= threshold
            ][:4]

            if not top_focus:
                continue

            # Update or create relationship entry
            existing = relationships.get(role_id, {})
            existing_focus = set(existing.get("focus", []))
            merged_focus = sorted(set(top_focus) | existing_focus)[:6]

            if set(merged_focus) != existing_focus:
                relationships[role_id] = {
                    "relationship": existing.get("relationship", f"{role_id} assistant"),
                    "focus": merged_focus,
                    "last_analyzed": datetime.now().isoformat(),
                    "tasks_analyzed": len(recent_reports),
                }
                updated_roles.append(role_id)

        if updated_roles:
            owner_profile["assistant_relationships"] = relationships
            owner_profile["updated_at"] = datetime.now().isoformat()
            owner_path.write_text(
                json.dumps(owner_profile, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            ctx.log(f"Updated assistant_relationships for: {', '.join(updated_roles)}")

        return TaskResult(
            success=True,
            metrics={
                "mode": "relationship_update",
                "roles_analyzed": len(list(roles_dir.iterdir())) if roles_dir.is_dir() else 0,
                "roles_updated": len(updated_roles),
                "updated_role_ids": updated_roles,
            },
        )

    @staticmethod
    def _is_within_off_peak(start_hhmm: str, end_hhmm: str) -> bool:
        now = datetime.now()
        try:
            start_hour, start_min = [int(x) for x in start_hhmm.split(":")]
            end_hour, end_min = [int(x) for x in end_hhmm.split(":")]
        except Exception:
            return True

        now_minutes = now.hour * 60 + now.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min

        if start_minutes <= end_minutes:
            return start_minutes <= now_minutes <= end_minutes
        return now_minutes >= start_minutes or now_minutes <= end_minutes

    @staticmethod
    def _build_automatic_dreaming_input(config: dict) -> Optional[dict]:
        lookback = int(config.get("lookback_messages", 200))
        store_path = config.get(
            "conversation_store_path",
            get_memory_subpath("conversations_multi_model.json"),
        )
        store_candidates = [Path(store_path)]
        if "conversation_store_path" not in config:
            store_candidates.append(
                Path(get_memory_subpath("conversations_multi_model.json"))
            )

        data = None
        used_path = None
        for candidate in store_candidates:
            if not candidate.exists():
                continue
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
                    used_path = candidate
                    break
            except Exception:
                continue

        if not data:
            return None

        recent = data[-lookback:] if len(data) > lookback else data
        lines = []
        for msg in recent:
            role = msg.get("message_type", "unknown")
            content = str(msg.get("text_content", "")).strip()
            if content:
                lines.append(f"[{role}] {content}")

        if not lines:
            return None

        now = datetime.now()
        conversation_id = f"auto_dream_{now.strftime('%Y%m%d_%H%M%S')}"
        return {
            "conversation_id": conversation_id,
            "conversation_text": "\n".join(lines),
            "metadata": {
                "trigger": "scheduler_automatic",
                "source": str(used_path) if used_path else "unknown",
                "message_count": len(lines),
                "generated_at": now.isoformat(),
                "original_text": "\n".join(lines),
            },
        }
