"""
Tests for CodingAgentExecutor's permission auto-grant logic.

Found live 2026-07-30: OpenCode's own /permission API never populates the
directory/patterns fields for external_directory-type permission requests
(confirmed by inspecting the coding-agent-mcp-tool submodule, which proxies
the raw response with zero normalization), so the existing prefix-based
auto-grant check could never match them — every such permission escalated
to the user regardless of how safe it actually was. This adds a config-driven
opt-in (auto_approve_external_directory on a server's config entry) so a
specific project can treat these as pre-approved instead.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.scheduler.coding_agent_executor import CodingAgentExecutor


def _make_executor() -> CodingAgentExecutor:
    return CodingAgentExecutor(resource_manager=SimpleNamespace())


class TestServerAutoApprovesExternalDirectory:
    def test_defaults_false_when_flag_absent(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git")]
        )
        executor._get_registry = lambda: None  # already "loaded"
        assert executor._server_auto_approves_external_directory("git@github.com:x/y.git") is False

    def test_true_when_flag_set_on_matching_entry(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(
            servers=[
                SimpleNamespace(id="git@github.com:x/y.git", auto_approve_external_directory=True),
                SimpleNamespace(id="git@github.com:other/repo.git", auto_approve_external_directory=False),
            ]
        )
        executor._get_registry = lambda: None
        assert executor._server_auto_approves_external_directory("git@github.com:x/y.git") is True
        assert executor._server_auto_approves_external_directory("git@github.com:other/repo.git") is False

    def test_false_when_server_id_not_found(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(servers=[])
        executor._get_registry = lambda: None
        assert executor._server_auto_approves_external_directory("does-not-exist") is False

    def test_false_when_server_id_is_none(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(servers=[])
        executor._get_registry = lambda: None
        assert executor._server_auto_approves_external_directory(None) is False


class TestSendWithPermissionWatchExternalDirectoryAutoApprove:
    """
    Uses real (short) timing rather than mocking asyncio.sleep — the poll loop
    checks send_task.done() both before and after each sleep, so mocking sleep
    to be instant races the mocked send_message coroutine's own scheduling and
    produces flaky/incorrect results. Each test takes ~3s (one real poll tick).
    """

    @pytest.mark.asyncio
    async def test_external_directory_escalates_when_flag_not_set(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = False

        never_set = asyncio.Event()
        backend = AsyncMock()

        async def _send_message(session_id, content):
            await never_set.wait()  # blocks until the poll loop cancels it
            return {"parts": []}

        backend.send_message = _send_message
        backend.list_permissions = AsyncMock(
            return_value=[{"requestID": "perm1", "title": "external_directory", "directory": "", "patterns": []}]
        )

        result = await executor._send_with_permission_watch(backend, "sess1", "do something")

        assert result["status"] == "permission_required"
        assert result["permission_id"] == "perm1"
        backend.respond_to_permission.assert_not_called()

    @pytest.mark.asyncio
    async def test_external_directory_auto_approved_when_flag_set(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = True

        never_set = asyncio.Event()
        calls = {"n": 0}

        async def _send_message(session_id, content):
            calls["n"] += 1
            if calls["n"] == 1:
                await never_set.wait()  # first attempt: blocks until cancelled by grant
            return {"parts": [{"type": "text", "text": "done"}]}

        backend = AsyncMock()
        backend.send_message = _send_message
        backend.list_permissions = AsyncMock(
            side_effect=[
                [{"requestID": "perm1", "title": "external_directory", "directory": "", "patterns": []}],
                [],  # no more pending permissions after grant
            ]
        )
        backend.respond_to_permission = AsyncMock(return_value=None)

        result = await executor._send_with_permission_watch(backend, "sess1", "do something")

        backend.respond_to_permission.assert_awaited_once_with(
            "sess1", "perm1", "always", directory=""
        )
        assert result["status"] == "completed"
        assert result["result"] == "done"


class TestServerModelOverride:
    """
    Found live 2026-07-30: a project's default OpenCode provider/model
    (zai-coding-plan/glm-5.1) hit a 5-hour usage-window rate limit; OpenCode
    silently retried forever with no error surfaced through its HTTP API, so
    from CodingAgentExecutor's side every call just looked like a timeout.
    model_override lets a project opt in to a different provider/model
    (e.g. OpenCode's own free "big-pickle") per-message as a manual stopgap.
    """

    def test_returns_none_when_absent(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git")]
        )
        executor._get_registry = lambda: None
        assert executor._server_model_override("git@github.com:x/y.git") is None

    def test_returns_override_when_set(self):
        executor = _make_executor()
        override = {"providerID": "opencode", "modelID": "big-pickle"}
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git", model_override=override)]
        )
        executor._get_registry = lambda: None
        assert executor._server_model_override("git@github.com:x/y.git") == override

    def test_ignores_incomplete_override(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git", model_override={"providerID": "opencode"})]
        )
        executor._get_registry = lambda: None
        assert executor._server_model_override("git@github.com:x/y.git") is None

    @pytest.mark.asyncio
    async def test_send_with_permission_watch_passes_model_override(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = False
        executor._model_override = {"providerID": "opencode", "modelID": "big-pickle"}

        backend = AsyncMock()
        backend.send_message = AsyncMock(return_value={"parts": [{"type": "text", "text": "OK"}]})
        backend.list_permissions = AsyncMock(return_value=[])

        result = await executor._send_with_permission_watch(backend, "sess1", "hi")

        backend.send_message.assert_awaited_once_with(
            "sess1", "hi", model={"providerID": "opencode", "modelID": "big-pickle"}
        )
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_send_with_permission_watch_omits_model_kwarg_when_unset(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = False
        executor._model_override = None

        backend = AsyncMock()
        backend.send_message = AsyncMock(return_value={"parts": [{"type": "text", "text": "OK"}]})
        backend.list_permissions = AsyncMock(return_value=[])

        await executor._send_with_permission_watch(backend, "sess1", "hi")

        backend.send_message.assert_awaited_once_with("sess1", "hi")
