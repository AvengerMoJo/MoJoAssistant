"""
Spec quality gate — validates that a task goal is complete enough to dispatch.

Applied at the MCP boundary for dispatch_subtask and scheduler_add_task.
The calling AI (Claude Code, this session, etc.) is responsible for spec
quality. This gate enforces the contract so Paul and other agents always
receive complete, actionable goals — never vague instructions.

Design principle (BRIDLE):
  Act → Validate → Log → Dream → Learn → Correct
  This module is the Validate step at the dispatch boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class SpecQualityResult:
    quality: str        # "ready" | "incomplete" | "vague"
    score: int          # 0–100
    missing: List[str]
    feedback: str

    @property
    def passed(self) -> bool:
        return self.quality == "ready"


# ---------------------------------------------------------------------------
# Signal patterns for each required spec field
# ---------------------------------------------------------------------------

_CRITERION_PATTERNS = [
    r"\bdone when\b", r"\bwhen (complete|done|finished)\b",
    r"\bsuccess (is|when|criterion)\b", r"\bdeliverable[s]?\s*:",
    r"\boutput\s*:", r"\bresult\s*:", r"\baccepted when\b",
    r"\bdone means\b", r"\bsuccess metric\b", r"\bgoal\s*:",
    r"\bexpected (output|result)\b", r"\bshould (return|produce|output|write|create)\b",
]

_SCOPE_PATTERNS = [
    r"\bout of scope\b", r"\bnot (including|to be|responsible for)\b",
    r"\bexcludes?\b", r"\blimited to\b", r"\bdo not\b", r"\bdon'?t\b",
    r"\bscope\s*:", r"\bonly\b.{0,40}\b(file|function|module|service|path|endpoint)\b",
    r"\bno\b.{0,20}\b(changes? to|touching|modifying)\b",
]

_ACCEPTANCE_PATTERNS = [
    r"\bverif(y|ied|ication)\b", r"\bvalidat(e|ion)\b",
    r"\btest(ed|ing)?\b", r"\bconfirm\b",
    r"\baccept(ed|ance)?\b", r"\bpass(es|ing)?\b",
    r"\bcheck\b.{0,30}\b(that|if|whether)\b",
    r"\bsuccess (is confirmed|is verified|check)\b",
]

# Goals that are obviously vague — single imperative verb + object, no detail
_VAGUE_PATTERNS = [
    r"^(improve|fix|update|enhance|make|do|handle|work on|look into|check|review)\s+\w[\w\s]{0,25}$",
    r"^make\s+\w+\s+better\s*$",
    r"^(better|faster|cleaner|simpler)\s+\w[\w\s]{0,20}$",
    r"^(analyse|analyze|investigate|explore)\s+\w[\w\s]{0,25}$",
]


def classify_goal(goal: str) -> SpecQualityResult:
    """
    Classify a task goal for spec completeness.

    Returns a SpecQualityResult with:
      - quality: "ready" | "incomplete" | "vague"
      - score:   0–100
      - missing: list of missing field names
      - feedback: human-readable explanation + suggestions
    """
    if not goal or not goal.strip():
        return SpecQualityResult(
            quality="vague",
            score=0,
            missing=["goal", "success_criterion", "scope_boundary", "acceptance_check"],
            feedback="Goal is empty.",
        )

    text = goal.lower().strip()
    word_count = len(text.split())

    # --- Vague single-phrase check ---
    for pattern in _VAGUE_PATTERNS:
        if re.match(pattern, text):
            return SpecQualityResult(
                quality="vague",
                score=10,
                missing=["success_criterion", "scope_boundary", "acceptance_check"],
                feedback=(
                    f"Goal is too vague: '{goal.strip()[:80]}'. "
                    "Specify what done looks like, what's out of scope, and how to verify."
                ),
            )

    # --- Too short to carry meaning ---
    if word_count < 8:
        return SpecQualityResult(
            quality="vague",
            score=15,
            missing=["success_criterion", "scope_boundary", "acceptance_check"],
            feedback=(
                f"Goal is too short ({word_count} words). "
                "A complete spec needs a success criterion, scope boundary, and acceptance check."
            ),
        )

    # --- Score each required field ---
    score = 25  # base for having a non-trivial goal
    missing: List[str] = []

    has_criterion = any(re.search(p, text) for p in _CRITERION_PATTERNS)
    if has_criterion:
        score += 25
    else:
        missing.append("success_criterion")

    has_scope = any(re.search(p, text) for p in _SCOPE_PATTERNS)
    if has_scope:
        score += 25
    else:
        missing.append("scope_boundary")

    has_acceptance = any(re.search(p, text) for p in _ACCEPTANCE_PATTERNS)
    if has_acceptance:
        score += 25
    else:
        missing.append("acceptance_check")

    if not missing:
        return SpecQualityResult(
            quality="ready",
            score=score,
            missing=[],
            feedback="Spec passes quality gate.",
        )

    suggestions = []
    if "success_criterion" in missing:
        suggestions.append("'Done when: <condition>' — what does success look like?")
    if "scope_boundary" in missing:
        suggestions.append("'Out of scope: <what not to do>' — what should be excluded?")
    if "acceptance_check" in missing:
        suggestions.append("'Verify by: <how to confirm>' — how will we know it worked?")

    return SpecQualityResult(
        quality="incomplete",
        score=score,
        missing=missing,
        feedback=(
            f"Spec missing {len(missing)} field(s). Add:\n"
            + "\n".join(f"  • {s}" for s in suggestions)
        ),
    )
