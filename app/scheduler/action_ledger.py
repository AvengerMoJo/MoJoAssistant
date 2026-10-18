"""Ledger of the state-changing tool calls a task made, so a final answer cannot claim success over a failed one.

Found 2026-10-19 (owner_route_paul_20261017_104205): Paul was asked to create an assistant, his write_file
call was refused by the sandbox, nothing was created, and his FINAL_ANSWER began "Completed: Configured ...".
The executor accepted it; the owner was told it was done. The answer's own **Incomplete** section is recorded
but nothing reads it (222 of 476 task reports list real incomplete items and all are "completed"), so it
cannot be the gate. A failed *action* is the reliable signal:

  - every call to a state-changing tool (danger medium/high in the capability catalog) is recorded
  - a failure is resolved by a later success of the same tool
  - a final answer is refused while an unresolved failure exists and the answer never mentions the failed
    tool or what it targeted; the model must retry, ask the owner, or say in the answer that it failed
  - after MAX_REFUSALS refusals the task fails with an explicit error instead of looping
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

MUTATING_DANGER_LEVELS = ("medium", "high")
MAX_REFUSALS = 2
REFUSAL_MARKER = "UNRESOLVED_ACTION_FAILURE"


def call_failed(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("error")) or result.get("success") is False
    return False


def _error_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("error") or result.get("message") or "the call reported failure")[:200]
    return "the call raised an error"


def _targets(args: Dict[str, Any]) -> List[str]:
    """Short, distinctive argument values (a path, an id) the answer would mention if it addressed the failure."""
    out: List[str] = []
    for v in (args or {}).values():
        if isinstance(v, str) and 3 <= len(v) <= 200 and "\n" not in v:
            out.append(v.rsplit("/", 1)[-1] or v)
    return out[:3]


@dataclass
class Failure:
    tool: str
    error: str
    targets: List[str]


@dataclass
class ActionLedger:
    failures: List[Failure] = field(default_factory=list)
    refusals: int = 0

    def record(self, tool: str, args: Dict[str, Any], result: Any, danger_level: str) -> None:
        if danger_level not in MUTATING_DANGER_LEVELS:
            return
        if call_failed(result):
            self.failures.append(Failure(tool, _error_text(result), _targets(args)))
        else:
            self.failures = [f for f in self.failures if f.tool != tool]

    def unaddressed(self, final_answer: str) -> List[Failure]:
        """Unresolved failures the final answer says nothing about."""
        text = (final_answer or "").lower()
        out = []
        for f in self.failures:
            mentioned = f.tool.lower() in text or any(t.lower() in text for t in f.targets)
            if not mentioned:
                out.append(f)
        return out

    def refusal_message(self, pending: List[Failure]) -> str:
        lines = "; ".join(f"{f.tool}({', '.join(f.targets) or '...'}): {f.error}" for f in pending)
        return (
            f"{REFUSAL_MARKER}: you wrote a final answer, but these actions failed and were never fixed: {lines}. "
            "Do not report success over a failed action. Retry it a different way, or call ask_user to get "
            "what you need, or write your final answer again stating plainly that this action failed and "
            "what is therefore not done."
        )

    def refuse(self) -> bool:
        """Count a refusal; True while the model still has attempts left."""
        self.refusals += 1
        return self.refusals <= MAX_REFUSALS


_REFUSED_TOO_OFTEN = "task ended: the final answer kept claiming completion over failed actions ({lines})"


def too_often_error(pending: List[Failure]) -> str:
    return _REFUSED_TOO_OFTEN.format(lines="; ".join(f"{f.tool}: {f.error}" for f in pending))
