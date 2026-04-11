"""
CapabilityResolver — three-layer capability resolution for agentic tasks.

Resolution order (each layer builds on the previous):

  Layer 1 — System defaults  (config/capability_defaults.json + personal override)
      Tools every agent gets regardless of role.
      ask_user is always_available and can never be removed.
      agent_defaults are category names expanded to tool names.

  Layer 2 — Role capabilities  (role.get("capabilities"))
      What this specific role adds.  Capability category names or explicit
      tool names, expanded via capability_catalog.json + CapabilityRegistry.

  Layer 3 — Runtime override  (task config available_tools)
      What the current task dispatch adds, removes, or replaces.

      Syntax:
        ["terminal", "exec"]        Absolute — replaces the role layer.
                                    System defaults are still applied.
        ["+terminal", "+exec"]      Additive — merged on top of role layer.
        ["-web"]                    Subtractive — removed from merged set.
        Mixed forms are supported.  If ANY entry starts with +/- the whole
        list is treated as a modifier; otherwise it's an absolute override.

  Final step — always_available re-applied after all operations so that
  no runtime override can accidentally strip ask_user.

Two-layer config:
  config/capability_defaults.json  — system defaults (tracked in git)
  ~/.memory/config/capability_defaults.json  — personal overrides (untracked)

  agent_defaults in the personal file extend (not replace) the system list.
  always_available in the personal file is merged with the system list.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class CapabilityResolver:
    """
    Single source of truth for capability → tool name resolution.

    Usage
    -----
        resolver = CapabilityResolver()
        tool_names = resolver.resolve(role, available_tools, tool_registry)

    The result is a stable sorted list of concrete tool names ready to be
    passed to the LLM as the tool schema and to the SecurityGate for enforcement.
    """

    def __init__(self) -> None:
        self._defaults_cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        role: Optional[Dict[str, Any]],
        available_tools: Optional[List[str]],
        tool_registry: Any,  # CapabilityRegistry — avoid circular import
    ) -> List[str]:
        """
        Resolve the final set of tool names for a task.

        Parameters
        ----------
        role            : role dict (may be None for role-less tasks)
        available_tools : from task config (None = not specified)
        tool_registry   : CapabilityRegistry instance for dynamic tool lookup
        """
        defaults = self._load_defaults()
        always = set(defaults.get("always_available", ["ask_user"]))
        default_caps: List[str] = defaults.get("agent_defaults", [])

        # Layer 1: system defaults
        system_tools: Set[str] = set(always)
        system_tools |= set(self._expand(default_caps, tool_registry))

        # Layer 2: role capabilities
        role_tools: Set[str] = set()
        if role:
            role_caps = role.get("capabilities") or []
            role_tools = set(self._expand(role_caps, tool_registry))

        merged = system_tools | role_tools

        # Layer 3: runtime override
        if available_tools is not None:
            merged = self._apply_override(merged, system_tools, available_tools, tool_registry)

        # Always-available survives all overrides
        merged |= always

        result = sorted(merged)
        logger.debug(
            f"CapabilityResolver: system={sorted(system_tools)} "
            f"role={sorted(role_tools)} "
            f"override={available_tools} "
            f"→ {result}"
        )
        return result

    # ------------------------------------------------------------------
    # Override logic
    # ------------------------------------------------------------------

    def _apply_override(
        self,
        merged: Set[str],
        system_tools: Set[str],
        available_tools: List[str],
        tool_registry: Any,
    ) -> Set[str]:
        """
        Apply the runtime available_tools override to the merged set.

        If any entry starts with + or -, treat the whole list as a modifier.
        Otherwise treat it as an absolute replacement of the role layer
        (system defaults are preserved).
        """
        has_modifiers = any(t.startswith(("+", "-")) for t in available_tools)

        if has_modifiers:
            result = set(merged)
            plain: List[str] = []
            for t in available_tools:
                if t.startswith("+"):
                    cap = t[1:]
                    result |= set(self._expand([cap], tool_registry))
                elif t.startswith("-"):
                    cap = t[1:]
                    result -= set(self._expand([cap], tool_registry))
                else:
                    plain.append(t)
            if plain:
                result |= set(self._expand(plain, tool_registry))
            return result
        else:
            # Absolute override: replace role layer, keep system defaults
            override_tools = set(self._expand(available_tools, tool_registry))
            return system_tools | override_tools

    # ------------------------------------------------------------------
    # Capability → tool name expansion (mirrors _resolve_capabilities)
    # ------------------------------------------------------------------

    def _expand(self, capabilities: List[str], tool_registry: Any) -> List[str]:
        """
        Expand a list of capability category names and/or explicit tool names
        into concrete tool names via capability_catalog.json + CapabilityRegistry.
        """
        if not capabilities:
            return []

        try:
            from app.config.config_loader import load_layered_json_config
            catalog = load_layered_json_config("config/capability_catalog.json")
        except Exception:
            catalog = {}

        tool_entries: Dict[str, Any] = catalog.get("tools", {})

        # Collect known category names from catalog + registry
        known_categories: Set[str] = {
            meta.get("category")
            for meta in tool_entries.values()
            if isinstance(meta, dict) and meta.get("category")
        }
        for t_def in getattr(tool_registry, "_tools", {}).values():
            if getattr(t_def, "category", None):
                known_categories.add(t_def.category)

        access_categories = {e for e in capabilities if e in known_categories}
        access_explicit = {e for e in capabilities if e not in known_categories}

        names: List[str] = []
        seen: Set[str] = set()

        # Catalog-defined tools — by category
        for tool_name, tool_meta in tool_entries.items():
            if not isinstance(tool_meta, dict):
                continue
            if tool_meta.get("always_injected") or tool_meta.get("internal"):
                continue
            if tool_meta.get("category") in access_categories:
                names.append(tool_name)
                seen.add(tool_name)

        # Registry-defined tools — by category or explicit name
        for t_name, t_def in getattr(tool_registry, "_tools", {}).items():
            if t_name in seen:
                continue
            cat_meta = tool_entries.get(t_name, {})
            if isinstance(cat_meta, dict) and cat_meta.get("internal"):
                continue
            t_cat = getattr(t_def, "category", None)
            if (t_cat and t_cat in access_categories) or t_name in access_explicit:
                names.append(t_name)
                seen.add(t_name)

        # Explicit names not yet resolved
        for t_name in access_explicit:
            if t_name not in seen:
                if t_name in tool_entries or (
                    hasattr(tool_registry, "get_tool") and tool_registry.get_tool(t_name)
                ):
                    names.append(t_name)

        return names

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_defaults(self) -> Dict[str, Any]:
        if self._defaults_cache is not None:
            return self._defaults_cache
        try:
            from app.config.config_loader import load_layered_json_config
            self._defaults_cache = load_layered_json_config("config/capability_defaults.json")
        except Exception:
            self._defaults_cache = {
                "always_available": ["ask_user"],
                "agent_defaults": ["memory", "orchestration"],
            }
        return self._defaults_cache
