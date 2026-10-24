"""Expand `provider_accounts` config into one resource per (account, model).

A provider with several accounts (e.g. OpenRouter, where each funded account has its own daily
allowance of free-model calls) is declared once:

    "provider_accounts": {
      "openrouter_free": {
        "template":   {type, provider, base_url, tier, ...},   # shared by every generated resource
        "quota_pool": "openrouter_free",                       # template pool; each account gets its own copy
        "accounts":   {"a": {"key_var": "OPEN_ROUTER_KEY"}, "b": {"key_var": "...", "enabled": false}},
        "models":     [{"model": "vendor/name:free", "priority": 10, "context_limit": 1000000}, ...]
      }
    }

Adding an account or a model is config only. Pure function; no I/O.
Every generated resource also gets health_group "<group>_<account>", so a probe that proves the
account unusable (see resource_health.probe_completion) gates all of that account's models.
Generated ids are "<group>_<account>_<model slug>"; all accounts of one model share account_group
"<group>_<model slug>" so the pool's round-robin spreads calls across accounts.
"""
import copy
import re
from typing import Any, Dict, List, Tuple


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def expand_provider_accounts(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """(resources, quota_pools, errors) with the generated entries merged over the plain ones.

    A malformed group is reported in `errors` and produces nothing; it never raises, so one bad
    group cannot take the whole pool down.
    """
    resources = dict(data.get("resources") or {})
    pools = dict(data.get("quota_pools") or {})
    errors: List[str] = []
    for group, spec in (data.get("provider_accounts") or {}).items():
        if not isinstance(spec, dict) or not spec.get("accounts") or not spec.get("models"):
            errors.append(f"provider_accounts.{group}: needs non-empty 'accounts' and 'models'")
            continue
        template = spec.get("template") or {}
        pool_name = spec.get("quota_pool")
        if pool_name and pool_name not in pools:
            errors.append(f"provider_accounts.{group}: quota_pool {pool_name!r} is not defined in quota_pools")
            continue
        for acct, acfg in spec["accounts"].items():
            if not isinstance(acfg, dict) or not (acfg.get("key_var") or acfg.get("api_key_env")):
                errors.append(f"provider_accounts.{group}.{acct}: needs key_var")
                continue
            acct_pool = None
            if pool_name:
                acct_pool = f"{pool_name}__{acct}"
                pools[acct_pool] = copy.deepcopy(data["quota_pools"][pool_name])
            for m in spec["models"]:
                if not m.get("model"):
                    errors.append(f"provider_accounts.{group}: a model entry has no 'model'")
                    continue
                slug = _slug(m["model"])
                conf = copy.deepcopy(template)
                conf.update(m)
                conf["key_var"] = acfg.get("key_var") or acfg.get("api_key_env")
                conf.pop("api_key_env", None)
                if acfg.get("credential_engine"):  # this account's key comes from the credential engine, not the environment
                    conf["credential_engine"] = True
                conf["account_group"] = f"{group}_{slug}"
                conf["health_group"] = f"{group}_{acct}"
                conf["enabled"] = bool(acfg.get("enabled", True) and m.get("enabled", True))
                if acct_pool:
                    conf["quota_pool"] = acct_pool
                conf["description"] = f"{group} account {acct}: {m['model']}. {m.get('description', '')}".strip()
                resources[f"{group}_{acct}_{slug}"] = conf
    return resources, pools, errors
