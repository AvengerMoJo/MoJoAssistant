import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

from app.scheduler import resource_health as rh
from app.scheduler.resource_pool import ResourceManager


class _Handler(BaseHTTPRequestHandler):
    status = 200

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":{"message":"User not found."}}' if type(self).status >= 400 else b'{"choices":[]}')

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", _Handler
    srv.shutdown()


@pytest.mark.parametrize("status,state", [(200, rh.LIVE), (401, rh.AUTH_FAILED), (403, rh.AUTH_FAILED),
                                          (429, rh.LIVE), (500, rh.ERROR)])
def test_completion_probe_classifies_the_answer(server, status, state):
    url, handler = server
    handler.status = status
    assert rh.probe_completion(url, "k", "m").state == state


def test_completion_probe_unreachable():
    assert rh.probe_completion("http://127.0.0.1:9/v1", "k", "m", timeout=2).state == rh.UNREACHABLE


def _pool(tmp_path, monkeypatch):
    data = {
        "quota_pools": {},
        "resources": {},
        "provider_accounts": {"g": {
            "template": {"type": "api", "provider": "openrouter", "base_url": "https://o/api/v1", "tier": "free_api",
                         "health_probe": "completion", "health_probe_interval_s": 3600},
            "accounts": {"a": {"key_var": "KA"}, "b": {"key_var": "KB"}},
            "models": [{"model": "m1:free"}, {"model": "m2:free"}],
        }},
    }
    monkeypatch.setenv("KA", "ka")
    monkeypatch.setenv("KB", "kb")
    monkeypatch.setattr(ResourceManager, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(ResourceManager, "META_FILE", tmp_path / "m.json")
    monkeypatch.setattr(ResourceManager, "SANDBOX_ENV_FILE", tmp_path / "none.env")
    monkeypatch.setattr(ResourceManager, "get_loaded_resource_ids", lambda self: set())
    with patch("app.config.config_loader.load_layered_json_config", return_value=data):
        return ResourceManager(config_path=str(tmp_path / "p.json"))


def test_one_completion_per_account_and_a_refused_account_gates_all_its_models(tmp_path, monkeypatch):
    rm = _pool(tmp_path, monkeypatch)
    calls = []

    def completion(base_url, key, model, timeout=30.0):
        calls.append((key, model))
        return rh.ProbeResult(rh.AUTH_FAILED if key == "ka" else rh.LIVE, "x", 0)

    live_listing = lambda *a, **k: rh.ProbeResult(rh.LIVE, "HTTP 200", 0)
    with patch.object(rh, "probe_endpoint", live_listing), patch.object(rh, "probe_completion", completion):
        rm.probe_all()
        rm.probe_all()  # second pass inside the interval: no new completions
    assert sorted(calls) == [("ka", "m1:free"), ("kb", "m1:free")]
    ids = [r["id"] for r in rm.selection_order() if r["id"].startswith("g_")]
    eligible = {r["id"] for r in rm.selection_order() if r["eligible"]}
    assert not any(i.startswith("g_a_") for i in eligible)
    assert {i for i in eligible if i.startswith("g_b_")} == {i for i in ids if i.startswith("g_b_")}
    reasons = {r["id"]: r.get("excluded_because") or "" for r in rm.selection_order() if r["id"].startswith("g_a_")}
    assert all("auth_failed" in v for v in reasons.values())


def test_a_listing_failure_still_works_without_an_account_probe(tmp_path, monkeypatch):
    rm = _pool(tmp_path, monkeypatch)
    with patch.object(rh, "probe_endpoint", lambda *a, **k: rh.ProbeResult(rh.UNREACHABLE, "down", 0)), \
            patch.object(rh, "probe_completion", lambda *a, **k: rh.ProbeResult(rh.LIVE, "ok", 0)):
        rm.probe_all()
    assert not [r for r in rm.selection_order() if r["eligible"]]
