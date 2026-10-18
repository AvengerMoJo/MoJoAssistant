"""Resource-pool upkeep jobs. config.job selects the job; today: openrouter_free_models."""
# [mojo-integration]
from __future__ import annotations

from pathlib import Path

from app.config.paths import get_memory_subpath
from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult

TOOL_PROBE = [{
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Return the given text.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
}]


class ResourceMaintenanceHandler(TaskHandler):
    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        job = (task.config or {}).get("job")
        if job != "openrouter_free_models":
            return TaskResult(success=False, error_message=f"unknown resource_maintenance job: {job!r}")
        try:
            summary = await self._refresh_openrouter_free(ctx)
        except Exception as e:
            ctx.log(f"openrouter free-model refresh failed: {e}", "error")
            return TaskResult(success=False, error_message=f"openrouter free-model refresh failed: {e}")
        ctx.log(
            f"openrouter free-model refresh: {len(summary['checked'])} checked, added {summary['added']}, "
            f"disabled {list(summary['disabled'])}, enabled {summary['enabled']}"
        )
        return TaskResult(success=True, metrics=summary)

    async def _refresh_openrouter_free(self, ctx: ExecutorContext) -> dict:
        import httpx
        from app.llm.unified_client import UnifiedLLMClient
        from app.scheduler import free_model_refresh as fmr
        from app.scheduler.account_expansion import expand_provider_accounts

        rm = ctx.get_resource_manager()
        probe = next((r for r in rm._resources.values()
                      if r.id.startswith(f"{fmr.GROUP}_") and r.enabled and r.api_key), None)
        if probe is None:
            raise fmr.RefreshError("no enabled openrouter_free account with a key to verify models with")

        async def fetch_catalog():
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(fmr.CATALOG_URL)
                resp.raise_for_status()
                return resp.json()

        async def verify(model: str) -> bool:
            cfg = {"base_url": probe.base_url, "model": model, "api_key": probe.api_key, "output_limit": 100,
                   "message_format": "openai", "provider": probe.provider, "timeout": 90}
            data = await UnifiedLLMClient().call_async(
                messages=[{"role": "user", "content": "Call the echo tool with the text 'ok'."}],
                resource_config=cfg, model_override=model, tools=TOOL_PROBE,
            )
            choices = data.get("choices") or []
            return bool(choices and (choices[0].get("message") or {}).get("tool_calls"))

        config_path = Path(get_memory_subpath("config", "resource_pool.json"))
        summary = await fmr.run_refresh(
            config_path=config_path,
            state_path=Path(get_memory_subpath("state", "openrouter_free_refresh.json")),
            fetch_catalog=fetch_catalog,
            verify=verify,
            expand=expand_provider_accounts,
        )
        if summary["config_written"]:
            rm.reload_config()
        return summary
