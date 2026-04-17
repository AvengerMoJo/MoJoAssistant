#!/bin/bash
# Install MoJoAssistant as a launchd user agent (macOS)
# After this, the scheduler runs 24/7 and auto-starts on login.
#
# Usage:
#   ./scripts/install_service_macos.sh          # install + start
#   ./scripts/install_service_macos.sh --stop   # stop and unload
#   ./scripts/install_service_macos.sh --status # show agent status + logs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.mojoassistant"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/MoJoAssistant"
CLAUDE_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }

# ── Stop / unload ─────────────────────────────────────────────────────────────
if [[ "$1" == "--stop" ]]; then
    info "Stopping and unloading $LABEL..."
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && ok "Stopped" || warn "Was not loaded"
    rm -f "$PLIST_FILE" && ok "Plist removed" || true
    exit 0
fi

# ── Status ────────────────────────────────────────────────────────────────────
if [[ "$1" == "--status" ]]; then
    info "Launch agent status:"
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null || warn "Agent not loaded"
    echo ""
    if [[ -f "$LOG_DIR/stdout.log" ]]; then
        info "Last 30 lines (stdout):"
        tail -30 "$LOG_DIR/stdout.log"
    fi
    if [[ -f "$LOG_DIR/stderr.log" ]]; then
        info "Last 10 lines (stderr):"
        tail -10 "$LOG_DIR/stderr.log"
    fi
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  MoJoAssistant — macOS launchd installer${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Validate project
[[ -f "$PROJECT_DIR/unified_mcp_server.py" ]] || { err "unified_mcp_server.py not found in $PROJECT_DIR"; exit 1; }
[[ -f "$PROJECT_DIR/venv/bin/python" ]]        || { err "venv not found — run install.sh first"; exit 1; }
[[ -f "$PROJECT_DIR/.env" ]]                   || { err ".env not found — copy .env.example and configure it"; exit 1; }
ok "Project validated: $PROJECT_DIR"

# Preflight: check system tools and MCP dependencies
info "Running preflight check..."
if "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/scripts/preflight.py" 2>&1; then
    ok "Preflight passed"
else
    echo ""
    warn "Some preflight checks failed (see above)."
    echo -e "  Re-run with install prompts:  ${BLUE}python scripts/preflight.py${NC}"
    echo -e "  Auto-fix non-manual items:    ${BLUE}python scripts/preflight.py --auto${NC}"
    echo ""
    read -rp "Continue anyway? [y/N] " _cont
    [[ "$_cont" =~ ^[Yy]$ ]] || exit 1
fi

# Create log directory
mkdir -p "$LOG_DIR"
ok "Log directory: $LOG_DIR"

# Unload existing agent if present
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

# Write plist (paths resolved at install time)
mkdir -p "$PLIST_DIR"
cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/venv/bin/python</string>
        <string>${PROJECT_DIR}/unified_mcp_server.py</string>
        <string>--mode</string>
        <string>http</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <!-- Load .env variables -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${HOME}/.cargo/bin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/stderr.log</string>

    <!-- Auto-start at login -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Restart on crash -->
    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>5</integer>
</dict>
</plist>
EOF
ok "Plist written: $PLIST_FILE"

# Load .env into plist EnvironmentVariables (expand all KEY=VALUE lines)
info "Injecting .env into plist..."
python3 - <<PYEOF
import re, plistlib, os
from pathlib import Path

plist_path = "$PLIST_FILE"
env_path   = "$PROJECT_DIR/.env"

with open(plist_path, "rb") as f:
    data = plistlib.load(f)

env_vars = data.setdefault("EnvironmentVariables", {})
for line in Path(env_path).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, val = line.partition("=")
    key = key.strip()
    val = val.strip().strip('"').strip("'")
    if key and val:
        env_vars[key] = val

with open(plist_path, "wb") as f:
    plistlib.dump(data, f)

print(f"  Injected {len(env_vars)} environment variables")
PYEOF
ok ".env variables injected into plist"

# Load the agent
launchctl bootstrap "gui/$(id -u)" "$PLIST_FILE"
sleep 2

if launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -q "state = running"; then
    ok "Agent is running"
else
    # Check if the process is up via port
    if lsof -i :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        ok "Agent is running (port 8000 open)"
    else
        warn "Agent loaded but may still be starting — check logs:"
        warn "  tail -f $LOG_DIR/stderr.log"
    fi
fi

# ── Update Claude config ───────────────────────────────────────────────────────
echo ""
info "Updating Claude MCP config to use HTTP mode..."

if [[ ! -f "$CLAUDE_CFG" ]]; then
    warn "Claude config not found at $CLAUDE_CFG — skipping auto-update"
    warn "Manually add to your Claude MCP config:"
    echo '  "MoJoAssistant": { "url": "http://localhost:8000/" }'
else
    MCP_KEY=$(grep '^MCP_API_KEY=' "$PROJECT_DIR/.env" | cut -d= -f2 | tr -d '"' | tr -d "'")
    cp "$CLAUDE_CFG" "${CLAUDE_CFG}.bak.$(date +%Y%m%d_%H%M%S)"
    ok "Config backed up"

    python3 - <<PYEOF
import json

cfg_path = "$CLAUDE_CFG"
api_key  = "$MCP_KEY"

with open(cfg_path) as f:
    cfg = json.load(f)

servers = cfg.setdefault("mcpServers", {})

for key in list(servers.keys()):
    cmd  = servers[key].get("command", "")
    args = " ".join(servers[key].get("args", []))
    if "mojo" in key.lower() or "mojo" in cmd.lower() or "mojo" in args.lower():
        print(f"  removing old entry: {key}")
        del servers[key]

servers["MoJoAssistant"] = {
    "url": "http://localhost:8000/",
    "headers": {"Authorization": f"Bearer {api_key}"} if api_key else {}
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("  MoJoAssistant HTTP entry added")
PYEOF
    ok "Claude config updated → HTTP mode"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ok "Installation complete"
echo ""
echo "  Manage the agent:"
echo "    launchctl start  $LABEL    # start"
echo "    launchctl stop   $LABEL    # stop (stays loaded)"
echo "    ./scripts/install_service_macos.sh --stop    # stop + remove"
echo "    ./scripts/install_service_macos.sh --status  # quick status"
echo ""
echo "  Live logs:"
echo "    tail -f $LOG_DIR/stdout.log"
echo "    tail -f $LOG_DIR/stderr.log"
echo ""
echo "  After restarting Claude, reconnect with /mcp"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
