"""Shadow mode for engine-driven selection: MoJoAssistant keeps choosing from its own table, and the credential
engine is asked the same question on the side. Every pick is compared and written to a log; nothing the engine
answers is used. A week of this shows whether the engine's ranking is right before it is trusted with the hot path.

Off by default; `"shadow_engine_selection": true` at the top of resource_pool.json turns it on. It runs on one
background thread with a bounded queue, so it can never slow or fail an LLM call. When the engine cannot answer,
that is recorded as an error row (at most one a minute), not hidden. Known, expected differences while migrating:
resources that are not engine-managed yet are disabled in the engine, and the engine knows nothing of which local
model is loaded or busy in LM Studio.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger("engine_shadow")
MAX_PENDING = 20
ERROR_ROW_EVERY_S = 60


class ShadowSelector:
    def __init__(self, client_factory: Callable[[], Any], log_path: Path):
        self._client_factory, self._path = client_factory, Path(log_path)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-shadow")
        self._lock = threading.Lock()
        self._pending, self._dropped, self._last_error_row = 0, 0, 0.0

    def compare(self, kind: str, mojo_pick: Dict[str, Any], requirements: Dict[str, Any]) -> None:
        """Queue one comparison and return at once. mojo_pick: {"id", "group", "tier"}."""
        with self._lock:
            if self._pending >= MAX_PENDING:
                self._dropped += 1
                return
            self._pending += 1
        self._pool.submit(self._run, kind, dict(mojo_pick), dict(requirements))

    def _run(self, kind: str, mojo: Dict[str, Any], requirements: Dict[str, Any]) -> None:
        try:
            row = {"t": time.time(), "kind": kind, "mojo": mojo["id"], "mojo_group": mojo.get("group"),
                   "mojo_tier": mojo.get("tier"), "constraints": requirements}
            with self._lock:
                if self._dropped:
                    row["dropped_before"], self._dropped = self._dropped, 0
            try:
                out = self._client_factory().select(requirements, limit=8)
            except Exception as e:
                now = time.time()
                with self._lock:
                    due = now - self._last_error_row >= ERROR_ROW_EVERY_S
                    if due:
                        self._last_error_row = now
                if due:
                    row.update({"level": "engine_error", "engine_error": f"{type(e).__name__}: {e}"})
                    self._write(row)
                return
            ranked: List[Dict[str, Any]] = out.get("ranked", [])
            top = ranked[0] if ranked else None
            ids = [r["id"] for r in ranked]
            excluded = {x["id"]: x["reason"] for x in out.get("excluded", [])}
            if top is None:
                level = "engine_none"
            elif top["id"] == mojo["id"]:
                level = "exact"
            elif mojo.get("group") and top.get("account_group") == mojo["group"]:
                level = "same_group"   # round-robin inside an account group is not a disagreement
            else:
                level = "differs"
            row.update({"level": level, "engine": top["id"] if top else None, "engine_group": top.get("account_group") if top else None,
                        "engine_top": ids[:5], "engine_rank": top.get("rank_priority") if top else None,
                        "mojo_position_in_engine": ids.index(mojo["id"]) + 1 if mojo["id"] in ids else None,
                        "engine_excluded_mojo": excluded.get(mojo["id"])})
            self._write(row)
        except Exception as e:  # the shadow must never raise into the pool; a lost row is logged loudly
            _log.error("shadow comparison failed: %s", e)
        finally:
            with self._lock:
                self._pending -= 1

    def _write(self, row: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def close(self) -> None:
        self._pool.shutdown(wait=True)
