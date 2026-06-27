"""
MessengerAdapter registry — discovers adapters from three sources:

  1. Built-in   — app/mcp/adapters/messenger/*.py (ships with MoJo)
  2. Entry point — pip-installed plugins that declare mojoassistant.messenger
  3. Drop-in    — ~/.memory/plugins/messenger/*.py (no install required)

Priority: first registration wins per adapter_type, so drop-ins can override
built-ins for power users.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Dict, Iterator, Optional, Type

from app.mcp.adapters.messenger.base import MessengerAdapter

logger = logging.getLogger("mojo_assistant.messenger.registry")

# adapter_type string → class
_REGISTRY: Dict[str, Type[MessengerAdapter]] = {}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def register(cls: Type[MessengerAdapter]) -> Type[MessengerAdapter]:
    """Register a MessengerAdapter subclass. Usable as a decorator.

    Example:
        @register
        class MyAdapter(MessengerAdapter):
            adapter_type = "my_platform"
            ...
    """
    if not cls.adapter_type:
        logger.debug("[messenger/registry] skipping %s — no adapter_type set", cls.__name__)
        return cls
    if cls.adapter_type in _REGISTRY:
        logger.debug(
            "[messenger/registry] '%s' already registered by %s — skipping %s",
            cls.adapter_type, _REGISTRY[cls.adapter_type].__name__, cls.__name__,
        )
        return cls
    _REGISTRY[cls.adapter_type] = cls
    logger.debug("[messenger/registry] registered '%s' (%s)", cls.adapter_type, cls.__name__)
    return cls


def get(adapter_type: str) -> Optional[Type[MessengerAdapter]]:
    """Return the class for adapter_type, or None if not registered."""
    return _REGISTRY.get(adapter_type)


def all_types() -> Iterator[str]:
    return iter(_REGISTRY)


def load_all() -> None:
    """Discover and register from all three sources (idempotent)."""
    _load_builtins()
    _load_entry_points()
    _load_plugin_dir()


# ------------------------------------------------------------------
# Discovery — private
# ------------------------------------------------------------------

def _load_builtins() -> None:
    """Import built-in adapters. Add new ones here."""
    _safe_import("app.mcp.adapters.messenger.discord")
    _safe_import("app.mcp.adapters.messenger.telegram")


def _load_entry_points() -> None:
    """Load adapters published via pyproject.toml entry points.

    Any pip-installable package can contribute a messenger adapter:
        [project.entry-points."mojoassistant.messenger"]
        my_platform = "my_package.module:MyAdapter"
    """
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="mojoassistant.messenger")
        for ep in eps:
            try:
                cls = ep.load()
                if isinstance(cls, type) and issubclass(cls, MessengerAdapter):
                    register(cls)
                    logger.info("[messenger/registry] entry_point '%s' loaded", ep.name)
                else:
                    logger.warning(
                        "[messenger/registry] entry_point '%s' is not a MessengerAdapter subclass",
                        ep.name,
                    )
            except Exception as exc:
                logger.warning(
                    "[messenger/registry] entry_point '%s' failed to load: %s", ep.name, exc
                )
    except Exception as exc:
        logger.debug("[messenger/registry] entry_points scan skipped: %s", exc)


def _load_plugin_dir() -> None:
    """Load adapters from ~/.memory/plugins/messenger/ (drop-in, no install needed).

    Each .py file in that directory should contain exactly one MessengerAdapter
    subclass. Files starting with _ are ignored.
    """
    plugin_dir = Path(os.path.expanduser("~/.memory/plugins/messenger"))
    if not plugin_dir.exists():
        return
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"mojo_messenger_plugin_{path.stem}", path
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            found = 0
            for name in dir(mod):
                obj = getattr(mod, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, MessengerAdapter)
                    and obj is not MessengerAdapter
                    and obj.adapter_type
                ):
                    register(obj)
                    found += 1
            if found:
                logger.info(
                    "[messenger/registry] plugin '%s' loaded %d adapter(s)", path.name, found
                )
            else:
                logger.warning(
                    "[messenger/registry] plugin '%s' has no MessengerAdapter subclass", path.name
                )
        except Exception as exc:
            logger.warning(
                "[messenger/registry] plugin '%s' failed: %s", path.name, exc
            )


def _safe_import(module_path: str) -> None:
    try:
        importlib.import_module(module_path)
    except Exception as exc:
        logger.debug("[messenger/registry] built-in '%s' skipped: %s", module_path, exc)
