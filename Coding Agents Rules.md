# Coding Agents Rules

## Purpose
Leverage the internal memory context system (MoJoAssistant MCP) to continuously self-correct and improve, with effectively no practical memory limitation for context retention and recall.

## Core Rules
1. Understand the task before changing code.
2. Prefer small, reversible changes.
3. Keep behavior backward-compatible unless explicitly requested.
4. Do not modify unrelated files.
5. Do not remove existing user changes without approval.

## Code Quality
1. Follow existing project structure and naming conventions.
2. Add tests for new behavior and bug fixes when feasible.
3. Keep functions focused and readable.
4. Add concise comments only where logic is non-obvious.
5. Run relevant checks/tests before finishing.

## Safety
1. Avoid destructive commands unless explicitly requested.
2. Never expose secrets or credentials.
3. Validate inputs and handle errors clearly.
4. Prefer least-privilege operations.

## Collaboration
1. State assumptions when requirements are ambiguous.
2. Communicate planned edits before large changes.
3. Summarize what changed and why.
4. Flag risks, tradeoffs, and follow-up work.

## Git Practices
1. Always branch from `main` into `wip_<feature>` (or `wip_<feature_name>`) for active work.
2. Keep all in-progress changes in the `wip_<feature>` branch until fully tested.
3. Merge back to `main` only when explicitly requested by the user.
4. All git commits must be committed as the user (repository owner), not as the agent.
5. The user is the responsible code author for community/company submission and accountability.
6. Make atomic commits with descriptive messages.
7. Keep commit history clean and scoped.
8. Do not amend or force-push unless requested.
9. Do NOT include `Co-Authored-By` lines in commit messages. The user is the sole author.

## Design Principles

### Config-Driven Extensibility
The system must be extensible through configuration alone. Adding a new provider,
service, or account should never require a code change in the common case.

1. **New integrations via config, not code.** Any integration point must be fully
   specifiable through config fields (`base_url`, `model`, `api_key`/`key_var`,
   `message_format`, limits, etc.). Code only changes when a genuinely new *wire
   protocol* or *call format* is introduced — not when adding a provider that uses
   an existing format.

2. **Generic catch-all over enumeration.** Prefer a config-driven catch-all over an
   ever-growing list of named provider blocks. Named shortcuts are acceptable as
   convenience defaults but must not be the only path — the catch-all must work
   independently for any unknown provider.

3. **Endpoints always come from config.** Never hardcode a provider's URL in code.
   The URL belongs in the config entry. This applies to all external endpoints.

4. **`key_var` for env-based secrets.** Config entries reference environment variable
   names via `key_var`; the loader resolves them at runtime. Raw secrets never appear
   in config files or git history.

5. **Multi-account structures are first-class.**
   A provider with multiple accounts is expressed as:
   ```
   provider_name:
     account_x: { base_url, model, key_var, ... }
     account_y: { base_url, model, key_var, ... }
   ```
   The system registers these as `provider_name_account_x`, `provider_name_account_y`
   automatically. Adding or removing an account requires only a `config set` — no code.

6. **Runtime config overrides codebase defaults.**
   Config resolution follows a strict layer hierarchy — later layers win:
   - Layer 1: `config/*.json` — codebase defaults (committed, shared)
   - Layer 2: `~/.memory/config/*.json` — personal runtime overrides (never committed)

   Personal preferences, API keys, active model selection, and account-specific
   settings always live in the runtime layer. The codebase layer is a template only.

### When Code Changes Are Justified
- A new wire protocol or message format that cannot be expressed through existing
  config fields (e.g. a non-standard auth scheme, a different request structure).
- A new capability class with no existing interface (e.g. streaming, tool-use, vision).
- A bug fix or performance improvement.

If you find yourself adding a named provider block just to set a URL or model name —
stop. Put that in config instead.

## Definition of Done
1. Code changes implemented.
2. Relevant tests/checks pass (or failures documented).
3. Documentation updated when needed.
4. Handoff summary includes files touched and next steps.
