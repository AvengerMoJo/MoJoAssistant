"""HITLManager — registry and lifecycle owner for all HITL adapters."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from app.mcp.adapters.hitl.base import HITLAdapter

logger = logging.getLogger(f"mojo_assistant.{__name__}")

# ---------------------------------------------------------------------------
# Adapter registry — populated by each concrete adapter module at import time
# ---------------------------------------------------------------------------
_ADAPTER_REGISTRY: Dict[str, Type[HITLAdapter]] = {}


def register_adapter_type(cls: Type[HITLAdapter]) -> Type[HITLAdapter]:
    """Decorator: register an HITLAdapter subclass by its adapter_type string."""
    if cls.adapter_type:
        _ADAPTER_REGISTRY[cls.adapter_type] = cls
    return cls


def _ensure_builtins_registered() -> None:
    """Lazy-import built-in adapters so they register themselves."""
    if "discord_owner" not in _ADAPTER_REGISTRY:
        from app.mcp.adapters.hitl import discord as _  # noqa: F401


class HITLManager:
    """Instantiates, starts, and broadcasts to configured HITL adapters.

    Config shape (from notifications_config.json, key "hitl"):
    {
      "hitl": {
        "discord_owner": {
          "enabled": true,
          "channel_id": "123456789"
        }
      }
    }
    """

    def __init__(self) -> None:
        self._adapters: List[HITLAdapter] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load_from_config(cls, config_path: Optional[str] = None) -> "HITLManager":
        _ensure_builtins_registered()
        mgr = cls()
        cfg_path = config_path or os.path.expanduser("~/.memory/config/notifications_config.json")
        try:
            raw = json.loads(Path(cfg_path).read_text())
            hitl_cfg = raw.get("hitl", {})
        except FileNotFoundError:
            logger.info("[hitl/manager] config not found at %s — no adapters loaded", cfg_path)
            return mgr
        except Exception as exc:
            logger.warning("[hitl/manager] failed to read config: %s", exc)
            return mgr

        for adapter_type, adapter_cfg in hitl_cfg.items():
            if not isinstance(adapter_cfg, dict):
                continue
            if not adapter_cfg.get("enabled", True):
                continue
            cls_ref = _ADAPTER_REGISTRY.get(adapter_type)
            if cls_ref is None:
                logger.warning("[hitl/manager] unknown adapter type '%s' — skipping", adapter_type)
                continue
            adapter = cls_ref(adapter_id=adapter_type, config=adapter_cfg)
            mgr._adapters.append(adapter)
            logger.info("[hitl/manager] loaded adapter '%s'", adapter_type)

        return mgr

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: Any) -> None:
        for adapter in self._adapters:
            adapter.set_scheduler(scheduler)

    async def start(self) -> None:
        for adapter in self._adapters:
            try:
                await adapter.start()
            except Exception as exc:
                logger.error("[hitl/manager] failed to start '%s': %s", adapter.adapter_id, exc)

    async def stop(self) -> None:
        for adapter in self._adapters:
            try:
                await adapter.stop()
            except Exception as exc:
                logger.warning("[hitl/manager] error stopping '%s': %s", adapter.adapter_id, exc)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def send_hitl(self, task_id: str, question: str, choices: List[str]) -> None:
        for adapter in self._adapters:
            try:
                await adapter.send_hitl(task_id, question, choices)
            except Exception as exc:
                logger.error(
                    "[hitl/manager] send_hitl failed for '%s': %s", adapter.adapter_id, exc
                )

    async def send_notification(self, title: str, body: str, severity: str = "info") -> None:
        for adapter in self._adapters:
            try:
                await adapter.send_notification(title, body, severity)
            except Exception as exc:
                logger.error(
                    "[hitl/manager] send_notification failed for '%s': %s",
                    adapter.adapter_id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def adapters(self) -> List[HITLAdapter]:
        return list(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)
