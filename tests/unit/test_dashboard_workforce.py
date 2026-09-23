"""Unit tests for the dashboard's /dashboard/workforce page.

This is the actual personal web UI (https://ai.avengergear.com/dashboard)
that surfaces the agent_bridge fleet -- distinct from the agent_fleet MCP
tool itself (tests/unit/test_agent_bridge.py). Added after the MCP tool
shipped without a corresponding UI update, which the user correctly
flagged as "the dashboard has no update."
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dashboard import router as dashboard_router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(dashboard_router, "verify_token", lambda token: True)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    return TestClient(app, cookies={"mojo_dash": "anything"})


async def test_workforce_page_shows_mixed_backend_hosts(client, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    monkeypatch.setattr(
        "app.mcp.agent_bridge.config.load_config",
        lambda: {"hosts": {
            "worker-gpu": {
                "base_url": "http://worker-gpu:4096", "password": "pw",
                "owner": "personal",
                "location": {"region": "home", "provider": "self-hosted"},
                "profile": {"hardware_accel": ["amd-directml"], "capabilities": ["text", "graphics"]},
                "tier": {"type": "free", "backend": "self-hosted-local"},
            },
            "worker-customer": {
                "base_url": "http://worker-customer:4096", "password": "pw",
                "owner": "customer",
                "owner_note": "CUSTOMER-OWNED: client infra",
                "location": {"region": "remote", "provider": "client"},
                "tier": {"type": "free", "backend": "self-hosted-local"},
            },
            "worker-legacy": {
                "base_url": "http://worker-legacy:4097/mcp", "backend": "legacy_mcp",
                "location": {"region": "home", "provider": "self-hosted"},
                "tier": {"type": "free", "backend": "self-hosted-local"},
            },
        }},
    )
    monkeypatch.setattr(srv, "_check_legacy_mcp", AsyncMock(
        return_value={"status": "ok", "url": "http://worker-legacy:4097/mcp"}
    ))

    resp = client.get("/dashboard/workforce")
    assert resp.status_code == 200
    body = resp.text
    assert "worker-gpu" in body
    assert "worker-customer" in body
    assert "worker-legacy" in body
    assert "virtual interface" in body  # legacy_mcp callout is visible
    assert "amd-directml" in body
    assert "CUSTOMER" in body  # owner boundary is surfaced
    assert "PERSONAL" in body


async def test_workforce_page_empty_registry_shows_placeholder(client, monkeypatch):
    monkeypatch.setattr("app.mcp.agent_bridge.config.load_config", lambda: {"hosts": {}})

    resp = client.get("/dashboard/workforce")
    assert resp.status_code == 200
    assert "No hosts registered" in resp.text


async def test_workforce_page_requires_auth(monkeypatch):
    monkeypatch.setattr(dashboard_router, "verify_token", lambda token: False)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/dashboard/workforce")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard/login"
