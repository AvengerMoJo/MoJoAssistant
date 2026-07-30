"""
Tests for CodingAgentExecutor's automatic quota-exhaustion fallback.

Found live 2026-07-30: OpenCode retries a rate-limited call silently
forever and never surfaces the underlying provider error through its HTTP
API — every send_message from MoJoAssistant's side just looks like a hang.
The real error ("AI_APICallError: Usage limit reached for 5 hour. Your
limit will reset at ...") only ever appeared in OpenCode's own log file,
and it cost ~40 minutes to notice and manually apply a model override.
This automates that: on a send_message timeout, tail OpenCode's log for
this session and, if a quota-exhaustion is found, auto-apply the
project's configured quota_fallback_model for subsequent calls.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.scheduler.coding_agent_executor import CodingAgentExecutor


def _make_executor() -> CodingAgentExecutor:
    return CodingAgentExecutor(resource_manager=SimpleNamespace())


_REAL_QUOTA_LINE = (
    'timestamp=2026-07-30T05:53:11.316Z level=ERROR run=5def60c6 message="stream error" '
    'providerID=zai-coding-plan modelID=glm-5.1 session.id=ses_TARGET small=false agent=build '
    'mode=primary error.error="AI_APICallError: Usage limit reached for 5 hour. '
    'Your limit will reset at 2026-07-30 15:04:03"\n'
)
_STREAM_START_LINE = (
    'timestamp=2026-07-30T05:53:19.325Z level=INFO run=5def60c6 message=stream '
    'providerID=zai-coding-plan modelID=glm-5.1 session.id=ses_TARGET small=false '
    'agent=build mode=primary\n'
)
_UNRELATED_SESSION_LINE = _REAL_QUOTA_LINE.replace("ses_TARGET", "ses_OTHER")
_GENERIC_ERROR_LINE = (
    'timestamp=2026-07-30T05:53:11.316Z level=ERROR run=5def60c6 message="stream error" '
    'providerID=zai-coding-plan modelID=glm-5.1 session.id=ses_TARGET small=false agent=build '
    'mode=primary error.error="Connection reset by peer"\n'
)


class TestOpencodeLogShowsQuotaExhaustion:
    def _write_log(self, tmp_path, lines):
        log_dir = tmp_path / ".local" / "share" / "opencode" / "log"
        log_dir.mkdir(parents=True)
        log_path = log_dir / "opencode.log"
        log_path.write_text("".join(lines), encoding="utf-8")
        return tmp_path

    def test_true_when_most_recent_line_for_session_is_quota_error(self, tmp_path, monkeypatch):
        home = self._write_log(tmp_path, [_STREAM_START_LINE, _REAL_QUOTA_LINE])
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert CodingAgentExecutor._opencode_log_shows_quota_exhaustion("ses_TARGET") is True

    def test_false_when_session_later_recovered(self, tmp_path, monkeypatch):
        home = self._write_log(tmp_path, [_REAL_QUOTA_LINE, _STREAM_START_LINE])
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert CodingAgentExecutor._opencode_log_shows_quota_exhaustion("ses_TARGET") is False

    def test_false_for_unrelated_session(self, tmp_path, monkeypatch):
        home = self._write_log(tmp_path, [_UNRELATED_SESSION_LINE])
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert CodingAgentExecutor._opencode_log_shows_quota_exhaustion("ses_TARGET") is False

    def test_false_for_generic_non_quota_error(self, tmp_path, monkeypatch):
        home = self._write_log(tmp_path, [_GENERIC_ERROR_LINE])
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        assert CodingAgentExecutor._opencode_log_shows_quota_exhaustion("ses_TARGET") is False

    def test_false_when_log_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert CodingAgentExecutor._opencode_log_shows_quota_exhaustion("ses_TARGET") is False


class TestServerQuotaFallbackModel:
    def test_returns_none_when_absent(self):
        executor = _make_executor()
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git")]
        )
        executor._get_registry = lambda: None
        assert executor._server_quota_fallback_model("git@github.com:x/y.git") is None

    def test_returns_fallback_when_set(self):
        executor = _make_executor()
        fallback = {"providerID": "opencode", "modelID": "big-pickle"}
        executor._servers_config = SimpleNamespace(
            servers=[SimpleNamespace(id="git@github.com:x/y.git", quota_fallback_model=fallback)]
        )
        executor._get_registry = lambda: None
        assert executor._server_quota_fallback_model("git@github.com:x/y.git") == fallback


class TestSendWithPermissionWatchAutoFallback:
    @pytest.mark.asyncio
    async def test_timeout_with_quota_exhaustion_applies_fallback(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = False
        executor._model_override = None
        executor._quota_fallback_model = {"providerID": "opencode", "modelID": "big-pickle"}

        never_set = asyncio.Event()
        backend = AsyncMock()

        async def _send_message(session_id, content, **kwargs):
            await never_set.wait()
            return {"parts": []}

        backend.send_message = _send_message
        backend.list_permissions = AsyncMock(return_value=[])

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch.object(
                 CodingAgentExecutor, "_opencode_log_shows_quota_exhaustion", return_value=True
             ):
            # Fast-forward the 280s deadline without a real 280s wait.
            fake_time = {"t": 0.0}

            class _FakeLoop:
                def time(self):
                    fake_time["t"] += 300.0
                    return fake_time["t"]

            mock_loop.return_value = _FakeLoop()
            result = await executor._send_with_permission_watch(backend, "sess1", "hi")

        assert result["status"] == "timeout"
        assert executor._model_override == {"providerID": "opencode", "modelID": "big-pickle"}

    @pytest.mark.asyncio
    async def test_timeout_without_quota_exhaustion_leaves_override_unset(self):
        executor = _make_executor()
        executor._auto_approve_external_directory = False
        executor._model_override = None
        executor._quota_fallback_model = {"providerID": "opencode", "modelID": "big-pickle"}

        never_set = asyncio.Event()
        backend = AsyncMock()

        async def _send_message(session_id, content, **kwargs):
            await never_set.wait()
            return {"parts": []}

        backend.send_message = _send_message
        backend.list_permissions = AsyncMock(return_value=[])

        with patch("asyncio.get_event_loop") as mock_loop, \
             patch.object(
                 CodingAgentExecutor, "_opencode_log_shows_quota_exhaustion", return_value=False
             ):
            fake_time = {"t": 0.0}

            class _FakeLoop:
                def time(self):
                    fake_time["t"] += 300.0
                    return fake_time["t"]

            mock_loop.return_value = _FakeLoop()
            result = await executor._send_with_permission_watch(backend, "sess1", "hi")

        assert result["status"] == "timeout"
        assert executor._model_override is None
