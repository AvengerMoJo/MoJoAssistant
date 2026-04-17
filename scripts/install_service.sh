#!/bin/bash
# Install MoJoAssistant as a systemd user service (Linux)
# After this, the scheduler runs 24/7 independently of Claude Code.
#
# Usage:
#   ./scripts/install_service.sh          # install + start
#   ./scripts/install_service.sh --stop   # stop and disable
#   ./scripts/install_service.sh --status # show service status + logs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="mojoassistant"
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
CLAUDE_CFG="$HOME/.config/Claude/claude_desktop_config.json"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }

# ── Stop / disable ────────────────────────────────────────────────────────────
if [[ "$1" == "--stop" ]]; then
    info "Stopping and disabling $SERVICE_NAME..."
    systemctl --user stop  "$SERVICE_NAME" 2>/dev/null && ok "Stopped"  || warn "Was not running"
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null && ok "Disabled" || warn "Was not enabled"
    exit 0
fi

# ── Status ───────────────────────────────────────────────────────────────────
if [[ "$1" == "--status" ]]; then
    systemctl --user status "$SERVICE_NAME" --no-pager || true
    echo ""
    info "Last 30 log lines:"
    journalctl --user -u "$SERVICE_NAME" -n 30 --no-pager || true
    exit 0
fi

# ── Install ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  MoJoAssistant — service installer${NC}"
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

# Write service file (inline so paths are resolved at install time)
mkdir -p "$HOME/.config/systemd/user"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=MoJoAssistant MCP Server (HTTP mode)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/venv/bin/python \\
    unified_mcp_server.py --mode http --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=mixed
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mojoassistant

[Install]
WantedBy=default.target
EOF
ok "Service file written: $SERVICE_FILE"

# Reload + enable + start
systemctl --user daemon-reload
ok "systemd daemon reloaded"

systemctl --user enable "$SERVICE_NAME"
ok "Service enabled (auto-start on login)"

systemctl --user restart "$SERVICE_NAME"
sleep 2

if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running"
else
    err "Service failed to start — check: journalctl --user -u $SERVICE_NAME -n 50"
    exit 1
fi

# ── Update Claude config to use HTTP ─────────────────────────────────────────
echo ""
info "Updating Claude MCP config to use HTTP mode..."

if [[ ! -f "$CLAUDE_CFG" ]]; then
    warn "Claude config not found at $CLAUDE_CFG — skipping auto-update"
    warn "Manually add this entry to your Claude MCP config:"
else
    # Read MCP_API_KEY from .env
    MCP_KEY=$(grep '^MCP_API_KEY=' "$PROJECT_DIR/.env" | cut -d= -f2 | tr -d '"' | tr -d "'")

    # Backup
    cp "$CLAUDE_CFG" "${CLAUDE_CFG}.bak.$(date +%Y%m%d_%H%M%S)"
    ok "Config backed up"

    # Use python to update JSON (preserve existing entries)
    python3 - <<PYEOF
import json, sys

cfg_path = "$CLAUDE_CFG"
api_key  = "$MCP_KEY"

with open(cfg_path) as f:
    cfg = json.load(f)

servers = cfg.setdefault("mcpServers", {})

# Remove old STDIO entries for MoJo
for key in list(servers.keys()):
    cmd = servers[key].get("command", "")
    args = " ".join(servers[key].get("args", []))
    if "mojo" in key.lower() or "mojo" in cmd.lower() or "mojo" in args.lower():
        print(f"  removing old entry: {key}")
        del servers[key]

# Add HTTP entry
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

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ok "Installation complete"
echo ""
echo "  Manage the service:"
echo "    systemctl --user start|stop|restart|status mojoassistant"
echo "    journalctl --user -u mojoassistant -f          # live logs"
echo "    ./scripts/install_service.sh --status          # quick status"
echo ""
echo "  Restart to pick up code changes:"
echo "    systemctl --user restart mojoassistant"
echo ""
echo "  After restarting Claude Code, reconnect with /mcp"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
