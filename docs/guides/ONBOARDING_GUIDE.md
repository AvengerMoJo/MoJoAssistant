# MoJoAssistant — 5-Minute Onboarding

**Goal:** From zero to a working AI assistant with memory in 5 minutes.

---

## Step 1: Install (1 minute)

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
./scripts/install.sh
```

The installer creates a venv, installs dependencies, and checks for required tools.

---

## Step 2: Check what works (30 seconds)

```bash
python3 scripts/doctor.py --setup
```

You'll see something like:

```
Core (Stable)
  ✅  Scheduler daemon       — running, 4 tasks queued
  ✅  HITL inbox             — reachable, 0 pending
  ✅  Memory search          — local embeddings active (all-MiniLM-L6-v2)
  ✅  MCP tool surface       — 14 tools registered
  ✅  Policy checker         — active, 23 patterns loaded
  ✅  Role system            — 7 roles loaded
  ✅  Audit trail            — append-only log active

Optional (Experimental)
  ⚠️  Agent execution (LLM)  — no local LLM running
  ⚠️  Coding agent bridge    — claude and opencode not found in PATH
```

Everything in "Core" should be green. The experimental items are optional — MoJo works without them.

---

## Step 3: Connect to Claude (1 minute)

**Option A: Claude Desktop (same machine)**

Add to `~/.claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "mojo": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer demo_key_for_development"
      }
    }
  }
}
```

**Option B: Claude Code (same machine)**
```bash
claude mcp add mojo http://localhost:8000/mcp
```

**Option C: Claude.ai (browser — needs tunnel)**
```bash
# In a separate terminal:
cloudflared tunnel --url http://localhost:8000
# Copy the URL it prints, add it to Claude.ai → Settings → Integrations
```

---

## Step 4: Start the server (10 seconds)

```bash
# HTTP mode (dashboard + MCP + scheduler)
python unified_mcp_server.py --mode http --port 8000

# Or as a persistent service:
./scripts/install_service.sh
```

Open `http://localhost:8000/dashboard` to see the dashboard.

---

## Step 5: See it work (2 minutes)

### In Claude, try these:

**Check what MoJo knows:**
```
Use the get_context tool with type="orientation"
```

**Talk to a role:**
```
Use the dialog tool with role_id="researcher" and message="What do you know about this project?"
```

**Schedule a task:**
```
Use the scheduler tool with action="add", type="assistant", role_id="researcher",
description="Summarize the latest AI news"
```

**Search memory:**
```
Use the search_memory tool with query="project overview"
```

### In the dashboard:

- **`/dashboard`** — overview with task queue and recent events
- **`/dashboard/tasks`** — all tasks with status, filters, session transcripts
- **`/dashboard/chat`** — talk directly to any role
- **`/dashboard/events`** — full event log with SSE auto-update

---

## What just happened?

1. **MoJo installed** with 7 bundled roles (researcher, developer, code_reviewer, etc.)
2. **5 demo tasks were seeded** — including a memory roundtrip test and a policy enforcement test
3. **The scheduler is running** — it will pick up tasks and execute them using available LLM resources
4. **The dashboard is live** — you can see events, tasks, and chat with roles
5. **Memory is active** — conversations are stored and searchable via semantic embeddings

---

## Next steps

| Want to... | Do this |
|-----------|---------|
| Add an LLM for agent tasks | Run `python3 scripts/doctor.py --fix` — guided setup |
| Create a custom role | Copy `config/roles/researcher.json` to `~/.memory/roles/my_role.json` and edit |
| Set up daily briefings | `scheduler(action="add", cron="0 9 * * *", role_id="researcher", description="Morning briefing")` |
| Get push notifications | See [Notifications Setup](NOTIFICATIONS_SETUP.md) |
| Connect Google Calendar | See [Google Workspace Setup](GOOGLE_WORKSPACE_SETUP.md) |
| Understand the architecture | Read [System Overview](../architecture/SYSTEM_README.md) |
| See what MoJo protects | Visit `/dashboard/privacy` after running a few tasks |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `doctor.py` shows red for Scheduler | Make sure the server is running: `python unified_mcp_server.py --mode http --port 8000` |
| Claude can't connect | Check the URL and API key match between Claude config and MoJo `.env` |
| No roles found | Run `python3 scripts/doctor.py --fix` to unpack bundled roles |
| Tasks stay pending | Check if an LLM is configured — tasks need a brain to run |
| Dashboard asks for password | Set `DASHBOARD_PASSWORD` in `.env`, or use `MCP_API_KEY` value |

See [Installation Guide](../INSTALL.md) for full configuration reference.
