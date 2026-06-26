# tmux MCP Setup Guide

MoJoAssistant uses [tmux-mcp-rs](https://github.com/nicholasgasior/tmux-mcp-rs) as its virtual terminal backend. Agents get persistent shell sessions via tmux — run commands, read output, manage windows and panes.

---

## Prerequisites

| Requirement | Why |
|---|---|
| tmux | Terminal multiplexer — the runtime backend |
| Rust toolchain (cargo) | Builds tmux-mcp-rs from source |

---

## Step 1 — Install tmux

**Debian / Ubuntu:**
```bash
sudo apt install tmux
```

**macOS (Homebrew):**
```bash
brew install tmux
```

**Arch:**
```bash
sudo pacman -S tmux
```

Verify:
```bash
tmux -V
```

---

## Step 2 — Install Rust toolchain

If you don't have Rust installed:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

Verify:
```bash
cargo --version
```

---

## Step 3 — Install tmux-mcp-rs

```bash
cargo install tmux-mcp-rs
```

This builds the binary and places it at `~/.cargo/bin/tmux-mcp-rs`.

Verify:
```bash
~/.cargo/bin/tmux-mcp-rs --help
```

---

## Step 4 — Verify MoJoAssistant config

The default config is already in `config/mcp_servers.json`:

```json
{
  "id": "tmux",
  "name": "tmux MCP (tmux-mcp-rs)",
  "transport": "stdio",
  "command": "~/.cargo/bin/tmux-mcp-rs",
  "args": ["--shell-type", "bash", "--config", "config/tmux-mcp.toml"],
  "category": "terminal",
  "enabled": true
}
```

The security denylist is in `config/tmux-mcp.toml` — it blocks dangerous commands (`rm -rf /`, fork bombs, reverse shells, etc.). To customize, copy to `~/.memory/config/tmux-mcp.toml`.

---

## Step 5 — Restart and test

Restart MoJoAssistant, then verify the terminal tools are registered:

```
Use the config tool to check system health.
```

Or check the dashboard — tmux tools (`tmux__list-sessions`, `tmux__execute-command`, etc.) should appear in the tool catalog.

Test from an agentic task:
```
Use the scheduler tool to add a task that lists tmux sessions.
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `tmux-mcp-rs: command not found` | Ensure `~/.cargo/bin` is in your PATH, or use the full path in config |
| `tmux: command not found` | Install tmux (Step 1) |
| `cargo: command not found` | Install Rust toolchain (Step 2) |
| Tools not showing up | Check `config/mcp_servers.json` — `enabled` must be `true` and `tmux` binary must exist |
| Permission denied on commands | Check `config/tmux-mcp.toml` denylist — the command may be blocked |

---

## How It Works

- tmux-mcp-rs spawns a tmux server and exposes it over MCP (stdio transport)
- MoJoAssistant registers 20+ `tmux__*` tools in the `terminal` category
- Roles with `terminal` in their tool access can create sessions, run commands, and read output
- Each agentic task gets isolation via dedicated tmux sessions/windows/panes
- The `SHELL` env var points to `scripts/agent-shell` which prepends `$MEMORY_PATH/capability` to PATH

---

## Personal Override

To customize tmux MCP settings without touching the system config:

```bash
cp config/tmux-mcp.toml ~/.memory/config/tmux-mcp.toml
# Edit ~/.memory/config/tmux-mcp.toml
```

To disable tmux MCP entirely, set `enabled: false` in your personal `~/.memory/config/mcp_servers.json`:

```json
{
  "servers": [
    {
      "id": "tmux",
      "enabled": false
    }
  ]
}
```
