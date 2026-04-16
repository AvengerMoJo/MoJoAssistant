"""
UnifiedLLMClient — single entry point for all LLM HTTP calls in MoJoAssistant.

Key resolution order (env beats config, runtime override beats codebase):
  1. key_var / api_key_env environment variable
  2. Inline api_key in resource config (from merged config — runtime layer wins)
  3. resolve_llm_resource(resource_id) — searches both api_models and local_models
  4. {PROVIDER}_API_KEY / LMSTUDIO_API_KEY env fallbacks
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx


class UnifiedLLMClient:
    """Single class for all LLM HTTP calls in MoJoAssistant."""

    # ------------------------------------------------------------------ #
    # Config helpers                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def find_resource(cls, resource_id: str) -> Dict[str, Any]:
        """
        Find a resource entry in merged llm_config.json.
        Searches api_models (flat + nested sub-accounts) then local_models.
        Returns {} if not found.
        """
        from app.config.config_loader import load_layered_json_config
        cfg = load_layered_json_config("config/llm_config.json")

        # api_models — flat entries and nested sub-accounts
        for name, entry in cfg.get("api_models", {}).items():
            if not isinstance(entry, dict):
                continue
            if name == resource_id and entry.get("provider"):
                return dict(entry)
            if not entry.get("provider"):
                for sub_name, sub in entry.items():
                    if isinstance(sub, dict) and f"{name}_{sub_name}" == resource_id:
                        return dict(sub)

        # local_models — flat dict
        local = cfg.get("local_models", {})
        if resource_id in local and isinstance(local[resource_id], dict):
            entry = dict(local[resource_id])
            if "server_url" in entry and "base_url" not in entry:
                entry["base_url"] = entry["server_url"]
            return entry

        return {}

    @classmethod
    def resolve_key(
        cls,
        resource_id: str,
        entry: Dict[str, Any],
        env_override: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Resolve the API key for a resource.

        Priority:
          1. key_var / api_key_env → env_override then os.environ
          2. Inline api_key in entry (non-template)
          3. resolve_llm_resource(resource_id) from merged config
          4. LMSTUDIO_API_KEY (for lmstudio entries)
          5. {PROVIDER}_API_KEY env fallback
        """
        _env = env_override or {}

        # 1. key_var / api_key_env
        key_var = entry.get("key_var") or entry.get("api_key_env")
        if key_var:
            val = _env.get(key_var) or os.environ.get(key_var)
            if val:
                return val

        # 2. Inline api_key
        inline = entry.get("api_key", "")
        if inline and not str(inline).startswith("{{"):
            return inline

        # 3. Merged config lookup
        try:
            from app.config.config_loader import resolve_llm_resource
            cfg_key = resolve_llm_resource(resource_id).get("api_key")
            if cfg_key and not str(cfg_key).startswith("{{"):
                return cfg_key
        except Exception:
            pass

        # 4. Provider/lmstudio env fallbacks
        provider = entry.get("provider", "")
        candidates: List[str] = []
        if "lmstudio" in resource_id.lower():
            candidates += ["LMSTUDIO_API_KEY", "LM_STUDIO_API_KEY"]
        if provider:
            candidates.append(f"{provider.upper()}_API_KEY")
        for var in candidates:
            val = _env.get(var) or os.environ.get(var)
            if val:
                return val

        return None

    # ------------------------------------------------------------------ #
    # HTTP helpers                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_headers(resource_config: Dict[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        api_key = resource_config.get("api_key")
        message_format = resource_config.get("message_format", "openai")
        if message_format == "anthropic":
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = resource_config.get("anthropic_version", "2023-06-01")
        else:
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _build_payload(
        messages: List[Dict],
        model: str,
        output_limit: int,
        message_format: str,
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        if message_format == "anthropic":
            system = next((m["content"] for m in messages if m["role"] == "system"), None)
            user_messages = [m for m in messages if m["role"] != "system"]
            payload: Dict[str, Any] = {
                "model": model,
                "messages": user_messages,
                "max_tokens": min(2048, output_limit),
            }
            if system:
                payload["system"] = system
        else:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": min(4096, output_limit),
            }
            if tools:
                payload["tools"] = tools
                # Ask the model to issue one tool call per response.
                # Prevents runaway parallel-call batches (e.g. Gemma 4 issuing
                # 88 identical bash_exec calls in a single response).
                # Most OpenAI-compatible backends honour this; local servers
                # that ignore it are covered by the dedup in _execute_tool_calls.
                payload["parallel_tool_calls"] = False
        return payload

    @staticmethod
    def _extract_text(data: Dict, message_format: str) -> str:
        """Extract response text from API response dict."""
        try:
            if message_format == "anthropic":
                return data["content"][0]["text"].strip()
            msg = data["choices"][0]["message"]
            return (
                msg.get("content", "")
                or msg.get("reasoning_content", "")
                or ""
            )
        except (KeyError, IndexError, TypeError):
            return ""

    async def call_async(
        self,
        messages: List[Dict],
        resource_config: Dict[str, Any],
        model_override: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Async LLM call. Used by agentic_executor.
        Returns full response dict with _selected_model injected.
        """
        base_url = resource_config.get("base_url", "").rstrip("/")
        message_format = resource_config.get("message_format", "openai")
        output_limit = resource_config.get("output_limit", 8192)
        model = model_override or resource_config.get("model", "")

        headers = self._build_headers(resource_config)

        if message_format == "anthropic":
            url = f"{base_url}/messages"
        else:
            url = f"{base_url}/chat/completions"

        payload = self._build_payload(messages, model, output_limit, message_format, tools)

        # 300s read timeout: local LLMs (Qwen 35B, Gemma 27B) can take >120s
        # on a large context. Connect timeout stays short (10s) to fail fast if
        # the server is down. The task-level wall-clock cap (core.py) is the
        # ultimate safety net.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0)
        ) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        data["_selected_model"] = model
        return data

    async def call_stream_async(
        self,
        messages: List[Dict],
        resource_config: Dict[str, Any],
        model_override: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Async streaming LLM call. Yields text chunks as they arrive.

        Only supports text generation (no tool calls — use call_async for those).
        Uses OpenAI-compatible SSE format: data: {...}\n\n lines.
        Yields decoded content strings only; caller receives plain text chunks.
        """
        base_url = resource_config.get("base_url", "").rstrip("/")
        message_format = resource_config.get("message_format", "openai")
        output_limit = resource_config.get("output_limit", 8192)
        model = model_override or resource_config.get("model", "")
        headers = self._build_headers(resource_config)

        payload = self._build_payload(messages, model, output_limit, message_format, tools=None)
        payload["stream"] = True

        if message_format == "anthropic":
            url = f"{base_url}/messages"
        else:
            url = f"{base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except Exception:
                        continue

                    if message_format == "anthropic":
                        # Anthropic stream: content_block_delta events
                        delta = chunk.get("delta", {})
                        text = delta.get("text", "")
                    else:
                        # OpenAI stream: choices[0].delta.content
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        text = delta.get("content") or ""

                    if text:
                        yield text

    def call_sync(
        self,
        messages: List[Dict],
        resource_config: Dict[str, Any],
        model_override: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Sync LLM call. Used by api_llm_interface.
        Returns full response dict.
        """
        import requests as req

        base_url = resource_config.get("base_url", "").rstrip("/")
        message_format = resource_config.get("message_format", "openai")
        output_limit = resource_config.get("output_limit", 8192)
        model = model_override or resource_config.get("model", "")

        headers = self._build_headers(resource_config)

        if message_format == "anthropic":
            url = f"{base_url}/messages"
        else:
            url = f"{base_url}/chat/completions"

        payload = self._build_payload(messages, model, output_limit, message_format, tools)

        timeout = resource_config.get("timeout", 300)
        response = req.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
