"""Dynamic answer computation for routing-profiler tasks.

Root cause found live 2026-08-15/16: several benchmark tasks ask the
model to report a fact about live, mutable system state (resource_pool.json
contents, role configs, directory contents). The task files originally
stored a frozen ``correct_answer`` string -- a snapshot of that state at
whatever moment the task was authored. Every one of those snapshots drifts
stale the instant the underlying file changes, which happens routinely
(new models registered, roles edited, config tweaked). A model that
computes the CURRENT, true answer -- even via a real tool call, even
perfectly correctly -- still fails, because it's being compared against
yesterday's number, not reality.

Patching the frozen string by hand (what was done for 8 tasks on
2026-08-15) only fixes the test until the next real system change. It is
not a real fix, just a later expiration date.

The real fix: tasks whose answer is a pure function of live, inspectable
state get a ``correct_answer_fn`` key instead of (or alongside) a frozen
``correct_answer``. At grading time, run_routing_profiler.check_answer()
calls the named function here to get the answer as it is RIGHT NOW,
so the check is correct at any point in time, not just the moment
someone last regenerated the JSON by hand.

Each function takes no arguments and returns a string in the same shape
check_answer() already expects (",".join(...) / ";".join(...) for
multi-item answers), or None if the live data can't be read (in which
case check_answer falls back to the task's static correct_answer, if any).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_resource_pool() -> Dict:
    p = Path.home() / ".memory" / "config" / "resource_pool.json"
    return json.loads(p.read_text()).get("resources", {})


def _load_roles() -> Dict[str, Dict]:
    roles_dir = Path.home() / ".memory" / "roles"
    out = {}
    for f in sorted(roles_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out[d.get("id", f.stem)] = d
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# resource_pool.json derived answers
# ---------------------------------------------------------------------------

def resource_pool_total_count() -> str:
    return str(len(_load_resource_pool()))


def resource_pool_enabled_count() -> str:
    pool = _load_resource_pool()
    return str(sum(1 for v in pool.values() if v.get("enabled")))


def resource_pool_enabled_free_tier_names() -> str:
    pool = _load_resource_pool()
    names = sorted(k for k, v in pool.items() if v.get("enabled") and v.get("tier") == "free")
    return ",".join(names)


def resource_pool_enabled_local_with_priority() -> str:
    pool = _load_resource_pool()
    items = sorted(
        (k, v.get("priority")) for k, v in pool.items()
        if v.get("enabled") and v.get("type") == "local"
    )
    return ",".join(f"{k}={pri}" for k, pri in items)


def resource_pool_model_and_tier_per_resource() -> str:
    pool = _load_resource_pool()
    items = sorted(pool.items())
    return ";".join(f"{k}={v.get('model','?')}:{v.get('tier','?')}" for k, v in items)


def resource_pool_status_per_resource() -> str:
    pool = _load_resource_pool()
    items = sorted(pool.items())
    return ";".join(f"{k}={'enabled' if v.get('enabled') else 'disabled'}" for k, v in items)


def resource_pool_lowest_priority_model_name() -> str:
    pool = _load_resource_pool()
    enabled = [(k, v.get("priority", 999), v.get("model")) for k, v in pool.items() if v.get("enabled")]
    if not enabled:
        return ""
    min_pri = min(pri for _, pri, _ in enabled)
    return next(model for k, pri, model in enabled if pri == min_pri)


def resource_pool_ranked_free_local_by_priority() -> str:
    pool = _load_resource_pool()
    items = sorted(
        ((k, v.get("priority", 999)) for k, v in pool.items() if v.get("type") == "local" and v.get("enabled")),
        key=lambda x: x[1],
    )
    return ",".join(f"{k}(p={pri})" for k, pri in items)


def resource_pool_api_tier_count_and_models() -> str:
    pool = _load_resource_pool()
    models = sorted(v.get("model", "?") for v in pool.values() if v.get("tier") == "free_api")
    return f"count={len(models)};models=" + ",".join(models)


def resource_pool_max_tasks_per_hour_estimate() -> str:
    # (3600 / tick_interval) * enabled_count. tick_interval is the
    # app/scheduler/core.py Scheduler.__init__ default (60s) -- no config
    # file exposes an override, so 60 is the only value discoverable by
    # reading the codebase, matching what the task goal actually asks the
    # model to do ("read scheduler tick interval").
    tick_interval = 60
    pool = _load_resource_pool()
    enabled_count = sum(1 for v in pool.values() if v.get("enabled"))
    return str(int((3600 / tick_interval) * enabled_count))


# ---------------------------------------------------------------------------
# config/ directory derived answers
# ---------------------------------------------------------------------------

# Files in config/ that are NOT configuration -- runtime-generated logs,
# .example templates, and non-JSON docs. tool_operation_logs.json alone is
# ~3MB and grows continuously from ordinary system activity; including it
# makes any aggregate stat over "config files" unstable by the minute,
# regardless of how often the answer key is regenerated. Excluding these
# is what "config files" means to a human reading the goal text, and it's
# also the only way this class of task can have a stable answer at all.
_NON_CONFIG_FILES = {"tool_operation_logs.json"}


def _real_config_json_files():
    config_dir = PROJECT_ROOT / "config"
    return sorted(
        p for p in config_dir.glob("*.json")
        if p.name not in _NON_CONFIG_FILES
    )


def config_json_file_names() -> str:
    return ",".join(p.name for p in _real_config_json_files())


def config_total_line_count() -> str:
    total = 0
    for p in _real_config_json_files():
        total += len(p.read_text(errors="replace").splitlines())
    return str(total)


# ---------------------------------------------------------------------------
# role-derived answers
# ---------------------------------------------------------------------------

def popo_system_prompt_word_count() -> str:
    roles = _load_roles()
    popo = roles.get("popo", {})
    return str(len(popo.get("system_prompt", "").split()))


def scheduler_orchestration_roles() -> str:
    """cellD_012: roles referenced by role_id in scheduler_config.json (repo
    default merged with the personal override, matching how the real
    scheduler resolves it -- see that file's own _comment) that also carry
    the 'orchestration' capability.

    Bug found live 2026-08-17: the frozen correct_answer
    ("ahman,anna,doc_audit,paul,popo,quinn") didn't match either the repo
    default (zero role_id entries) or the personal config (one: "paul")
    under any interpretation tried -- almost certainly written against an
    earlier scheduler_config.json snapshot with more role_id-tagged tasks
    that has since been trimmed. Rather than guess at historical intent,
    this computes the answer fresh from whatever the live merged config
    actually contains right now.
    """
    def _role_ids(cfg) -> set:
        ids: set = set()

        def walk(o):
            if isinstance(o, dict):
                if "role_id" in o:
                    ids.add(o["role_id"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(cfg)
        return ids

    repo_cfg = json.loads((PROJECT_ROOT / "config" / "scheduler_config.json").read_text())
    personal_path = Path.home() / ".memory" / "config" / "scheduler_config.json"
    personal_cfg = json.loads(personal_path.read_text()) if personal_path.exists() else {}
    role_ids = _role_ids(repo_cfg) | _role_ids(personal_cfg)

    roles = _load_roles()
    orchestration = sorted(
        rid for rid in role_ids
        if "orchestration" in (roles.get(rid, {}).get("capabilities") or [])
    )
    return "orchestration_roles=" + ",".join(orchestration)


def coding_agent_roles_avg_max_iterations() -> str:
    roles = _load_roles()
    vals = [r.get("max_iterations") for r in roles.values() if r.get("executor") == "coding_agent"]
    vals = [v for v in vals if v is not None]
    if not vals:
        return ""
    return f"{sum(vals) / len(vals):.2f}"


def roles_avg_nine_chapter_score() -> str:
    roles = _load_roles()
    vals = [r.get("nine_chapter_score") for r in roles.values() if r.get("nine_chapter_score") is not None]
    if not vals:
        return ""
    return f"{sum(vals) / len(vals):.2f}"


def roles_count_default_port_embedding_model() -> str:
    """cellC_001's 3-fact composite answer: role count, default server
    port, default embedding model. All three are live/mutable -- role
    count grows as roles are added (was hardcoded "16", live is 17 as of
    2026-08-16); the other two rarely change but are cheap to compute
    fresh rather than trust a frozen snapshot."""
    role_count = len(_load_roles())
    env_example = PROJECT_ROOT / ".env.example"
    port = ""
    for line in env_example.read_text(errors="replace").splitlines():
        if line.strip().startswith("SERVER_PORT="):
            port = line.split("=", 1)[1].strip()
            break
    embedding_cfg = json.loads((PROJECT_ROOT / "config" / "embedding_config.json").read_text())
    embedding_model = embedding_cfg.get("embedding_models", {}).get("default", {}).get("model_name", "")
    return f"{role_count};{port};{embedding_model}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: Dict[str, Callable[[], str]] = {
    "resource_pool_total_count": resource_pool_total_count,
    "resource_pool_enabled_count": resource_pool_enabled_count,
    "resource_pool_enabled_free_tier_names": resource_pool_enabled_free_tier_names,
    "resource_pool_enabled_local_with_priority": resource_pool_enabled_local_with_priority,
    "resource_pool_model_and_tier_per_resource": resource_pool_model_and_tier_per_resource,
    "resource_pool_status_per_resource": resource_pool_status_per_resource,
    "resource_pool_lowest_priority_model_name": resource_pool_lowest_priority_model_name,
    "resource_pool_ranked_free_local_by_priority": resource_pool_ranked_free_local_by_priority,
    "resource_pool_api_tier_count_and_models": resource_pool_api_tier_count_and_models,
    "resource_pool_max_tasks_per_hour_estimate": resource_pool_max_tasks_per_hour_estimate,
    "config_json_file_names": config_json_file_names,
    "config_total_line_count": config_total_line_count,
    "popo_system_prompt_word_count": popo_system_prompt_word_count,
    "coding_agent_roles_avg_max_iterations": coding_agent_roles_avg_max_iterations,
    "roles_avg_nine_chapter_score": roles_avg_nine_chapter_score,
    "roles_count_default_port_embedding_model": roles_count_default_port_embedding_model,
    "scheduler_orchestration_roles": scheduler_orchestration_roles,
}


def resolve_dynamic_answer(fn_name: str) -> Optional[str]:
    """Look up and call a registered answer function. Returns None (never
    raises) if the name is unknown or the live computation fails -- the
    caller falls back to the task's static correct_answer in that case."""
    fn = REGISTRY.get(fn_name)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None
