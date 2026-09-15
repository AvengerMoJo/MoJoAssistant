"""Agent bridge config — reads ~/.memory/config/agent_bridge.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".memory" / "config" / "agent_bridge.json"

DEFAULTS: Dict[str, Any] = {
    "bind": "0.0.0.0",
    "port": 8497,
    "password": "",  # bridge BasicAuth password — empty = auto-generate on start
    "hosts": {},
}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or CONFIG_PATH
    cfg: Dict[str, Any] = dict(DEFAULTS)
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            cfg.update({k: v for k, v in raw.items() if k in DEFAULTS})
            if "hosts" in raw and isinstance(raw["hosts"], dict):
                cfg["hosts"].update(raw["hosts"])
        except Exception:
            logger.warning("Failed to parse %s, using defaults", p)
    return cfg
