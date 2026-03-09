# Release Notes v1.1.7-beta

## Summary

This release improves the agentic scheduler workflow layer without changing the MCP surface area in a disruptive way.

The focus is:
- stronger output quality control
- more adaptive resource selection
- parallel discovery with human-in-the-loop review
- clearer Google Workspace onboarding
- a lightweight MCP smoke checklist for release validation

## Highlights

### 1. Agentic Quality Gates

Agentic tasks now validate final answers more strictly before marking a run successful.

Added support for:
- exact-text final answer requirements
- required content checks
- bounded output length checks
- correction loop when a final answer is structurally invalid

This makes the scheduler more reliable for contract-style tasks where output shape matters.

### 2. Dynamic Resource Policy Selection

Resource selection is now more adaptive during agentic runs.

The executor can choose tier preference based on:
- task complexity
- recent failures
- configured policy constraints

This reduces the need for static per-task tuning and prepares the system for richer policy-driven model orchestration.

### 3. Parallel Discovery Mode

Added explicit agentic execution modes:
- `normal`
- `deep_research`
- `parallel_discovery`

`parallel_discovery` fans a task out to multiple workers, preserves per-worker results, and aggregates them in a single parent task result.

### 4. Human-in-the-Loop Review Report

Parallel runs now produce a structured review report in `scheduler_get_task(...).result.metrics.review_report`.

Included fields:
- `summary`
- `recommendation_reason`
- `recommended_next_actions`
- `ranked_results`
- `decision_required`

This keeps MCP generic while making parallel results easier for clients and humans to interpret.

### 5. Google Workspace Setup Guidance

Installer and documentation now guide users through preparing Google Workspace integration before using:
- `google_service`
- scheduler tasks with `provider = "google_calendar"`

New setup guidance covers:
- `gcloud` authentication
- `gws` authentication
- verification steps

### 6. MCP Smoke Checklist

Added a lightweight live verification checklist for the current MCP release surface:
- resource pool status
- Google Calendar read/write
- agentic free-api path
- parallel discovery review path
- session output presence

This is intentionally a smoke checklist, not a full automated harness.

## Files Added

- `docs/releases/RELEASE_NOTES_v1.1.7-beta.md`
- `docs/guides/GOOGLE_WORKSPACE_SETUP.md`
- `docs/guides/MCP_SMOKE_CHECKLIST.md`

## Key Files Updated

- `app/scheduler/agentic_executor.py`
- `app/scheduler/executor.py`
- `app/scheduler/planning_prompt_manager.py`
- `app/installer/agents/env_configurator.py`
- `app/mcp/core/tools.py`
- `app/mcp/__init__.py`
- `app/scheduler/__init__.py`

## Validation Notes

Validated during this release cycle:
- free-api agentic execution with concrete OpenRouter free-model resolution
- parallel discovery aggregation and review report generation
- generic review summary fields through MCP
- Google Calendar scheduler integration
- Google Workspace onboarding documentation path

## Upgrade Notes

- Users who want Google Calendar integration should complete:
  - `docs/guides/GOOGLE_WORKSPACE_SETUP.md`
- Users validating this release should run:
  - `docs/guides/MCP_SMOKE_CHECKLIST.md`
