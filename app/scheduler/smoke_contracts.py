from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContractCheck:
    name: str
    ok: bool
    reason: str = ""


@dataclass
class ContractResult:
    ok: bool
    checks: List[ContractCheck] = field(default_factory=list)


@dataclass
class ResourceContract:
    min_context_limit: int = 8192
    min_output_limit: int = 512
    require_enabled: bool = True
    require_reachable: bool = True
    require_model_name: bool = True


def evaluate_resource_for_basic_agentic(resource: Dict[str, Any], contract: Optional[ResourceContract] = None) -> ContractResult:
    c = contract or ResourceContract()
    checks: List[ContractCheck] = []

    enabled = bool(resource.get("enabled", False))
    status = str(resource.get("status", "")).lower()
    model = resource.get("model")
    context_limit = int(resource.get("context_limit") or 0)
    output_limit = int(resource.get("output_limit") or 0)

    checks.append(ContractCheck("enabled", (not c.require_enabled) or enabled, "resource disabled" if c.require_enabled and not enabled else ""))
    checks.append(ContractCheck("reachable", (not c.require_reachable) or status == "available", f"status={status}" if c.require_reachable and status != "available" else ""))
    checks.append(ContractCheck("model_name", (not c.require_model_name) or bool(model), "model is empty" if c.require_model_name and not model else ""))
    checks.append(ContractCheck("context_limit", context_limit >= c.min_context_limit, f"context_limit={context_limit} < {c.min_context_limit}" if context_limit < c.min_context_limit else ""))
    checks.append(ContractCheck("output_limit", output_limit >= c.min_output_limit, f"output_limit={output_limit} < {c.min_output_limit}" if output_limit < c.min_output_limit else ""))

    ok = all(x.ok for x in checks)
    return ContractResult(ok=ok, checks=checks)


def evaluate_role_tools(role: Dict[str, Any], available_tools: List[str], must_have_any: Optional[List[str]] = None) -> ContractResult:
    checks: List[ContractCheck] = []

    role_id = role.get("id")
    checks.append(ContractCheck("role_id", bool(role_id), "missing role id" if not role_id else ""))

    if must_have_any:
        overlap = sorted(set(available_tools) & set(must_have_any))
        checks.append(
            ContractCheck(
                "tool_overlap",
                bool(overlap),
                f"missing required tool family; need any of {must_have_any}" if not overlap else f"matched={overlap}",
            )
        )

    return ContractResult(ok=all(x.ok for x in checks), checks=checks)
