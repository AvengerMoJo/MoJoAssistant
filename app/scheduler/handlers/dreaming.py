"""Dreaming task handler — memory consolidation via the ABCD pipeline."""
# [mojo-integration]
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult
from app.config.paths import get_memory_subpath


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
                from dreaming.storage.json_backend import JsonFileBackend
                role_id = task.config.get("role_id", "unknown")
                storage_path = (
                    Path(get_memory_subpath("roles")) / role_id / "knowledge_units"
                )
                pipeline = ctx.get_dreaming_pipeline(quality_level)
                pipeline.storage = JsonFileBackend(storage_path=storage_path)

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

            pipeline = ctx.get_dreaming_pipeline(quality_level)
            conv_role_id = task.config.get("role_id")
            if conv_role_id:
                try:
                    from dreaming.storage.json_backend import JsonFileBackend
                    role_storage_path = (
                        Path(get_memory_subpath("roles")) / conv_role_id / "knowledge_units"
                    )
                    pipeline.storage = JsonFileBackend(storage_path=role_storage_path)
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
