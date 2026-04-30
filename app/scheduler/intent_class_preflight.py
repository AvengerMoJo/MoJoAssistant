from dataclasses import dataclass, field
from typing import Dict, List
import shutil


@dataclass
class ClassStatus:
    ok: bool
    providers_checked: List[str] = field(default_factory=list)
    passing_providers: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


@dataclass
class PreflightReport:
    ok: bool
    required_classes: List[str]
    class_status: Dict[str, ClassStatus]
    remediation: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "required_classes": self.required_classes,
            "class_status": {
                k: {
                    "ok": v.ok,
                    "providers_checked": v.providers_checked,
                    "passing_providers": v.passing_providers,
                    "failures": v.failures,
                }
                for k, v in self.class_status.items()
            },
            "remediation": self.remediation,
        }


def evaluate_intent_class_preflight(required_classes: List[str], provider_health: Dict[str, Dict]) -> PreflightReport:
    """
    provider_health shape:
      {
        "provider_id": {
          "intent_classes": ["execute", ...],
          "ok": bool,
          "failure": "..."  # optional
        }
      }
    """
    status: Dict[str, ClassStatus] = {}
    remediation: List[str] = []

    for ic in required_classes:
      s = ClassStatus(ok=False)
      for pid, meta in provider_health.items():
          if ic not in (meta.get("intent_classes") or []):
              continue
          s.providers_checked.append(pid)
          if meta.get("ok"):
              s.passing_providers.append(pid)
          else:
              reason = meta.get("failure") or "probe failed"
              s.failures.append(f"{pid}: {reason}")

      s.ok = len(s.passing_providers) > 0
      if not s.ok:
          remediation.append(f"Attach or repair at least one provider for intent class '{ic}'")
      status[ic] = s

    ok = all(v.ok for v in status.values()) if required_classes else True
    return PreflightReport(ok=ok, required_classes=required_classes, class_status=status, remediation=remediation)


def infer_intent_classes_for_tool(tool_name: str) -> List[str]:
    """Map concrete tool names to abstract intent classes."""
    t = (tool_name or "").strip()
    if t in {"ask_user"}:
        return ["escalate"]
    if t in {"bash_exec", "python_exec", "tmux_exec", "tmux_run_command"}:
        return ["execute"]
    if t.startswith("tmux__"):
        return ["interact", "execute"]
    if t in {"read_file", "search_in_files", "task_session_read", "task_report_read", "memory_search"}:
        return ["read", "observe"]
    if t in {"write_file", "add_conversation"}:
        return ["write"]
    if t in {"web_search", "fetch_url", "curl_request"}:
        return ["external_lookup", "read"]
    if t.startswith("playwright__browser_"):
        return ["interact", "external_lookup", "read"]
    return []


def provider_health_from_tools(enabled_tools: List[str]) -> Dict[str, Dict]:
    """
    Build provider_health from resolved tool names.
    Adds lightweight runtime probes for known binary-backed families.
    """
    health: Dict[str, Dict] = {}
    for t in enabled_tools:
        classes = infer_intent_classes_for_tool(t)
        if not classes:
            continue
        ok = True
        failure = ""
        if t in {"bash_exec", "python_exec"}:
            if shutil.which("bash") is None:
                ok = False
                failure = "bash binary missing"
        if t in {"tmux_exec", "tmux_run_command"} or t.startswith("tmux__"):
            if shutil.which("tmux") is None:
                ok = False
                failure = "tmux binary missing"
        health[t] = {"intent_classes": classes, "ok": ok, "failure": failure}

    # finalize contract provider is framework-level
    health["framework.finalize_contract"] = {
        "intent_classes": ["finalize"],
        "ok": True,
        "failure": "",
    }
    return health
