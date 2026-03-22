# Release Notes — v1.2.3-beta

## Theme: Universal Tool Access — Any MCP Server Becomes Agent Tools

Three interconnected upgrades land in this release: a unified resource pool, a
catalog-driven tool system, and a generic MCP client bridge that lets any external
MCP server's tools flow directly to agent roles. The result is that adding a new
capability to the agent fleet is now a one-line config change.

Validated end-to-end: Rebecca autonomously navigated live GitHub pages using
Playwright MCP — clicking through directories, reading source files, synthesizing
findings — without any custom browser code in MoJo.

---

## 1. Resource Pool Unification

### Two-layer `resource_pool.json`
`llm_config.json` is superseded by `config/resource_pool.json` (system defaults)
merged with `~/.memory/config/resource_pool.json` (user personal). Both use a flat
`resources` dict instead of nested `local_models`/`api_models` groupings.

```json
{
  "resources": {
    "openrouter_avengermojo": {
      "type": "api", "provider": "openrouter",
      "tier": "free_api", "capabilities": ["tool_use"]
    }
  }
}
```

### `acquire_by_requirements(requirements)`
New `ResourceManager` method replaces per-role `preferred_resource_id`. Roles declare
what they need; the pool finds the best match:

```json
"resource_requirements": {
  "tier": ["free_api", "free"],
  "min_context": 65536,
  "capabilities": ["vision"]
}
```

Filters by tier, `min_context`, `min_output`, and `capabilities`. Round-robin across
equal-priority resources for load distribution. Legacy `preferred_resource_id` still
accepted as a fallback.

### `capabilities` field on `LLMResource`
New `List[str]` field (e.g. `["tool_use", "vision"]`) enables capability-gated tool
result routing — vision models receive screenshots, text models receive text only.

---

## 2. Tool Catalog + Category-Based Access

### `config/tool_catalog.json`
Central registry mapping tool names to categories (`memory`, `file`, `web`, `exec`,
`comms`, `browser`, `terminal`) with intent-driven descriptions used by `list_tools`.

```json
"categories": {
  "browser": { "description": "Headless browser — render pages, interact, screenshot" },
  "web":     { "description": "Web search and HTTP requests" }
}
```

### `tool_access` replaces `tools` in roles
Roles now declare capability categories, not explicit tool names:

```json
"tool_access": ["web", "memory", "browser"]
```

`_resolve_tools_from_role` expands categories → tool names at execution time via
the catalog **and** the dynamic registry. Adding a new tool to a category
automatically makes it available to all roles that declare that category.

### `ask_user` always injected
Marked `always_injected: true` in the catalog — excluded from category expansion but
always added to every agent's tool list. Roles cannot accidentally drop the HITL
escape hatch.

---

## 3. Web Search + Fetch URL (Builtin Tools)

### `web_search` — Google Custom Search
Queries the Google Custom Search API and returns titles, snippets, and URLs.
Requires `GOOGLE_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` in `.env`.

### `fetch_url` — Full page content
HTTP GET + HTML stripping → plain text. Used after `web_search` to read the full
content of a result page. `max_chars` parameter (default 8000).

Both are now hardcoded builtins in `_register_builtins()` — they survive any
`dynamic_tools.json` regeneration and are always available.

---

## 4. MCPClientManager — Any MCP Server Becomes Agent Tools

### Architecture
`app/scheduler/mcp_client_manager.py` manages long-lived connections to external
MCP servers using the MCP Python SDK (`ClientSession` + `stdio_client`).

On `AgenticExecutor` startup, it reads `config/mcp_servers.json`, connects to each
enabled server, discovers their tools, and registers them in `DynamicToolRegistry`
with executor type `external_mcp` and the server's category.

```
config/mcp_servers.json
  └── playwright (transport: stdio, category: browser)
        → connects: npx @playwright/mcp@latest --headless
        → discovers: 22 tools
        → registers: playwright__browser_navigate, playwright__browser_click, ...
              └── executor: {type: "external_mcp", server: "playwright", tool: "browser_navigate"}
```

