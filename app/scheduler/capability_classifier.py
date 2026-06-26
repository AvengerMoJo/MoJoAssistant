"""Capability name classifier — resolves unknown/misspelled tool names.

Two-tier resolution:
  1. Static alias table (zero cost) — covers common variants and known
     misspellings.  Always checked first; no LLM call needed.
  2. LLM classifier (fallback) — handles novel misspellings and synonyms
     the alias table doesn't cover.  Results are cached on disk so each
     unknown name only costs one LLM call ever.

Integration point: CapabilityResolver._expand() calls
``normalize_tool_name(name, known_tools)`` before doing registry lookup.
If the name is already known it is returned unchanged.  If it resolves
via alias or LLM it is returned canonicalized.  If nothing matches,
``None`` is returned and the caller skips the name with a warning.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1 — static alias table
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, str] = {
    # read
    "file_read": "read_file",
    "cat": "read_file",
    "read": "read_file",
    # write
    "file_write": "write_file",
    "write": "write_file",
    # list
    "ls": "list_files",
    "dir": "list_files",
    "list_dir": "list_files",
    # search
    "grep": "search_in_files",
    "search": "search_in_files",
    "search_files": "search_in_files",
    "file_search": "search_in_files",
    # exec
    "bash": "bash_exec",
    "exec": "bash_exec",
    "shell": "bash_exec",
    "container_exec": "bash_exec",
    "run_bash": "bash_exec",
    "terminal": "bash_exec",
    # web
    "curl": "fetch_url",
    "curl_request": "fetch_url",
    "http_get": "fetch_url",
    "fetch": "fetch_url",
    "get_url": "fetch_url",
    "web": "web_search",
    "google": "web_search",
    "search_web": "web_search",
    # memory
    "search_memory": "memory_search",
    "memory": "memory_search",
    "remember": "memory_search",
    # browser
    "browser": "playwright__browser_navigate",
    "navigate": "playwright__browser_navigate",
    "open_url": "playwright__browser_navigate",
    # task
    "task_session": "task_session_read",
    "task_report": "task_report_read",
    "session_read": "task_session_read",
    "report_read": "task_report_read",
}

# ---------------------------------------------------------------------------
# Tier 2 — LLM classifier
# ---------------------------------------------------------------------------

_CACHE_PATH = Path.home() / ".memory" / "config" / "capability_classifier_cache.json"
_COUNTER_PATH = Path.home() / ".memory" / "config" / "capability_unknown_counts.json"
_cache: Optional[Dict[str, Optional[str]]] = None


def _load_cache() -> Dict[str, Optional[str]]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = {}
    return _cache


def _save_cache(cache: Dict[str, Optional[str]]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("[capability_classifier] failed to save cache: %s", e)


def _record_unknown(name: str, resolved_to: Optional[str]) -> None:
    """Increment the frequency counter for an unknown tool name.

    Persisted to capability_unknown_counts.json so we can later build a
    dictionary from the most commonly requested unknown names.

    Schema: { "<unknown_name>": {"count": N, "resolved_to": "<canonical>|null"} }
    """
    try:
        try:
            data: Dict[str, Any] = json.loads(_COUNTER_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        entry = data.get(name, {"count": 0, "resolved_to": resolved_to})
        entry["count"] = entry.get("count", 0) + 1
        entry["resolved_to"] = resolved_to  # update to latest resolution
        data[name] = entry
        _COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COUNTER_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("[capability_classifier] failed to record unknown count: %s", e)


def _call_llm_classifier(unknown_name: str, known_tools: List[str]) -> Optional[str]:
    """One-shot sync LLM call to identify the canonical tool name.

    Uses the first reachable free-tier local resource.  Falls back to
    None (not an error) if no resource is available.
    """
    try:
        import httpx
        from app.scheduler.resource_pool import ResourcePool
        pool = ResourcePool()
        resource = pool.acquire_by_requirements(
            {"tier": ["free", "free_api"], "min_context": 4096}
        )
        if not resource:
            logger.debug("[capability_classifier] no resource available for LLM classification")
            return None

        tools_list = "\n".join(f"- {t}" for t in sorted(known_tools))
        prompt = (
            f"You are a tool name resolver. A user specified the tool name "
            f'"{unknown_name}" but it does not exist in the registry.\n\n'
            f"Available canonical tool names:\n{tools_list}\n\n"
            f'Which canonical tool name best matches "{unknown_name}"? '
            f"Reply with ONLY the exact canonical name from the list above, "
            f'or reply "none" if there is no reasonable match. '
            f"No explanation."
        )

        base_url = resource.base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"

        headers = {"Content-Type": "application/json"}
        if resource.api_key:
            headers["Authorization"] = f"Bearer {resource.api_key}"

        payload = {
            "model": resource.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 32,
            "temperature": 0.0,
        }

        resp = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().lower()

        if answer == "none" or not answer:
            return None
        # Verify the answer is actually in our known list
        if answer in {t.lower() for t in known_tools}:
            # Return the correctly-cased version
            for t in known_tools:
                if t.lower() == answer:
                    return t
        return None

    except Exception as e:
        logger.debug("[capability_classifier] LLM call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_tool_name(
    name: str,
    known_tools: List[str],
    *,
    use_llm: bool = True,
) -> Optional[str]:
    """Resolve ``name`` to a canonical tool name.

    Parameters
    ----------
    name        : tool name as provided (may be misspelled or aliased)
    known_tools : list of canonical tool names currently in the registry
    use_llm     : set False to skip the LLM tier (tests, hot paths)

    Returns
    -------
    The canonical name, or ``None`` if no reasonable match found.
    The caller should log a warning on ``None`` and skip the tool.
    """
    # Already valid — fastest path
    if name in known_tools:
        return name

    # Tier 1: static alias table
    alias = _ALIASES.get(name.lower())
    if alias and alias in known_tools:
        logger.info("[capability_classifier] alias resolved: %s → %s", name, alias)
        _record_unknown(name, alias)
        return alias

    # If alias points somewhere not in known_tools, still try it — it may
    # be a valid builtin not in the dynamic list
    if alias:
        logger.info("[capability_classifier] alias resolved (not in dynamic list): %s → %s", name, alias)
        _record_unknown(name, alias)
        return alias

    if not use_llm:
        logger.warning("[capability_classifier] unknown tool '%s' — no alias match, LLM disabled", name)
        _record_unknown(name, None)
        return None

    # Tier 2: LLM classifier with disk cache
    cache = _load_cache()
    cache_key = f"{name}::{','.join(sorted(known_tools))}"[:200]

    if cache_key in cache:
        cached = cache[cache_key]
        if cached:
            logger.info("[capability_classifier] cache hit: %s → %s", name, cached)
        else:
            logger.debug("[capability_classifier] cache hit (no match): %s", name)
        _record_unknown(name, cached)
        return cached

    logger.info("[capability_classifier] LLM classifying unknown tool: '%s'", name)
    resolved = _call_llm_classifier(name, known_tools)

    cache[cache_key] = resolved
    _save_cache(cache)
    _record_unknown(name, resolved)

    if resolved:
        logger.info("[capability_classifier] LLM resolved: %s → %s", name, resolved)
    else:
        logger.warning("[capability_classifier] could not resolve tool name '%s'", name)

    return resolved
