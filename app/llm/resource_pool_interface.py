"""
ResourcePoolLLMInterface — dreaming pipeline LLM adapter backed by ResourceManager.

Implements the duck-typed generate_response(query, context) interface expected
by DreamingPipeline (chunker + synthesizer) using the same ResourceManager +
UnifiedLLMClient stack that AgenticExecutor uses for agentic tasks.

This replaces LLMInterface(config_file="config/llm_config.json") in
TaskExecutor._get_dreaming_pipeline(), eliminating the split-brain risk where
the dreaming LLM could silently use a stale model from llm_config.json after
resource_pool.json has been updated.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.scheduler.resource_pool import ResourceManager

logger = logging.getLogger(__name__)


class DreamingLLMError(RuntimeError):
    """An LLM call made for the dreaming pipeline failed or returned nothing usable.

    generate_response() used to log such failures and return "" -- which the pipeline cannot
    tell from an empty answer, so a run with no working LLM archived empty results and
    reported success (2026-10-08: global dreaming "completed" for a week with no new archive).
    """


class ResourcePoolLLMInterface:
    """
    LLM interface for the dreaming pipeline backed by ResourceManager.

    Usage:
        rm = ResourceManager()
        llm = ResourcePoolLLMInterface(rm)
        pipeline = DreamingPipeline(llm_interface=llm, quality_level="basic")
    """

    def __init__(
        self,
        resource_manager: "ResourceManager",
        tier_preference: Optional[List] = None,
        max_tokens: int = 16000,
        timeout_seconds: float = 900.0,
    ) -> None:
        """
        Args:
            resource_manager: Shared ResourceManager instance to acquire LLM resources from.
            tier_preference: Ordered list of ResourceTier values; None uses ResourceManager default.
            max_tokens: Hard cap on output tokens per call.
        """
        self._rm = resource_manager
        self._tier_preference = tier_preference  # None = ResourceManager default
        self._max_tokens = max_tokens
        # Per-call wait. A nightly run sends ~200 messages in one prompt to a local 35B model; the old
        # fixed 120s cut every call off (2026-10-09: first honest failure of the nightly job).
        self._timeout = timeout_seconds

    def generate_response(self, query: str, context: Optional[str] = None) -> str:
        """
        Synchronous wrapper around async _generate so the dreaming pipeline
        (which calls us synchronously) works without modification.
        """
        try:
            try:
                asyncio.get_running_loop()
                in_async_context = True
            except RuntimeError:
                in_async_context = False
            if in_async_context:
                # We're inside a running loop -- run in a worker thread with its own loop so this
                # call can wait for the answer without deadlocking that loop.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._generate(query))
                    return future.result(timeout=self._timeout)
            return asyncio.run(self._generate(query))
        except DreamingLLMError:
            raise
        except (TimeoutError, RuntimeError, OSError) as e:
            logger.error(f"ResourcePoolLLMInterface.generate_response failed: {e}")
            raise DreamingLLMError(f"LLM call failed after waiting up to {self._timeout:g}s: {type(e).__name__}: {e}") from e

    async def _generate(self, query: str) -> str:
        from app.llm.unified_client import UnifiedLLMClient
        from app.scheduler.resource_pool import ResourceTier

        # Acquire a suitable resource
        if self._tier_preference:
            from app.scheduler.resource_pool import ResourceTier as RT
            tiers = [RT(t) if isinstance(t, str) else t for t in self._tier_preference]
            resource = self._rm.acquire(tier_preference=tiers)
        else:
            resource = self._rm.acquire()

        if resource is None:
            raise DreamingLLMError("no LLM resource available for dreaming")

        config_max_tokens = min(resource.output_limit or self._max_tokens, self._max_tokens)
        resource_config = {
            "base_url": resource.base_url,
            "model": resource.model,
            "api_key": resource.api_key,
            "output_limit": config_max_tokens,
            "message_format": "openai",
            "provider": resource.provider,
            "timeout": self._timeout,
        }
        client = UnifiedLLMClient()
        messages = [{"role": "user", "content": query}]
        try:
            data = await client.call_async(
                messages=messages,
                resource_config=resource_config,
                model_override=resource.model,
            )
        except (TimeoutError, ConnectionError, OSError) as e:
            self._rm.record_usage(resource.id, success=False, error_message=str(e))
            logger.error(f"ResourcePoolLLMInterface._generate failed: {e}")
            raise DreamingLLMError(f"{resource.id}: {type(e).__name__}: {e}") from e

        self._rm.record_usage(resource.id, success=True)
        choices = data.get("choices", [])
        content = (choices[0].get("message", {}).get("content", "") or "") if choices else ""
        finish = choices[0].get("finish_reason") if choices else None
        if not content.strip():
            usage = data.get("usage") or {}
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            why = (f"finish_reason={finish}, {usage.get('completion_tokens')} completion tokens "
                   f"({reasoning} spent on reasoning) against a {config_max_tokens}-token output budget")
            hint = (" -- a thinking model used its whole output budget on reasoning; raise dreaming.max_output_tokens "
                    "or use a non-thinking resource") if finish == "length" else ""
            raise DreamingLLMError(f"{resource.id} returned an empty completion ({why}){hint}")
        if finish == "length":
            logger.warning(f"ResourcePoolLLMInterface: {resource.id} hit its output limit; the reply may be truncated")
        return content
