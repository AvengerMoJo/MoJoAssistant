"""What MoJoAssistant tells the engine's usage ledger about a finished call: counts and labels only, a figure the
provider did not return is unknown (never 0), and a call that cannot be reported is counted and logged."""
import json
import logging
import time

import httpx
import pytest

from app.scheduler.credential_engine_client import CredentialEngineClient, call_ledger_fields


class Engine:
    def __init__(self):
        self.reports = []

    def __call__(self, request):
        path = request.url.path
        if path == "/oauth/authorize":
            return httpx.Response(303, headers={"location": "http://cb?code=abc&state=s"})
        if path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if path == "/api/v1/acquire":
            return httpx.Response(200, json={"lease_id": "lease_1", "expires_at": time.time() + 900, "api_key": "sk-X", "model": "m"})
        if path == "/api/v1/report":
            self.reports.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "available", "duplicate": False})
        return httpx.Response(404)


@pytest.fixture
def engine():
    return Engine()


@pytest.fixture
def client(tmp_path, engine):
    boot = tmp_path / "boot.json"
    boot.write_text(json.dumps({"service_url": "https://public.example", "service_url_local": "http://127.0.0.1:8700",
                                "tenant_id": "tenant_t",
                                "mojoassistant_client": {"client_id": "c", "client_secret": "s", "redirect_uri": "http://cb"}}))
    return CredentialEngineClient(boot, transport=httpx.MockTransport(engine))


def _wait(engine, n=1):
    deadline = time.time() + 5
    while len(engine.reports) < n and time.time() < deadline:
        time.sleep(0.02)
    assert len(engine.reports) >= n, "the report never reached the engine"


def test_tokens_model_and_task_class_reach_the_engine(client, engine):
    client.api_key("r1")
    fields = call_ledger_fields({"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165}, "m-9", 830.44,
                                "scheduler.agentic", "r1")
    client.report("r1", True, ledger=fields)
    _wait(engine)
    sent = engine.reports[0]
    assert (sent["tokens_in"], sent["tokens_out"], sent["model_served"], sent["task_class"]) == (120, 45, "m-9", "scheduler.agentic")
    assert sent["duration_ms"] == 830.4 and len(sent["call_id"]) == 32 and sent["lease_id"] == "lease_1"


def test_missing_usage_is_unknown_not_zero_and_is_logged(caplog):
    with caplog.at_level(logging.INFO):
        fields = call_ledger_fields(None, "m", 10, "chat.role", "r1")
    assert fields["tokens_in"] is None and fields["tokens_out"] is None
    assert "no token counts" in caplog.text


@pytest.mark.parametrize("usage", [{"prompt_tokens": "12", "completion_tokens": 5}, {"prompt_tokens": -1, "completion_tokens": 5},
                                    {"prompt_tokens": True, "completion_tokens": 5}, {"completion_tokens": 5}, "x"])
def test_an_unreadable_figure_is_unknown_never_repaired(usage):
    assert call_ledger_fields(usage)["tokens_in"] is None


def test_unknown_fields_are_not_sent_so_an_old_engine_still_accepts_the_report(client, engine):
    client.api_key("r1")
    client.report("r1", True)                      # no ledger at all
    _wait(engine)
    assert set(engine.reports[0]) == {"lease_id", "success", "error_message"}


def test_each_call_gets_its_own_call_id():
    assert call_ledger_fields({})["call_id"] != call_ledger_fields({})["call_id"]


def test_a_call_with_no_lease_is_counted_and_logged_not_dropped_silently(client, engine, caplog):
    with caplog.at_level(logging.WARNING):
        client.report("never_fetched", True, ledger=call_ledger_fields({}))
        client.report("never_fetched", False, "boom")
    assert client.unreported_calls == 2 and engine.reports == []
    assert "not reported to the credential engine" in caplog.text


def test_the_pool_passes_the_call_details_for_engine_managed_resources_only(tmp_path, monkeypatch):
    from pathlib import Path
    from unittest.mock import patch

    from app.scheduler import credential_engine_client as cec
    from app.scheduler.resource_pool import ResourceManager

    for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                       ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
        monkeypatch.setattr(ResourceManager, attr, tmp_path / name)
    res = {rid: {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "m", "tier": "free_api",
                 "priority": 1, "enabled": True, "context_limit": 1000, "output_limit": 100, **extra}
           for rid, extra in (("managed", {"credential_engine": True}), ("plain", {}))}
    cfg = tmp_path / "pool.json"
    cfg.write_text(json.dumps({"resources": res}))
    with patch("app.config.config_loader.load_layered_json_config", return_value={"resources": res}):
        rm = ResourceManager(config_path=str(cfg))

    class Recorder:
        def __init__(self):
            self.calls = []

        def report(self, resource_id, success, error_message=None, ledger=None):
            self.calls.append((resource_id, success, ledger))

    rec = Recorder()
    monkeypatch.setattr(cec, "get_credential_engine_client", lambda: rec)
    usage = {"prompt_tokens": 7, "completion_tokens": 3}
    rm.record_usage("managed", success=True, token_usage=usage, model_served="m-1", duration_ms=12.0, task_class="chat.role")
    rm.record_usage("plain", success=True, token_usage=usage, model_served="m-1", duration_ms=12.0, task_class="chat.role")
    rm.record_usage("managed", success=False, error_message="boom")             # an older call site: no details
    assert [c[0] for c in rec.calls] == ["managed", "managed"]
    ok, failed = rec.calls[0][2], rec.calls[1][2]
    assert (ok["tokens_in"], ok["tokens_out"], ok["model_served"], ok["task_class"]) == (7, 3, "m-1", "chat.role")
    assert failed["tokens_in"] is None and failed["tokens_out"] is None and failed["call_id"]
