"""Daily refresh of the OpenRouter free-model lane in the resource pool.

OpenRouter's free models come and go and fail for days at a time (both Nemotron models answered 503 / timed
out on every account on 2026-10-18 while the pool kept putting them first). The list in
resource_pool.json -> provider_accounts.openrouter_free.models is therefore kept up to date by this job:

  1. fetch the public catalog (no key needed); a failed fetch is an error and changes nothing
  2. candidates = free (price 0) models that support tool calls, have enough context, are not expired
  3. every configured model and up to MAX_NEW_PER_RUN new candidates get one real round trip
  4. a new candidate that answers is added at a low priority (promotion is the owner's call)
  5. a configured model that left the catalog is disabled at once; one that failed FAIL_LIMIT daily checks in a
     row is disabled; a disabled one that is in the catalog and answers again is enabled
  6. the config is written with a backup, read back and re-expanded; if that fails the backup is restored

Models are never deleted: a disabled entry keeps its reason and can come back. State lives in
~/.memory/state/openrouter_free_refresh.json. Network and the pool config are injected so the decisions are
unit-testable without either.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

CATALOG_URL = "https://openrouter.ai/api/v1/models"
GROUP = "openrouter_free"
MIN_CONTEXT = 32000
MAX_NEW_PER_RUN = 3
FAIL_LIMIT = 3
NEW_MODEL_PRIORITY = 30


class RefreshError(RuntimeError):
    pass


def free_tool_candidates(catalog: Dict[str, Any], today: datetime, min_context: int = MIN_CONTEXT) -> Dict[str, Dict[str, Any]]:
    """{model id: catalog entry} for free models that can do tool calls and are not expired."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in catalog.get("data") or []:
        mid = m.get("id") or ""
        pricing = m.get("pricing") or {}
        if not mid.endswith(":free"):
            continue
        if str(pricing.get("prompt", "0")) not in ("0", "0.0") or str(pricing.get("completion", "0")) not in ("0", "0.0"):
            continue
        if "tools" not in (m.get("supported_parameters") or []):
            continue
        if int(m.get("context_length") or 0) < min_context:
            continue
        expires = m.get("expiration_date")
        if expires:
            try:
                if datetime.fromisoformat(str(expires)).replace(tzinfo=timezone.utc) <= today:
                    continue
            except ValueError:
                pass
        out[mid] = m
    return out


def plan_changes(
    configured: List[Dict[str, Any]],
    catalog_ids: Dict[str, Dict[str, Any]],
    verified: Dict[str, bool],
    history: Dict[str, Dict[str, Any]],
    today: str,
) -> Dict[str, Any]:
    """What to add / disable / enable, and the new per-model history. Pure."""
    history = copy.deepcopy(history)
    add: List[Dict[str, Any]] = []
    disable: Dict[str, str] = {}
    enable: List[str] = []
    known = {m["model"] for m in configured}

    for m in configured:
        mid = m["model"]
        h = history.setdefault(mid, {"consecutive_failures": 0})
        if mid not in verified:
            continue
        if verified[mid]:
            h["consecutive_failures"], h["last_ok"] = 0, today
        else:
            h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
        enabled = m.get("enabled", True)
        in_catalog = mid in catalog_ids
        if enabled and not in_catalog and not mid.startswith("openrouter/"):
            disable[mid] = f"no longer listed as a free, tool-capable model in the OpenRouter catalog ({today})"
        elif enabled and h["consecutive_failures"] >= FAIL_LIMIT:
            disable[mid] = f"failed {h['consecutive_failures']} daily checks in a row (last {today})"
        elif not enabled and in_catalog and verified[mid]:
            enable.append(mid)

    for mid, entry in catalog_ids.items():
        if mid in known or mid not in verified or not verified[mid]:
            continue
        add.append({
            "model": mid,
            "priority": NEW_MODEL_PRIORITY,
            "context_limit": int(entry.get("context_length") or MIN_CONTEXT),
            "description": f"auto-added {today} by the daily free-model refresh after a working round trip; "
                           "priority is deliberately low until the owner promotes it.",
        })
        history[mid] = {"consecutive_failures": 0, "last_ok": today, "auto_added": today}
    return {"add": add, "disable": disable, "enable": enable, "history": history}


def apply_to_config(config_path: Path, plan: Dict[str, Any], expand: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    """Write the plan into the config: backup, write, read back, re-expand; restore the backup on any failure."""
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    models = data["provider_accounts"][GROUP]["models"]
    by_id = {m["model"]: m for m in models}
    for mid, reason in plan["disable"].items():
        by_id[mid]["enabled"] = False
        by_id[mid]["disabled_reason"] = reason
    for mid in plan["enable"]:
        by_id[mid].pop("enabled", None)
        by_id[mid].pop("disabled_reason", None)
    models.extend(plan["add"])
    if not (plan["add"] or plan["disable"] or plan["enable"]):
        return {"written": False}

    backup = config_path.with_name(config_path.name + ".bak_freerefresh")
    shutil.copy2(config_path, backup)
    try:
        config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        back = json.loads(config_path.read_text(encoding="utf-8"))
        _, _, errors = expand(back)
        if errors:
            raise RefreshError(f"config does not expand after the change: {errors}")
        present = {m["model"] for m in back["provider_accounts"][GROUP]["models"]}
        missing = {m["model"] for m in plan["add"]} - present
        if missing:
            raise RefreshError(f"read-back is missing added models: {sorted(missing)}")
    except Exception:
        shutil.copy2(backup, config_path)
        raise
    return {"written": True, "backup": str(backup)}


async def run_refresh(
    config_path: Path,
    state_path: Path,
    fetch_catalog: Callable[[], Any],
    verify: Callable[[str], Any],
    expand: Callable[[Dict[str, Any]], Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One daily run. fetch_catalog() -> catalog dict; verify(model) -> bool (awaitable). Both may raise."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    catalog = await _maybe_await(fetch_catalog())
    if not isinstance(catalog, dict) or not catalog.get("data"):
        raise RefreshError("OpenRouter catalog came back empty; nothing was changed")
    candidates = free_tool_candidates(catalog, now)

    data = json.loads(config_path.read_text(encoding="utf-8"))
    configured = data["provider_accounts"][GROUP]["models"]
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    history = state.get("models", {})

    known = {m["model"] for m in configured}
    fresh = [mid for mid in candidates if mid not in known]
    # biggest context first, then name: the same catalog gives the same order every day
    new_ids = sorted(fresh, key=lambda mid: (-int(candidates[mid].get("context_length") or 0), mid))[:MAX_NEW_PER_RUN]
    to_check = [m["model"] for m in configured if not m["model"].startswith("openrouter/")] + new_ids
    verified: Dict[str, bool] = {}
    for mid in to_check:
        try:
            verified[mid] = bool(await _maybe_await(verify(mid)))
        except Exception:
            verified[mid] = False

    plan = plan_changes(configured, candidates, verified, history, today)
    result = apply_to_config(config_path, plan, expand)

    summary = {
        "run_at": now.isoformat(),
        "catalog_free_tool_models": len(candidates),
        "checked": verified,
        "added": [m["model"] for m in plan["add"]],
        "disabled": plan["disable"],
        "enabled": plan["enable"],
        "config_written": result["written"],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"models": plan["history"], "last_run": summary}, indent=2), encoding="utf-8")
    return summary


async def _maybe_await(v):
    if hasattr(v, "__await__"):
        return await v
    return v
