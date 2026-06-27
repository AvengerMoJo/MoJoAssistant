# Browser MCP Setup Guide (Playwright vs Webwright)

MoJoAssistant supports browser automation through the `browser` tool category. You have two options — pick the one that fits your workflow.

---

## Choose Your Browser Backend

| | **Webwright (Default)** | **Playwright MCP** |
|---|---|---|
| **Paradigm** | Code-as-action — agent writes Playwright scripts | Step-by-step browser control (click, type, snapshot) |
| **Best for** | Complex multi-step workflows, reusable automation scripts | Interactive tasks, form filling, page inspection |
| **State** | Local workspace (code, screenshots, logs) is the state | Browser session is the workspace |
| **Install** | `pip install webwright && playwright install chromium` | `npm install -g @playwright/mcp && npx playwright install chromium` |
| **Requires** | Python 3.10+ | Node.js + npm |
| **Model cost** | Uses your MoJo LLM budget | Uses your MoJo LLM budget (no extra API key needed) |
| **Origin** | [Webwright](https://github.com/microsoft/Webwright) by Microsoft Research | [Playwright MCP](https://github.com/anthropics/anthropic-quickstarts/tree/main/mcp-server-playwright) by Microsoft/Anthropic |

**Why Webwright is the default for agentic tasks:**
- Agents write complete Playwright scripts and debug them iteratively
- No need to maintain browser state across tool calls
- Scripts are reusable and can be saved as artifacts
- Python-native integration fits MoJoAssistant's stack

**Both are enabled by default.** Tools get prefixed names (`webwright__*`, `playwright__*`). Roles that grant `browser` access get tools from both backends.

---

## Option A — Playwright MCP (Recommended for Most Users)

### Step 1 — Install Node.js

**Debian / Ubuntu:**
```bash
sudo apt install nodejs npm
```

**macOS (Homebrew):**
```bash
brew install node
```

**Verify:**
```bash
node --version
npm --version
```

### Step 2 — Install Playwright MCP

```bash
npm install -g @playwright/mcp
npx playwright install chromium
```

This installs the MCP server and downloads the Chromium browser binary.

### Step 3 — Verify config

The default config is already in `config/mcp_servers.json`:

```json
{
  "id": "playwright",
  "name": "Playwright MCP",
  "transport": "stdio",
  "command": "npx",
  "args": ["@playwright/mcp@latest", "--headless"],
  "category": "browser",
  "enabled": true
}
```

### Step 4 — Restart and test

Restart MoJoAssistant. Browser tools (`playwright__browser_navigate`, `playwright__browser_click`, `playwright__browser_snapshot`, etc.) should appear in the tool catalog.

Test:
```
Use the scheduler tool to add a task that navigates to https://example.com and takes a screenshot.
```

---

## Option B — Webwright (Code-as-Action)

[Webwright](https://github.com/microsoft/Webwright) by Microsoft Research takes a different approach: instead of step-by-step browser commands, the agent writes complete Playwright scripts. This is more robust for complex workflows and produces reusable automation code.

### Step 1 — Install Webwright

```bash
pip install webwright
playwright install chromium
```

### Step 2 — Configure in MoJoAssistant

Add Webwright to your personal MCP servers config (`~/.memory/config/mcp_servers.json`):

```json
{
  "servers": [
    {
      "id": "webwright",
      "name": "Webwright",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "webwright.run.cli", "--mcp"],
      "category": "browser",
      "enabled": true
    }
  ]
}
```

### Step 3 — Disable Playwright (optional)

If you only want Webwright, disable Playwright in your personal config:

```json
{
  "servers": [
    {
      "id": "playwright",
      "enabled": false
    }
  ]
}
```

### Step 4 — Restart and test

Restart MoJoAssistant. Webwright tools will appear in the `browser` category.

---

## Using Both Simultaneously

You can have both enabled. MoJoAssistant registers tools from all enabled servers in the `browser` category. Roles with `browser` access will see tools from both backends.

To use one or the other for a specific task, the role's system prompt can specify which tools to prefer. For example:
- "Use `playwright__browser_*` tools for this task" — step-by-step
- "Write a Playwright script using Webwright for this task" — code-as-action

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `npx: command not found` | Install Node.js and npm (Step 1 for Playwright) |
| `playwright: command not found` | Run `npx playwright install chromium` |
| Chromium download fails | Check network; try `npx playwright install --with-deps chromium` (installs system deps) |
| `webwright: module not found` | Run `pip install webwright` in your venv |
| Browser tools not showing | Check `config/mcp_servers.json` — `enabled` must be `true` |
| Headless mode issues | Playwright runs `--headless` by default; remove the flag in args for headed mode |

---

## Personal Override

To customize browser MCP settings:

Create or edit `~/.memory/config/mcp_servers.json`:

```json
{
  "servers": [
    {
      "id": "playwright",
      "enabled": false
    },
    {
      "id": "webwright",
      "name": "Webwright",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "webwright.run.cli", "--mcp"],
      "category": "browser",
      "enabled": true
    }
  ]
}
```

Personal config wins over system config on any key conflict.
