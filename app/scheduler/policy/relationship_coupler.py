"""
RelationshipPolicyCoupler — translates owner_profile.assistant_relationships[role_id].trust_level
into policy baseline adjustments applied before per-role policy config.

Trust levels and their effect on policy defaults:

  "restricted"  — tightest defaults; sensitive_domain_action=block, content checker
                  enforced, data_boundary.allow_external_mcp=False
  "standard"    — normal defaults; sensitive_domain_action=warn (default)
  "trusted"     — relaxed defaults; content checker still runs; no extra restrictions

Trust level only adjusts DEFAULTS. Explicit role policy config always wins.
If a role has no entry in assistant_relationships, "standard" is assumed.
"""

from typing import Any, Dict, Optional

from app.roles.owner_context import load_owner_profile


_TRUST_POLICY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "restricted": {
        "sensitive_domain_action": "block",
        "data_boundary_defaults": {"allow_external_mcp": False, "allowed_tiers": ["free"]},
        "extra_checkers": ["sensitive_domain", "data_boundary"],
    },
    "standard": {
        "sensitive_domain_action": "warn",
        "data_boundary_defaults": {},
        "extra_checkers": ["sensitive_domain"],
    },
    "trusted": {
        "sensitive_domain_action": "warn",
        "data_boundary_defaults": {},
        "extra_checkers": [],
    },
}


def get_trust_level(role_id: Optional[str]) -> str:
    """Return the trust level for role_id from the owner profile, defaulting to 'standard'."""
    if not role_id:
        return "standard"
    try:
        profile = load_owner_profile()
        rel = profile.get("assistant_relationships", {}).get(role_id, {})
        return rel.get("trust_level", "standard")
    except Exception:
        return "standard"


def apply_trust_defaults(
    role_id: Optional[str],
    policy: Dict[str, Any],
    data_boundary: Dict[str, Any],
) -> tuple:
    """
    Apply trust-level defaults to policy and data_boundary dicts.

    Role-explicit values always win — this only fills in gaps where the role
    has not specified a value.

    Returns (merged_policy, merged_data_boundary).
    """
    trust = get_trust_level(role_id)
    defaults = _TRUST_POLICY_DEFAULTS.get(trust, _TRUST_POLICY_DEFAULTS["standard"])

    merged_policy = dict(policy)
    merged_data_boundary = dict(data_boundary)

    # sensitive_domain_action: role wins, trust fills gap
    merged_policy.setdefault("sensitive_domain_action", defaults["sensitive_domain_action"])

    # data_boundary defaults: only set keys not already specified by role
    for k, v in defaults["data_boundary_defaults"].items():
        merged_data_boundary.setdefault(k, v)

    # extra_checkers: ensure trust-required checkers are in the pipeline
    # Role can still override the full checkers list via policy.checkers
    if "checkers" not in merged_policy:
        base = ["static", "content", "sensitive_domain"]
        for c in defaults["extra_checkers"]:
            if c not in base:
                base.append(c)
        merged_policy["checkers"] = base

    return merged_policy, merged_data_boundary