### `external_mcp` executor type
New executor type in `DynamicToolRegistry`. When an agent calls a registered tool,
the registry forwards the call to `MCPClientManager.call_tool(server_id, tool_name, args)`
which routes it to the live `ClientSession`.

### Generalised pattern
To add any new MCP server to the agent tool pool, add one entry to `mcp_servers.json`:

```json
{
  "id": "github",
  "command": "npx", "args": ["@modelcontextprotocol/server-github"],
  "category": "vcs",
  "enabled": true
}
```

Then add `"vcs"` to any role's `tool_access`. No code changes required.

### `category` field on `ToolDefinition`
All builtins are now tagged with their category. `_resolve_tools_from_role` checks
both `tool_catalog.json` and the live registry for category matches — so dynamically
discovered external MCP tools flow to roles that declare their category.

---

## 5. Agent Protocol Stack (§21) + Visual Agent Design (§22)

### §21 — Character → Role → Goal protocol
Full validation protocol documenting the three-layer agent model:

- **Character** (NineChapter): weighted score from 5 dimensions, derives system
  prompt sections. Score = `core_values×0.25 + emotional_reaction×0.20 + cognitive_style×0.25 + social_orientation×0.15 + adaptability×0.15`
- **Role**: assigns character to a job (`tool_access`, `resource_requirements`,
  `behavior_rules`, `hitl_conditions`)
- **Goal**: urgency×importance matrix drives attention level (noise/digest/alert/blocking)
  and resource tier escalation (free → free_api → paid)

`role_id` is now required for assistant tasks. Inline `system_prompt` in task config
triggers a deprecation warning.

### §22 — Visual agent adaptor design
Architecture for browser and terminal tool categories, including:
- Playwright MCP as the browser backend (implemented this release)
- Terminal session tools via tmux (planned v1.3)
- Capability-gated visual payloads (screenshot vs text degradation)
- `visual_mode: full | text_only | unavailable` in task session metadata

---

## 6. Rebecca Role — Validated with Live Browser Research

Rebecca's role (`~/.memory/roles/rebecca.json`) was updated:

- `tool_access` expanded to `["web", "memory", "browser"]`
- System prompt updated with correct tool names (`memory_search`, `web_search`,
  `fetch_url`, Playwright tools) and a "when a tool is unavailable" escalation protocol
- `resource_requirements` added: `tier: ["free_api", "free"]`, `min_context: 65536`

**Live validation:** Rebecca was tasked with researching `gpt-researcher` on GitHub
using browser tools. She autonomously navigated to the repo, clicked through
directories, read `agent.py` source, recovered from a failed click, and produced a
structured findings report — all from live page content, not training knowledge.

---

## Upgrade Notes

### New config files
- `config/resource_pool.json` — replace `llm_config.json` entries here
- `config/mcp_servers.json` — add external MCP servers (Playwright pre-configured)
- `config/tool_catalog.json` — now includes `browser` and `terminal` categories

### Dependencies
```bash
# Playwright MCP (auto-installed on first use via npx)
# No pip install required — uses system Node.js
```

### Role migration
Replace `tools: [...]` with `tool_access: [...]` using category names. Legacy `tools`
list still accepted but logs a migration notice.

### Environment variables
```bash
GOOGLE_API_KEY=...            # for web_search
GOOGLE_SEARCH_ENGINE_ID=...   # for web_search
```

---

## What's Next (v1.3)

- **Terminal tools** — `terminal_exec`, `terminal_read` via tmux sessions
- **`HttpAgentExecutor`** — drive ZeroClaw and other HTTP agents via MAP protocol (§17/§18)
- **§21 enforcement** — `role_id` required validation, `urgency`/`importance` fields,
  `behavior_rules` execution, `config doctor` NineChapter score validation
- **Hybrid memory search** — BM25 + embedding for research roles (§20)
