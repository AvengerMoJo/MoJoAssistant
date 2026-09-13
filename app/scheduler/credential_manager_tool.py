"""
Agent-facing tool: call_llm_via_route.

Proxies an LLM chat-completion call through a route registered on the
standalone ai-credential-manager service. The agent supplies route_id +
messages; MoJoAssistant resolves the credential internally via
credential_manager_client and makes the actual HTTP call itself. The raw
API key is never returned to the caller, never appears in the tool result,
and therefore never lands in agent-visible conversation context or logs --
this is the deliberate design choice made 2026-08-01: resource_pool.py's
existing acquire() already keeps .api_key internal to the scheduler, never
exposed to any agent; this tool preserves that same boundary for the
service-backed path instead of introducing a new leak surface.

Registered as a CapabilityDefinition in config/dynamic_tools.json (category
"credential", executor {"type": "python", "module": ...}). Gated the same
way every other MoJoAssistant tool is: a role can only call it if
"call_llm_via_route" is in that role's available_tools list (enforced by
CapabilityRegistry.execute_tool()'s allowlist check) -- no new
per-role-route authorization layer, per the tool-level-gate decision.

No fallback pattern: any failure (unreachable credential service, no grant
for the requested route, the LLM call itself failing) is returned as
{"success": False, "error": ...} for the calling agent to see and react
to -- never silently retried or substituted.
"""
from typing import Any, Dict, List, Optional

import httpx


def _redact_key_fragments(text: str, api_key: str, min_fragment_length: int = 6) -> str:
    """Strip any prefix of api_key (length >= min_fragment_length) out of
    text before it's shown to an agent.

    Found live 2026-08-01: LMStudio's own 401 error body echoed back a
    partial prefix of the key it rejected ("0uQer5WlAb**********") -- the
    provider's own diagnostic text, not something this code constructed,
    but forwarding it verbatim to the agent-visible tool result would still
    leak real key material. Checking every prefix length (not just the
    full key) is what catches a provider's own truncated/masked echo, not
    just an exact match.
    """
    if not text or not api_key:
        return text
    redacted = text
    for length in range(len(api_key), min_fragment_length - 1, -1):
        fragment = api_key[:length]
        if fragment and fragment in redacted:
            redacted = redacted.replace(fragment, "[REDACTED]")
    return redacted


async def run(args: Dict[str, Any]) -> Dict[str, Any]:
    route_id = args.get("route_id")
    messages = args.get("messages")
    max_tokens = args.get("max_tokens", 1024)
    temperature = args.get("temperature", 0.7)

    if not route_id:
        return {"success": False, "error": "route_id is required"}
    if not messages or not isinstance(messages, list):
        return {"success": False, "error": "messages (list of {role, content}) is required"}

    from app.scheduler.credential_manager_client import (
        get_credential_manager_client,
        CredentialManagerError,
    )
    client = get_credential_manager_client()

    try:
        resolved = await client.aresolve_credential(route_id)
    except CredentialManagerError as e:
        return {"success": False, "error": f"could not resolve route '{route_id}': {e}"}

    api_key = resolved["api_key"]
    base_url = resolved["base_url"].rstrip("/")
    model = resolved["model"]

    success = False
    error_message: Optional[str] = None
    completion_text = ""
    usage: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=60.0) as http_client:
            resp = await http_client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
        if resp.status_code == 200:
            body = resp.json()
            completion_text = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            success = True
        else:
            error_message = f"HTTP {resp.status_code}: {resp.text[:500]}"
    except Exception as e:
        error_message = str(e)

    try:
        # Full, unredacted error goes to the service's own usage log --
        # that's an internal record, not agent-visible, so no need to
        # weaken the diagnostic value of what gets stored there.
        await client.areport_usage(route_id, success=success, error_message=error_message)
    except CredentialManagerError:
        pass  # usage reporting is best-effort -- must not mask the real call result

    if not success:
        return {"success": False, "error": _redact_key_fragments(error_message or "", api_key)}

    return {
        "success": True,
        "route_id": route_id,
        "model": model,
        "completion": completion_text,
        "usage": usage,
    }
