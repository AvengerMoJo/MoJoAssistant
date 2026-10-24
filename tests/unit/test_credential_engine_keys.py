"""Engine-sourced keys: a resource with credential_engine=true gets its key from the engine at the moment of
use, never from env or config, and fails loudly when the engine cannot supply it."""
import json
import time
from unittest.mock import patch

import httpx
import pytest

from app.scheduler import credential_engine_client as cec
from app.scheduler.credential_engine_client import CredentialEngineClient, CredentialEngineError
from app.scheduler.resource_pool import ResourceManager


class FakeEngine:
    """Stands in for the service: OAuth endpoints + /api/v1. Records every request."""

    def __init__(self):
        self.requests, self.grant_acquire, self.key, self.lease_ttl = [], True, "sk-ENGINE", 900
        self.acquire_status, self.n = 200, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path, request.headers.get("authorization")))
        path = request.url.path
        if path == "/oauth/authorize":
            if not self.grant_acquire:
                return httpx.Response(303, headers={"location": "http://cb?error=access_denied"})
            return httpx.Response(303, headers={"location": "http://cb?code=abc&state=s"})
        if path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if path == "/api/v1/acquire":
            if self.acquire_status != 200:
                return httpx.Response(self.acquire_status, json={"error": "no resource can serve this request: x"})
            self.n += 1
            return httpx.Response(200, json={"lease_id": f"lease_{self.n}", "expires_at": time.time() + self.lease_ttl,
                                             "api_key": self.key, "model": "m"})
        if path == "/api/v1/report":
            return httpx.Response(200, json={"status": "available"})
        return httpx.Response(404)


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(tmp_path, engine):
    boot = tmp_path / "boot.json"
    boot.write_text(json.dumps({"service_url": "https://public.example", "service_url_local": "http://127.0.0.1:8700",
                                "tenant_id": "tenant_t",
                                "mojoassistant_client": {"client_id": "c", "client_secret": "s", "redirect_uri": "http://cb"}}))
    return CredentialEngineClient(boot, transport=httpx.MockTransport(engine))


def test_key_is_fetched_once_per_lease_and_renewed_before_it_expires(client, engine):
    assert client.api_key("r1") == "sk-ENGINE"
    assert client.api_key("r1") == "sk-ENGINE"
    assert sum(1 for _, p, _ in engine.requests if p == "/api/v1/acquire") == 1
    client._held["r1"].expires_at = time.time() + 30          # inside the refresh margin
    client.api_key("r1")
    assert sum(1 for _, p, _ in engine.requests if p == "/api/v1/acquire") == 2


def test_the_token_is_requested_for_the_acquire_scope_of_the_tenant(client, engine):
    client.api_key("r1")
    assert ("POST", "/oauth/authorize", None) in engine.requests
    assert engine.requests[-1][2] == "Bearer tok"


def test_a_scope_the_owner_has_not_granted_is_a_loud_error(client, engine):
    engine.grant_acquire = False
    with pytest.raises(CredentialEngineError, match="was not issued"):
        client.api_key("r1")


def test_engine_refusing_a_resource_is_a_loud_error_not_an_empty_key(client, engine):
    engine.acquire_status = 409
    with pytest.raises(CredentialEngineError, match="no resource can serve"):
        client.api_key("r1")


def test_engine_down_is_a_loud_error(tmp_path):
    boot = tmp_path / "b.json"
    boot.write_text(json.dumps({"service_url": "http://x", "service_url_local": "http://127.0.0.1:9", "tenant_id": "t",
                                "mojoassistant_client": {"client_id": "c", "client_secret": "s", "redirect_uri": "http://cb"}}))
    with pytest.raises(CredentialEngineError, match="unreachable"):
        CredentialEngineClient(boot).api_key("r1")


def test_loopback_is_preferred_over_the_public_url(client):
    assert str(client._http.base_url).startswith("http://127.0.0.1:8700")


