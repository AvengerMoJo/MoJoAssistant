# Spec: HITL Adapter Reliability Fix

## Problem

The new HITL adapter layer has two correctness gaps:

1. Runtime notifications are sent through fresh `HITLManager` instances created on demand.
   Those managers load new adapter objects from config, but they do not reuse the
   already-started adapter registered by `DiscordHITLAdapter.start()`. The fresh
   instances never receive `set_client()` or the gateway registration, so Discord
   HITL delivery can silently fail.

2. Discord catch-up restores waiting tasks using `pending_choices`, but the coding
   session handler stores the options under `pending_options`. After a Discord bot
   restart, waiting HITL messages can repost without buttons.

These are production-facing bugs because they affect the main owner feedback loop:

- tasks can pause for input but never reach the owner channel
- tasks that were already waiting can lose their choice buttons after restart

## Desired Outcome

We want HITL delivery to be:

- reliable: one live adapter instance per configured transport
- restart-safe: waiting tasks are restored with their original choices
- explicit: the code should distinguish adapter construction from adapter runtime state
- testable: both dispatch and catch-up paths should have targeted coverage

## Non-Goals

- Redesign the overall HITL protocol
- Add new transports in this change
- Change task semantics outside HITL notification delivery and restoration

## Root Cause

### 1. Fresh managers do not own the live adapter

`HITLManager.load_from_config()` builds a new manager and new adapter objects every
call. That is fine for static metadata, but it breaks transports that maintain live
state:

- Discord client binding
- owner channel binding
- pending-message tracking
- button view callbacks

`DiscordHITLAdapter` only becomes live after `start()` calls
`register_hitl_adapter(self)`. The on-demand helper path does not call `start()` on
that loaded instance, so it never receives the Discord client.

### 2. The pending choice key is inconsistent

The coding session handler stores question options under `pending_options`:

- `task.config["pending_options"] = options`

The Discord catch-up path reads `pending_choices`:

- `choices = task.config.get("pending_choices") or []`

That mismatch means restored tasks lose their buttons even when the original task
had valid reply choices.

## Proposal

### A. Introduce a shared live HITL manager

Create a single runtime HITL manager that is initialized once during app startup
and reused by notification helpers.

Proposed behavior:

1. The HTTP startup path loads HITL adapters once.
2. The manager starts them once and keeps the live instances around.
3. Notification helpers reuse the live manager instead of calling
   `HITLManager.load_from_config()` on every event.
4. Shutdown stops the shared manager once.

Implementation options:

- store the active manager on the application / service object
- provide a module-level accessor with lazy initialization
- inject the manager through the scheduler or executor context

Preferred option:

- app startup owns a single manager instance and passes it into the places that
  emit HITL notifications

This preserves the config-driven model while ensuring adapters have live state.

### B. Normalize pending choice storage

Make the handler and the Discord catch-up code use the same key.

Recommended approach:

- standardize on `pending_options`
- read both keys during a migration window:
  - first `pending_options`
  - fallback to `pending_choices` for backward compatibility
- update catch-up code to use the normalized key

### C. Add explicit adapter-state boundaries

Document and enforce the difference between:

- adapter config loaded from disk
- live runtime adapter instance bound to a transport

This should be reflected in the manager and adapter docstrings so future code does
not repeat the same mistake.

## Implementation Plan

### Step 1 — Add a shared manager path

- Add a runtime manager holder in the startup path.
- Wire `coding_session_opencode._push_hitl_notification()` and
  `_push_completion_notification()` to use the shared live manager.
- Wire `bonsai._send_hitl()` to use the same shared manager.

### Step 2 — Preserve live Discord adapter state

- Ensure `DiscordHITLAdapter.start()` is called exactly once per process.
- Ensure `stop()` unregisters only the shared live adapter instance.
- Keep `on_ready_hook()` attached to the live instance.

### Step 3 — Fix choice key mismatch

- Update catch-up logic to prefer `pending_options`.
- Keep `pending_choices` as a fallback while old tasks may still exist.
- Optionally write both keys during the transition if that simplifies rollback.

### Step 4 — Add tests

Add coverage for:

- notification helper reuses the shared HITL manager
- Discord adapter receives a live client before `send_hitl()` is called
- catch-up repopulates HITL buttons from `pending_options`
- backward compatibility with `pending_choices`

## Acceptance Criteria

- A task that pauses for HITL reaches Discord through the live adapter instance.
- A restarted bot reposts waiting tasks with the original reply buttons intact.
- The coding session and Bonsai notification paths use the same live manager.
- Tests fail before the fix and pass after the fix.

## Suggested Tests

### Unit

- `test_hitl_manager_shared_instance_is_reused`
- `test_discord_hitl_send_requires_started_adapter_state`
- `test_discord_catchup_prefers_pending_options`
- `test_discord_catchup_falls_back_to_pending_choices`
- `test_coding_session_push_hitl_uses_shared_manager`
- `test_bonsai_push_hitl_uses_shared_manager`

### Regression

- Start Discord HITL, send a task, restart the bot, confirm the task reposts with buttons.
- Trigger a coding-session permission pause, confirm the owner channel receives the HITL.

## Migration Notes

This change should be backward-compatible for in-flight tasks.

- old tasks that only have `pending_choices` should still repost correctly
- new tasks should write the normalized key
- if a singleton/shared manager is introduced, the startup/shutdown sequence should
  remain idempotent

## Open Questions

- Should the shared HITL manager live on the app object, scheduler, or a dedicated
  lifecycle service?
- Should `pending_choices` be retained indefinitely or removed after one release
  cycle?
- Should the Discord adapter be the only stateful transport, or should the manager
  abstraction support more live transports in the future?
