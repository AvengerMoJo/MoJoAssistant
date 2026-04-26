"""
CapabilityGapChecker — pre-task validation of capability coverage.

Runs before the agentic loop starts.  Analyzes the goal for signals that
indicate required capability categories, then checks whether those categories
are covered by the resolved tool set.

Design principles
-----------------
- Fast and cheap: keyword heuristics only, no LLM call.
- Non-blocking by default: warnings are logged, not fatal.
- Blockers are surfaced via ask_user (STOP_ASK_USER) so the user can extend
  the capability set before the agent wastes iterations discovering the gap.
- Heuristics are intentionally conservative: false positives (unnecessary
  warnings) are better than false negatives (silent missing capability).

Gap types
---------
  BLOCKER  — the goal explicitly requires a capability the role cannot use.
             Example: "git clone" in a role without terminal/exec.
             Result: ask_user before the loop starts.

  WARNING  — the goal may benefit from a capability that isn't present,
             but a reasonable agent might work around it.
             Example: goal mentions URLs but role has no web capability.
             Result: logged only, loop proceeds.

Extending the signal map
------------------------
Add entries to _CAPABILITY_SIGNALS to teach the checker about new patterns.
Each entry maps a capability category name to a list of goal keyword phrases.
"""
# [hitl-orchestrator: generic]
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Signal map: capability category → goal keyword patterns
# ---------------------------------------------------------------------------

# Phrases that strongly suggest a capability is REQUIRED (blocker level)
_BLOCKER_SIGNALS: Dict[str, List[str]] = {
    "terminal": [
        "git clone", "git pull", "git push", "make build", "make install",
        "npm install", "npm run", "pip install", "go build", "cargo build",
        "chmod", "chown", "systemctl", "tmux", "ssh ", "bash script",
        "shell script", "run command", "execute command",
    ],
    "exec": [
        "bash_exec", "run bash", "execute bash", "shell command",
        "run script", "execute script",
    ],
    "browser": [
        "open browser", "navigate to", "click on", "fill form",
        "take screenshot", "playwright", "selenium",
    ],
}

# Phrases that suggest a capability may be needed (warning level)
_WARNING_SIGNALS: Dict[str, List[str]] = {
    "web": [
        "fetch url", "http request", "api call", "download from",
        "curl ", "wget ", "api.ipify", "ipify.org",
    ],
    "file": [
        "read file", "write file", "edit file", "search in files",
        "create file", "delete file",
    ],
    "memory": [
        "search memory", "remember this", "recall", "from memory",
        "past task", "previous result",
    ],
    "browser": [
        "browser", "web page", "webpage", "navigate", "screenshot",
    ],
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class GapCheckResult:
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def ask_user_question(self) -> str:
        """Format blockers as an ask_user question."""
        lines = ["The task goal requires capabilities this role cannot use:"]
        for b in self.blockers:
            lines.append(f"  - {b}")
        lines.append(
            "\nWould you like to add the missing capabilities to this task "
            "via available_tools, or proceed anyway and let the agent adapt?"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class CapabilityGapChecker:
    """
    Pre-task validation: does the resolved capability set cover the goal?

    Usage
    -----
        checker = CapabilityGapChecker()
        result = checker.check(goal, resolved_tool_names, role)
        if result.has_blockers:
            # surface via ask_user before loop starts
    """

    def check(
        self,
        goal: str,
        resolved_tool_names: List[str],
        role: Optional[Dict[str, Any]] = None,
    ) -> GapCheckResult:
        """
        Check whether the resolved tools plausibly cover the goal.

        Parameters
        ----------
        goal               : task goal text
        resolved_tool_names: tool names from CapabilityResolver.resolve()
        role               : role dict (used for context, not tool names)
        """
        result = GapCheckResult()
        if not goal:
            return result

        goal_lower = goal.lower()
        resolved_categories = self._infer_categories(resolved_tool_names)

        # Check blocker signals
        for cap, phrases in _BLOCKER_SIGNALS.items():
            if cap in resolved_categories:
                continue
            for phrase in phrases:
                if phrase in goal_lower:
                    result.blockers.append(
                        f"Goal mentions '{phrase}' but role has no '{cap}' capability"
                    )
                    break  # one blocker per capability is enough

        # Check warning signals
        for cap, phrases in _WARNING_SIGNALS.items():
            if cap in resolved_categories:
                continue
            for phrase in phrases:
                if phrase in goal_lower:
                    result.warnings.append(
                        f"Goal may need '{cap}' capability ('{phrase}' detected)"
                    )
                    break

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _infer_categories(self, tool_names: List[str]) -> Set[str]:
        """
        Infer capability categories from resolved tool names.
        Uses catalog lookup + name-prefix heuristics.
        """
        categories: Set[str] = set()
        try:
            from app.config.config_loader import load_layered_json_config
            catalog = load_layered_json_config("config/capability_catalog.json")
            tool_entries: Dict[str, Any] = catalog.get("tools", {})
        except Exception:
            tool_entries = {}

        for t in tool_names:
            # Catalog lookup
            meta = tool_entries.get(t)
            if isinstance(meta, dict) and meta.get("category"):
                categories.add(meta["category"])
                continue
            # Name-prefix heuristics for MCP server tools
            if t.startswith("tmux__"):
                categories.add("terminal")
            elif t.startswith("playwright__"):
                categories.add("browser")
            elif t in ("bash_exec",):
                categories.add("exec")
            elif t in ("web_search", "fetch_url"):
                categories.add("web")
            elif t in ("memory_search", "add_conversation"):
                categories.add("memory")

        return categories
