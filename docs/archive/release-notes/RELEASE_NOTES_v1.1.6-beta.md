# MoJoAssistant v1.1.6-beta Release Notes

Release date: 2026-03-08

## Highlights

This release hardens the agentic scheduler stack for real runtime operations:
- Google Calendar scheduler integration validated end-to-end.
- OpenRouter multi-account free-tier routing validated across accounts.
- Dynamic free-model discovery via OpenRouter `/models` added to agentic execution.
- Resource pool now hot-reloads config/env changes across clients.
- Agentic runtime config paths unified to avoid split-brain updates.
- Local LLM startup changed to lazy initialization to avoid blocking scheduler init.

## Key Changes

### Scheduler + Resource Pool
- Added OpenRouter multi-account resources in `config/resource_pool_config.json` and validated free-api routing/failover behavior.
- Fixed resource naming/typo issues (`openrouter_elmntri`) and removed invalid null resource entries.
- Added hot-reload behavior in `app/scheduler/resource_pool.py`:
  - Detects changes in `config/resource_pool_config.json` and `~/.memory/resource_pool.env`.
  - Reloads runtime state automatically on status/acquire paths.

### Agentic Executor
- Added OpenRouter model discovery and cache in `app/scheduler/agentic_executor.py`:
  - Calls `GET /models` for `openrouter/auto` resources.
  - Selects free model IDs (prefers `*:free`, falls back to zero-priced models).
  - Caches selected model per resource.
  - Records resolved model in iteration logs.

### Calendar Integration
- Generic `google_service` MCP call support integrated and used for scheduler calendar path.
- Google Calendar scheduled task path (`provider=google_calendar`) verified with real event creation and `html_link` return.
- Added policy and guide for user-vs-ops calendar ownership:
  - `config/google_calendar_scheduler_policy.json`
  - `docs/guides/GOOGLE_CALENDAR_SCHEDULER_POLICY.md`

### Config UX and Templates
- Unified MCP writable modules with runtime-loaded files:
  - `agentic_tools` -> `config/dynamic_tools.json`
  - `agentic_prompts` -> `config/planning_prompts.json`
- Added template seeding support from:
  - `config/examples/dynamic_tools.example.json`
  - `config/examples/planning_prompts.example.json`
- Added onboarding guide:
  - `docs/guides/RESOURCE_POOL_ACCOUNT_ONBOARDING.md`
- Ignored runtime mutable files by default:
  - `config/dynamic_tools.json`
  - `config/planning_prompts.json`
  - `config/tool_operation_logs.json`

### Safety/Policy Fixes
- Fixed sandbox path expansion for `~` in `app/scheduler/safety_policy.py`.

### Local LLM Startup
- Refactored `app/llm/local_llm_interface.py` to lazy server startup/readiness check to avoid blocking scheduler initialization.

## Validation Summary

- Resource pool status and scheduler daemon health verified via MCP.
- Google Calendar scheduled task created successfully with real `event_id` and `html_link`.
- Per-account OpenRouter free-api smoke tests succeeded for:
  - `openrouter_avengermojo`
  - `openrouter_elmntri`
  - `openrouter_tinyi`
  - `openrouter_yiai`
- Resolved free model observed in live runs:
  - `arcee-ai/trinity-large-preview:free`

## Version

- `app/mcp/__init__.py`: `1.1.6-beta`
- `app/scheduler/__init__.py`: `1.1.6-beta`
