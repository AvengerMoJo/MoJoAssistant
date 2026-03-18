"""
Push Adapter Manager

Reads notifications_config.json (layered), instantiates each enabled adapter,
and starts/stops them alongside the server.

Adding a new push channel:
  1. Drop a new file in app/mcp/adapters/push/ implementing PushAdapter
  2. Register it in ADAPTER_REGISTRY below
  3. Add an entry in notifications_config.json.example
  That's it — no other code changes needed.
"""

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Registry: "type" value in config → adapter class
_ADAPTER_REGISTRY: Dict[str, Any] = {}


def _register_builtins():
    from app.mcp.adapters.push.ntfy import NtfyAdapter
    _ADAPTER_REGISTRY["ntfy"] = NtfyAdapter
    # Future: FCM, APNs, Slack, Telegram, etc.


class PushAdapterManager:
    """
    Manages the lifecycle of all configured push adapters.

    Each adapter is an independent reader of the EventLog.
    Starting/stopping one adapter has zero effect on the others.
    """

    def __init__(self, event_log):
        _register_builtins()
        self._event_log = event_log
        self._adapters: List[Any] = []

    def load_and_start(self) -> None:
        """Read config, instantiate enabled adapters, start each one."""
        configs = self._load_config()
        for adapter_cfg in configs:
            if not adapter_cfg.get("enabled", False):
                continue
            adapter_type = adapter_cfg.get("type")
            adapter_id = adapter_cfg.get("id", adapter_type)
            cls = _ADAPTER_REGISTRY.get(adapter_type)
            if cls is None:
                logger.warning(
                    "[push/manager] unknown adapter type '%s' (id=%s) — skipping",
                    adapter_type,
                    adapter_id,
                )
                continue
            try:
                adapter = cls(adapter_id, adapter_cfg, self._event_log)
                adapter.start()
                self._adapters.append(adapter)
                logger.info("[push/manager] started adapter %s (%s)", adapter_id, adapter_type)
            except Exception as exc:
                logger.error(
                    "[push/manager] failed to start adapter %s: %s", adapter_id, exc
                )

    def stop_all(self) -> None:
        """Stop all running adapters."""
        for adapter in self._adapters:
            try:
                adapter.stop()
            except Exception as exc:
                logger.warning("[push/manager] error stopping %s: %s", adapter.adapter_id, exc)
        self._adapters.clear()

    def reload(self) -> None:
        """Stop all adapters and restart from current config. Called on config change."""
        logger.info("[push/manager] reloading adapters")
        self.stop_all()
        self.load_and_start()

    @property
    def adapter_count(self) -> int:
        return len(self._adapters)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> List[Dict[str, Any]]:
        try:
            from app.config.config_loader import load_layered_json_config
            data = load_layered_json_config("config/notifications_config.json")
            adapters = data.get("adapters", [])
            # Tolerate dict-of-dicts format (e.g. {"0": {...}, "1": {...}})
            if isinstance(adapters, dict):
                adapters = list(adapters.values())
            return adapters
        except FileNotFoundError:
            return []
        except Exception as exc:
            logger.warning("[push/manager] failed to load notifications config: %s", exc)
            return []
