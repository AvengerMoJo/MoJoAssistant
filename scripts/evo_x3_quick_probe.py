#!/usr/bin/env python3
"""Quick probe for the evo-x3 OpenCode host: list sessions via /session."""

import json
import sys
from pathlib import Path

import requests

CONFIG_PATH = Path.home() / ".memory" / "config" / "agent_bridge.json"
HOST_KEY = "evo-x3"
REQUEST_TIMEOUT = 10


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def load_host_config() -> tuple[str, str]:
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"Config file not found: {CONFIG_PATH}")
    except OSError as exc:
        fail(f"Cannot read config file {CONFIG_PATH}: {exc}")

    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"Malformed JSON in {CONFIG_PATH}: {exc}")

    host = (config.get("hosts") or {}).get(HOST_KEY)
    if not isinstance(host, dict):
        fail(f"Host '{HOST_KEY}' not found in {CONFIG_PATH}")

    base_url = host.get("base_url")
    password = host.get("password")
    if not base_url or not password:
        fail(f"Host '{HOST_KEY}' is missing base_url or password")

    return base_url.rstrip("/"), password


def main() -> None:
    base_url, password = load_host_config()
    url = f"{base_url}/session"

    try:
        resp = requests.get(
            url,
            auth=("opencode", password),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        fail(f"Request to {url} timed out after {REQUEST_TIMEOUT}s")
    except requests.exceptions.ConnectionError as exc:
        fail(f"Connection error reaching {url}: {exc}")
    except requests.exceptions.RequestException as exc:
        fail(f"Request to {url} failed: {exc}")

    if resp.status_code != 200:
        fail(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        sessions = resp.json()
    except ValueError:
        fail(f"{url} returned non-JSON body: {resp.text[:200]}")

    if not isinstance(sessions, list):
        fail(f"Unexpected response shape from {url}: expected list, got {type(sessions).__name__}")

    print(f"Sessions: {len(sessions)}")
    if sessions:
        first = sessions[0]
        session_id = first.get("id") if isinstance(first, dict) else None
        if session_id is None:
            fail("First session has no 'id' field")
        print(f"First session id: {session_id}")


if __name__ == "__main__":
    main()
