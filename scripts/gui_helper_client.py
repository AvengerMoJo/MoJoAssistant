#!/usr/bin/env python3
"""Client for the authenticated gui_helper.ps1 listener on EVO-X3.

Reads the bearer token from $MOJO_GUI_TOKEN (falls back to
~/.memory/config/gui_helper.token) and sends requests over loopback
only. The listener already rejects anything not bound to 127.0.0.1,
so this client never accepts a non-loopback host.

Usage:
    MOJO_GUI_TOKEN=... python3 gui_helper_client.py launch "C:\\Tools\\foo.exe"
    python3 gui_helper_client.py click 100 200
    python3 gui_helper_client.py type "hello world"
    python3 gui_helper_client.py screenshot out.png
    python3 gui_helper_client.py health
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8766
DEFAULT_TOKEN_PATH = Path.home() / ".memory" / "config" / "gui_helper.token"
DEFAULT_HOST = "127.0.0.1"


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_token() -> str:
    tok = os.environ.get("MOJO_GUI_TOKEN")
    if tok:
        return tok.strip()
    if not DEFAULT_TOKEN_PATH.exists():
        fail(
            f"no MOJO_GUI_TOKEN in env and no token file at {DEFAULT_TOKEN_PATH} "
            f"- start the helper once to generate one"
        )
    return DEFAULT_TOKEN_PATH.read_text(encoding="utf-8").strip()


def request(
    method: str,
    host: str,
    port: int,
    path: str,
    token: str,
    body: dict | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict]:
    if host not in ("127.0.0.1", "localhost", "::1"):
        fail(f"refusing to talk to non-loopback host: {host}")
    url = f"http://{host}:{port}{path}"
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"error": raw}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        fail(f"connection failed: {exc}")


def cmd_health(args, token):
    code, body = request("GET", args.host, args.port, "/health", token)
    print(json.dumps(body, indent=2))
    sys.exit(0 if code == 200 else 1)


def cmd_launch(args, token):
    body = {"path": args.path}
    if args.arg:
        body["args"] = args.arg
    code, body = request("POST", args.host, args.port, "/launch", token, body=body)
    print(json.dumps(body, indent=2))
    sys.exit(0 if code == 200 else 1)


def cmd_click(args, token):
    body = {"x": args.x, "y": args.y}
    if args.button:
        body["button"] = args.button
    code, body = request("POST", args.host, args.port, "/click", token, body=body)
    print(json.dumps(body, indent=2))
    sys.exit(0 if code == 200 else 1)


def cmd_type(args, token):
    code, body = request("POST", args.host, args.port, "/type", token, body={"text": args.text})
    print(json.dumps(body, indent=2))
    sys.exit(0 if code == 200 else 1)


def cmd_screenshot(args, token):
    code, body = request("GET", args.host, args.port, "/screenshot", token)
    if code != 200 or "bytes_base64" not in body:
        print(json.dumps(body, indent=2))
        sys.exit(1)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(body["bytes_base64"]))
    print(f"wrote {out} ({body.get('width')}x{body.get('height')})")


def cmd_describe(args, token):
    code, body = request("POST", args.host, args.port, "/describe", token, body={"prompt": args.prompt})
    print(json.dumps(body, indent=2))
    sys.exit(0 if code == 200 else 1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="gui_helper.ps1 client")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("health")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("launch")
    sp.add_argument("path")
    sp.add_argument("arg", nargs="*")
    sp.set_defaults(func=cmd_launch)

    sp = sub.add_parser("click")
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp.add_argument("--button", choices=["left", "right", "middle"])
    sp.set_defaults(func=cmd_click)

    sp = sub.add_parser("type")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_type)

    sp = sub.add_parser("screenshot")
    sp.add_argument("output")
    sp.set_defaults(func=cmd_screenshot)

    sp = sub.add_parser("describe")
    sp.add_argument("prompt")
    sp.set_defaults(func=cmd_describe)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    token = load_token()
    args.func(args, token)


if __name__ == "__main__":
    main()
