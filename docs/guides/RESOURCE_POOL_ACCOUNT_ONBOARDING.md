# Resource Pool Account Onboarding (MCP Self-Serve)

This guide is for adding a new LLM API account without code changes.

## Goal

Use MCP `config` tool + env key file to register a new account in scheduler resource pool.

Scheduler/agentic tasks read from:
- `config/resource_pool_config.json`
- `~/.memory/resource_pool.env`

`llm_config.json` alone is not enough for agentic scheduler routing.

## What To Prepare

Prepare these before calling MCP:

1. Provider endpoint (example: `https://openrouter.ai/api/v1`)
2. API key (do not paste in chat logs)
3. Account ID slug (example: `openrouter_newacct`)
4. Env var name (example: `OPENROUTER_API_KEY_NEWACCT`)
5. Routing group (example: `openrouter_free`)
6. Tier (`free`, `free_api`, `paid`)
7. Priority (lower means selected earlier)
8. Model (example: `openrouter/auto`)

## Step 1: Add Resource Entry With MCP Config

Tool: `config`

```json
{
  "action": "set",
  "module": "resource_pool",
  "path": "resources.openrouter_newacct",
  "value": {
    "type": "api",
    "provider": "openai-compatible",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY_NEWACCT",
    "model": "openrouter/auto",
    "tier": "free_api",
    "priority": 10,
    "enabled": true,
    "context_limit": 131072,
    "output_limit": 8192,
    "account_group": "openrouter_free",
    "description": "OpenRouter free-tier routing (newacct)"
  }
}
```

## Step 2: Add API Key To Sandbox Env File

File: `~/.memory/resource_pool.env`

```bash
OPENROUTER_API_KEY_NEWACCT=sk-or-v1-xxxx
```

Notes:
- Keep one key per line: `ENV_NAME=value`
- No quotes
- Do not store real keys in repo config JSON

## Step 3: Reload Runtime

Option A (preferred): reload config via MCP `config` write (already done in step 1) and restart MCP service if key file changed.

Option B: restart scheduler daemon if needed:

- `scheduler_restart_daemon`

If agentic task still uses stale resource set, restart MCP service process.

## Step 4: Verify

1. Call `resource_pool_status`
2. Confirm new resource id exists and status is `available`
3. Submit a small `agentic` task with:

```json
{
  "tier_preference": ["free_api"],
  "max_iterations": 1
}
```

4. Confirm task/session shows the expected resource id in logs/metrics

## Common Failure Cases

1. Resource exists but not selected:
- Priority too high (numerically larger)
- Wrong `tier_preference`
- `enabled` is false

2. Resource selected but call fails:
- Missing/invalid key in `~/.memory/resource_pool.env`
- Wrong `base_url`
- Provider does not support `/chat/completions`

3. No failover behavior:
- Accounts not in same `account_group`
- Same group exists but only one resource is `available`

## Copy/Paste Prompt For MCP Clients

Use this as operator instruction:

```
Add a new API account to resource pool only (no code edits).
1) config.set module=resource_pool path=resources.<resource_id> with type/provider/base_url/api_key_env/model/tier/priority/enabled/context_limit/output_limit/account_group/description.
2) Write API key into ~/.memory/resource_pool.env as <api_key_env>=<value>.
3) Reload/restart runtime if needed.
4) Verify with resource_pool_status and a 1-iteration agentic task using tier_preference=["free_api"].
5) Report exact resource id selected and final status.
```