def test_report_goes_to_the_latest_lease_and_only_after_a_key_was_fetched(client, engine):
    client.report("r1", False, "boom")                      # nothing fetched: nothing to report on
    time.sleep(0.1)
    assert not any(p == "/api/v1/report" for _, p, _ in engine.requests)
    client.api_key("r1")
    client.report("r1", False, "boom")
    for _ in range(50):
        if any(p == "/api/v1/report" for _, p, _ in engine.requests):
            break
        time.sleep(0.02)
    assert any(p == "/api/v1/report" for _, p, _ in engine.requests)


# ── the pool ────────────────────────────────────────────────────────────────────────────────

def _pool(tmp_path, monkeypatch, client, engine_flag=True, env_key="sk-LOCAL-ENV"):
    data = {"resources": {"r1": {"type": "api", "provider": "openai", "base_url": "https://api.example/v1", "model": "m",
                                 "tier": "free_api", "priority": 1, "key_var": "R1_KEY", "credential_engine": engine_flag}}}
    monkeypatch.setenv("R1_KEY", env_key)
    monkeypatch.setattr(ResourceManager, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(ResourceManager, "META_FILE", tmp_path / "m.json")
    monkeypatch.setattr(ResourceManager, "SANDBOX_ENV_FILE", tmp_path / "none.env")
    monkeypatch.setattr(ResourceManager, "get_loaded_resource_ids", lambda self: set())
    monkeypatch.setattr(cec, "_client", client)
    with patch("app.config.config_loader.load_layered_json_config", return_value=data):
        return ResourceManager(config_path=str(tmp_path / "p.json"))


def test_an_engine_resource_reads_its_key_from_the_engine_not_from_env(tmp_path, monkeypatch, client, engine):
    rm = _pool(tmp_path, monkeypatch, client)
    r = rm.acquire()
    assert r.id == "r1" and r.api_key == "sk-ENGINE"        # env had sk-LOCAL-ENV; it was not used
    assert r.api_key_env is None and "sk-ENGINE" not in repr(r)


def test_without_the_flag_the_env_key_is_used_as_before(tmp_path, monkeypatch, client, engine):
    rm = _pool(tmp_path, monkeypatch, client, engine_flag=False)
    assert rm.acquire().api_key == "sk-LOCAL-ENV"
    assert not [p for _, p, _ in engine.requests]            # the engine was never contacted


def test_engine_down_means_the_key_read_fails_not_that_the_env_key_is_used(tmp_path, monkeypatch, client, engine):
    rm = _pool(tmp_path, monkeypatch, client)
    engine.acquire_status = 409
    r = rm.acquire()
    with pytest.raises(CredentialEngineError):
        r.api_key


def test_an_engine_resource_without_a_local_key_is_not_disabled_for_lacking_one(tmp_path, monkeypatch, client):
    monkeypatch.delenv("R1_KEY", raising=False)
    rm = _pool(tmp_path, monkeypatch, client, env_key="")
    assert rm._resources["r1"].enabled and rm.acquire().id == "r1"


def test_call_outcomes_of_an_engine_resource_are_reported(tmp_path, monkeypatch, client, engine):
    rm = _pool(tmp_path, monkeypatch, client)
    rm.acquire().api_key                                      # take a lease
    rm.record_usage("r1", success=False, error_message="boom")
    for _ in range(50):
        if any(p == "/api/v1/report" for _, p, _ in engine.requests):
            break
        time.sleep(0.02)
    assert any(p == "/api/v1/report" for _, p, _ in engine.requests)


def test_a_key_the_provider_refused_is_dropped_so_a_rotated_key_is_picked_up(client, engine):
    assert client.api_key("r1") == "sk-ENGINE"
    engine.key = "sk-ROTATED"
    assert client.api_key("r1") == "sk-ENGINE"                 # still inside its lease: no round trip
    client.report("r1", False, "Error code: 401 - invalid api key")
    assert client.api_key("r1") == "sk-ROTATED"                # refused key dropped; the engine is asked again


def test_an_ordinary_failure_keeps_the_held_key(client, engine):
    client.api_key("r1")
    client.report("r1", False, "Error code: 500 - upstream timeout")
    client.report("r1", True)
    assert sum(1 for _, p, _ in engine.requests if p == "/api/v1/acquire") == 1
