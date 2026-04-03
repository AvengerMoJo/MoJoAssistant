"""
Smoke — role_chat.py bug-fix regression tests (v1.2.9)

Covers two fixes:
  1. Streaming path quality gate: _ensure_response_quality() is applied after
     the streaming loop, so hollow/empty responses cannot leak through to the
     dashboard surface or be saved to history.

  2. Malformed tool-call JSON in both streaming and non-streaming paths: a
     parse failure injects a tool error result back into the conversation
     instead of silently executing the tool with empty arguments.

No network or LLM calls required — all LLM interactions are stubbed.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_stub_resource():
    """Minimal LLMResource pointing at a non-existent local endpoint."""
    from app.scheduler.resource_pool import LLMResource, ResourceTier
    return LLMResource(
        id="stub-chat",
        type="local",
        provider="openai",
        base_url="http://127.0.0.1:9999/v1",
        model="stub-model",
        tier=ResourceTier.FREE,
        enabled=True,
        api_key=None,
    )


def _make_resource_manager(resource):
    """ResourceManager with a single injected stub resource."""
    from app.scheduler.resource_pool import ResourceManager, UsageRecord
    rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
    rm._resources[resource.id] = resource
    rm._usage[resource.id] = UsageRecord()
    return rm


def _llm_response(content: str, tool_calls=None) -> dict:
    """Build an OpenAI-format completions response."""
    msg: dict = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return {
        "choices": [{"message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def _fake_role():
    return {
        "id": "smoke_role",
        "name": "SmokeRole",
        "system_prompt": "You are SmokeRole.",
        "tool_access": [],
    }


# ---------------------------------------------------------------------------
# Issue 1 — Streaming path must apply _ensure_response_quality()
# ---------------------------------------------------------------------------

class TestStreamingQualityGate:

    @pytest.mark.asyncio
    async def test_hollow_response_replaced_in_stream(self, isolated_memory_path):
        """
        When the final streamed text is a hollow placeholder phrase,
        exchange_stream() must emit a corrective token chunk and save the
        quality-checked text rather than the hollow output.
        """
        from app.scheduler.role_chat import RoleChatSession, _ensure_response_quality

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)
        session = RoleChatSession("smoke_role")

        hollow = "Let me search for that."
        expected_quality = _ensure_response_quality(hollow, "SmokeRole")
        assert expected_quality != hollow, "pre-condition: quality check must reject hollow phrase"

        with patch("app.roles.role_manager.RoleManager.get", return_value=_fake_role()), \
             patch.object(
                 session, "_call_raw",
                 new_callable=AsyncMock,
                 return_value=_llm_response(hollow),
             ), \
             patch.object(session, "_save_session") as mock_save:

            chunks = []
            async for line in session.exchange_stream("hello", resource_manager=rm):
                chunks.append(line)

        # At least one chunk should contain the quality-checked text
        all_text = "\n".join(chunks)
        assert "What I found" in all_text, (
            "Hollow streaming response was not replaced by quality gate"
        )

        # The text saved to history must be the corrected version
        assert mock_save.called
        saved_response = mock_save.call_args[0][2]  # _save_session(session, message, response)
        assert "What I found" in saved_response, (
            "Hollow text was persisted to history instead of the corrected fallback"
        )

    @pytest.mark.asyncio
    async def test_empty_response_replaced_in_stream(self, isolated_memory_path):
        """
        An empty streamed response (e.g. model returns empty content) is caught
        by the quality gate and replaced with the structured fallback.
        """
        from app.scheduler.role_chat import RoleChatSession

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)
        session = RoleChatSession("smoke_role")

        with patch("app.roles.role_manager.RoleManager.get", return_value=_fake_role()), \
             patch.object(
                 session, "_call_raw",
                 new_callable=AsyncMock,
                 return_value=_llm_response(""),
             ), \
             patch.object(session, "_save_session") as mock_save:

            chunks = []
            async for line in session.exchange_stream("hello", resource_manager=rm):
                chunks.append(line)

        all_text = "\n".join(chunks)
        assert "What I found" in all_text, (
            "Empty streaming response was not replaced by quality gate"
        )
        saved_response = mock_save.call_args[0][2]
        assert "What I found" in saved_response

    @pytest.mark.asyncio
    async def test_good_response_passes_through_unchanged(self, isolated_memory_path):
        """
        A substantive response must pass through the streaming quality gate
        untouched — no duplicate corrective token should be emitted.
        """
        from app.scheduler.role_chat import RoleChatSession

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)
        session = RoleChatSession("smoke_role")

        good = "The NineChapter system scores SmokeRole at 95 overall."

        with patch("app.roles.role_manager.RoleManager.get", return_value=_fake_role()), \
             patch.object(
                 session, "_call_raw",
                 new_callable=AsyncMock,
                 return_value=_llm_response(good),
             ), \
             patch.object(session, "_save_session") as mock_save:

            chunks = []
            async for line in session.exchange_stream("hello", resource_manager=rm):
                chunks.append(line)

        # Quality gate must NOT have fired — no "What I found" fallback text
        token_chunks = [c for c in chunks if '"type": "token"' in c]
        token_text = "".join(
            json.loads(c[len("data: "):])["text"]
            for c in token_chunks
            if c.startswith("data: ")
        )
        assert "What I found" not in token_text
        assert good[:20] in token_text


# ---------------------------------------------------------------------------
# Issue 2 — Malformed tool-call JSON injects error, does not fall back to {}
# ---------------------------------------------------------------------------

class TestMalformedToolArgsStreaming:

    def _make_tool_call_response(self, tool_name: str, bad_args: str) -> dict:
        """LLM response with a single tool call containing malformed JSON args."""
        tc = {
            "id": "tc-smoke-1",
            "type": "function",
            "function": {"name": tool_name, "arguments": bad_args},
        }
        return _llm_response("", tool_calls=[tc])

    @pytest.mark.asyncio
    async def test_streaming_bad_json_args_injects_tool_error(self, isolated_memory_path):
        """
        When the model emits a tool call with unparseable JSON arguments in the
        streaming path, a tool error result must be injected into the message
        list — _execute_tool must NOT be called with empty args.
        """
        from app.scheduler.role_chat import RoleChatSession

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)

        role_with_tools = {**_fake_role(), "tool_access": ["memory"]}
        session = RoleChatSession("smoke_role")

        bad_args = "{not valid json at all"
        tool_response = self._make_tool_call_response("memory_search", bad_args)
        # Second call: model provides a clean text response after receiving the error
        text_response = _llm_response("Here is what I found after the error correction.")

        call_sequence = [tool_response, text_response]
        call_index = 0

        async def _fake_call_raw(messages, rm, tools=None):
            nonlocal call_index
            resp = call_sequence[min(call_index, len(call_sequence) - 1)]
            call_index += 1
            return resp

        execute_tool_calls = []

        async def _fake_execute_tool(tool_name, args):
            execute_tool_calls.append((tool_name, args))
            return json.dumps({"success": True, "results": []})

        with patch("app.roles.role_manager.RoleManager.get", return_value=role_with_tools), \
             patch.object(session, "_call_raw", side_effect=_fake_call_raw), \
             patch.object(session, "_execute_tool", side_effect=_fake_execute_tool), \
             patch.object(session, "_save_session"):

            chunks = []
            async for line in session.exchange_stream("search something", resource_manager=rm):
                chunks.append(line)

        # _execute_tool must not have been called for the bad-args tool call
        assert execute_tool_calls == [], (
            "_execute_tool was called despite malformed tool arguments; "
            f"called with: {execute_tool_calls}"
        )

        # The error must have been injected as a tool result message.
        # Verify by checking the second _call_raw received a tool error in messages.
        # (Indirect check: conversation continued and produced a done event.)
        done_events = [c for c in chunks if '"type": "done"' in c]
        assert len(done_events) == 1, "exchange_stream did not terminate with a done event"

    @pytest.mark.asyncio
    async def test_streaming_bad_json_error_message_mentions_retry(self, isolated_memory_path):
        """
        The injected tool error message must tell the model what went wrong and
        ask it to retry with valid JSON.
        """
        from app.scheduler.role_chat import RoleChatSession

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)

        role_with_tools = {**_fake_role(), "tool_access": ["memory"]}
        session = RoleChatSession("smoke_role")

        bad_args = "{broken"
        tool_response = self._make_tool_call_response("memory_search", bad_args)
        text_response = _llm_response("Understood, retrying.")

        call_index = 0

        async def _fake_call_raw(messages, rm, tools=None):
            nonlocal call_index
            resp = [tool_response, text_response][min(call_index, 1)]
            call_index += 1
            return resp

        injected_messages = []

        original_append = list.append

        with patch("app.roles.role_manager.RoleManager.get", return_value=role_with_tools), \
             patch.object(session, "_call_raw", side_effect=_fake_call_raw), \
             patch.object(session, "_execute_tool", new_callable=AsyncMock), \
             patch.object(session, "_save_session"):

            # Capture the messages list by intercepting the second _call_raw call
            captured_messages = None

            async def _capturing_call_raw(messages, rm, tools=None):
                nonlocal call_index, captured_messages
                resp = [tool_response, text_response][min(call_index, 1)]
                if call_index == 1:
                    captured_messages = list(messages)
                call_index += 1
                return resp

            session._call_raw = _capturing_call_raw  # type: ignore[method-assign]

            async for _ in session.exchange_stream("find something", resource_manager=rm):
                pass

        assert captured_messages is not None, "Second LLM call was never made"
        # Find the injected tool result
        tool_results = [m for m in captured_messages if m.get("role") == "tool"]
        assert tool_results, "No tool result message was injected into the conversation"
        content = json.loads(tool_results[-1]["content"])
        assert content["success"] is False
        assert "could not be parsed as JSON" in content["error"]
        assert "retry" in content["error"].lower()


class TestMalformedToolArgsNonStreaming:

    def _make_tool_call_response(self, tool_name: str, bad_args: str) -> dict:
        tc = {
            "id": "tc-smoke-ns-1",
            "type": "function",
            "function": {"name": tool_name, "arguments": bad_args},
        }
        return _llm_response("", tool_calls=[tc])

    @pytest.mark.asyncio
    async def test_non_streaming_bad_json_args_injects_tool_error(self, isolated_memory_path):
        """
        Same malformed-args fix applies to the non-streaming exchange() path:
        _execute_tool must not be called when argument parsing fails.
        """
        from app.scheduler.role_chat import RoleChatSession

        stub_resource = _make_stub_resource()
        rm = _make_resource_manager(stub_resource)

        role_with_tools = {**_fake_role(), "tool_access": ["memory"]}
        session = RoleChatSession("smoke_role")

        bad_args = "not json"
        tool_response = self._make_tool_call_response("memory_search", bad_args)
        text_response = _llm_response("Here is the answer after error feedback.")

        call_index = 0

        async def _fake_call_raw(messages, rm, tools=None):
            nonlocal call_index
            resp = [tool_response, text_response][min(call_index, 1)]
            call_index += 1
            return resp

        execute_tool_calls = []

        async def _fake_execute_tool(tool_name, args):
            execute_tool_calls.append((tool_name, args))
            return json.dumps({"success": True, "results": []})

        with patch("app.roles.role_manager.RoleManager.get", return_value=role_with_tools), \
             patch.object(session, "_call_raw", side_effect=_fake_call_raw), \
             patch.object(session, "_execute_tool", side_effect=_fake_execute_tool), \
             patch.object(session, "_save_session"):

            result = await session.exchange("find something", resource_manager=rm)

        assert execute_tool_calls == [], (
            "_execute_tool was called despite malformed tool arguments (non-streaming path); "
            f"called with: {execute_tool_calls}"
        )
        assert "response" in result
