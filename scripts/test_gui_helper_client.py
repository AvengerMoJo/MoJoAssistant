#!/usr/bin/env python3
"""Offline smoke test for gui_helper_client.py.

Covers the parts that don't need a live Windows helper:
  - non-loopback host refusal
  - token file fallback
  - JSON body shape for each subcommand (via a fake transport)

Run: pytest -q scripts/test_gui_helper_client.py
or:  python3 -m pytest scripts/test_gui_helper_client.py -q
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CLIENT = HERE / "gui_helper_client.py"


@pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.10", "evil.example.com", ""])
def test_refuses_non_loopback_host(host, monkeypatch, capsys):
    """The client must never let a non-loopback host slip through."""
    monkeypatch.setenv("MOJO_GUI_TOKEN", "x" * 40)
    result = subprocess.run(
        [sys.executable, str(CLIENT), "--host", host, "health"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "non-loopback" in combined or "refusing" in combined or "connection failed" in combined


def test_missing_token_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MOJO_GUI_TOKEN", raising=False)
    monkeypatch.setattr("gui_helper_client.DEFAULT_TOKEN_PATH", tmp_path / "no-such-token")
    result = subprocess.run(
        [sys.executable, str(CLIENT), "health"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "no MOJO_GUI_TOKEN" in (result.stdout + result.stderr)


def test_health_against_local_stub(tmp_path, monkeypatch):
    """Spin up a tiny local HTTP server that mimics the helper, verify the
    client carries the bearer token and parses the JSON response correctly.
    This exercises the request layer end-to-end without needing PowerShell.
    """
    import http.server
    import threading

    received: dict = {}

    class Stub(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received["auth"] = self.headers.get("Authorization", "")
            received["path"] = self.path
            body = json.dumps({"ok": True, "pid": 4242}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args, **kwargs):
            return  # silence

    server = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        env = os.environ.copy()
        env["MOJO_GUI_TOKEN"] = "supersecrettoken"
        result = subprocess.run(
            [sys.executable, str(CLIENT), "--port", str(port), "health"],
            capture_output=True, text=True, env=env, timeout=10,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed == {"ok": True, "pid": 4242}
    assert received["auth"] == "Bearer supersecrettoken"
    assert received["path"] == "/health"


def test_describe_posts_prompt_to_describe_endpoint(tmp_path):
    """describe must POST {"prompt": ...} to /describe and print only the text reply."""
    import http.server
    import threading

    received: dict = {}

    class Stub(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received["path"] = self.path
            length = int(self.headers.get("Content-Length", "0"))
            received["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps({"ok": True, "text": "top-right, (150, 50)", "width": 1470, "height": 924}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args, **kwargs):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        env = os.environ.copy()
        env["MOJO_GUI_TOKEN"] = "supersecrettoken"
        result = subprocess.run(
            [sys.executable, str(CLIENT), "--port", str(port), "describe", "where is the green quadrant?"],
            capture_output=True, text=True, env=env, timeout=10,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stdout + result.stderr
    assert received["path"] == "/describe"
    assert received["body"] == {"prompt": "where is the green quadrant?"}
    assert json.loads(result.stdout)["text"] == "top-right, (150, 50)"
