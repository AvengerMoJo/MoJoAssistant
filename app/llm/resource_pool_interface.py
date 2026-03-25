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
        max_tokens: int = 4096,
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

    def generate_response(self, query: str, context: Optional[str] = None) -> str:
        """
        Synchronous wrapper around async _generate so the dreaming pipeline
        (which calls us synchronously) works without modification.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context — run in a thread to avoid
                # blocking the event loop.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._generate(query))
                    return future.result(timeout=120)
            else:
                return loop.run_until_complete(self._generate(query))
        except (TimeoutError, RuntimeError, OSError) as e:
            logger.error(f"ResourcePoolLLMInterface.generate_response failed: {e}")
            return ""

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
            logger.warning("ResourcePoolLLMInterface: no resource available")
            return ""

        resource_config = {
            "base_url": resource.base_url,
            "model": resource.model,
            "api_key": resource.api_key,
            "output_limit": min(resource.output_limit or 4096, self._max_tokens),
            "message_format": "openai",
            "provider": resource.provider,
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
            self._rm.record_usage(resource.id, success=False)
            logger.error(f"ResourcePoolLLMInterface._generate failed: {e}")
            return ""

        self._rm.record_usage(resource.id, success=True)
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""
