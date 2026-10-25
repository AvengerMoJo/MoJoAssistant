"""Third-party panels in the MoJoAssistant dashboard: a product with its own interface (the credential/resource
manager) is plugged in by CONFIG, not code. Each panel is {id, title, url, mode}:
  mode "iframe" -- shown inside the dashboard under /dashboard/plugins/<id> (the product must allow framing by
                   this dashboard's origin; it keeps its own sign-in)
  mode "link"   -- the nav entry opens the product's own page.
Config: config/dashboard_plugins.json (defaults, none) overridden by ~/.memory/config/dashboard_plugins.json.
A malformed entry is skipped and logged as an error -- it never takes the dashboard down and is never guessed at.
"""
import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from app.config.config_loader import load_layered_json_config

_log = logging.getLogger(__name__)
_ID = re.compile(r"^[a-z0-9_-]{1,40}$")
MODES = ("iframe", "link")


def validate_panel(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("panel must be an object")
    unknown = set(raw) - {"id", "title", "url", "mode"}
    if unknown:
        raise ValueError(f"unknown fields {sorted(unknown)}")
    pid, title, url, mode = raw.get("id"), raw.get("title"), raw.get("url"), raw.get("mode", "iframe")
    if not isinstance(pid, str) or not _ID.match(pid):
        raise ValueError("id must be 1-40 characters of a-z 0-9 _ -")
    if not isinstance(title, str) or not 1 <= len(title) <= 40:
        raise ValueError("title must be 1-40 characters")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("url must be an absolute http(s) URL")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    return {"id": pid, "title": title, "url": url, "mode": mode}


def load_panels() -> List[Dict[str, str]]:
    try:
        cfg = load_layered_json_config("config/dashboard_plugins.json")
    except (OSError, ValueError) as e:
        _log.error("dashboard_plugins.json cannot be read: %s", e)
        return []
    panels, seen = [], set()
    for i, raw in enumerate(cfg.get("panels", [])):
        try:
            p = validate_panel(raw)
            if p["id"] in seen:
                raise ValueError(f"duplicate id {p['id']!r}")
            seen.add(p["id"])
            panels.append(p)
        except ValueError as e:
            _log.error("dashboard_plugins.json panels[%d] skipped: %s", i, e)
    return panels
