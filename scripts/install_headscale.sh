#!/bin/bash
# Install self-hosted Headscale (Tailscale-compatible mesh VPN control plane)
# as a system systemd service.
#
# This is a SYSTEM service (not --user like mojoassistant.service) because it
# needs a stable bind independent of any user session, and is infra shared by
# the whole machine, not just this app.
#
# Usage:
#   sudo ./scripts/install_headscale.sh                # install + start (default port, auto-picked if busy)
#   sudo ./scripts/install_headscale.sh --port 8091     # install + start on an explicit port
#   sudo ./scripts/install_headscale.sh --stop          # stop and disable
#   ./scripts/install_headscale.sh --status             # show service status + logs
#
# Port: no port is safe to hardcode on every machine -- found live
# 2026-07-23, the first pick (8080) turned out to already be LMStudio's API
# gateway on this machine. DEFAULT_PORT below is just a starting guess; the
# script always checks it's actually free before using it, and --port lets
# you skip the guess entirely.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="headscale"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_DIR="/etc/headscale"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
# The .deb package (installed below) puts the binary at /usr/bin/headscale
# per Debian convention -- NOT /usr/local/bin. Found live 2026-07-23: a
# hardcoded /usr/local/bin/headscale here caused the systemd unit's
# ExecStart to point at a nonexistent path (status=203/EXEC, ~20 failed
# restart attempts before the mismatch was diagnosed). Resolve dynamically
# so this can't silently drift from whatever the package manager actually
# does again.
BINARY_PATH="$(command -v headscale || echo /usr/bin/headscale)"
HEADSCALE_USER="headscale"
DEFAULT_PORT="8091"
HEADSCALE_PORT=""
MOJO_NAMESPACE="mojo"
MAGIC_DNS_DOMAIN="mojo.internal"
HEADSCALE_REPO="juanfont/headscale"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }

port_in_use() {
    # True (0) if something is already listening on 127.0.0.1:$1.
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

# ── Argument parsing (--port must be handled before --stop/--status so it
#    can't be silently ignored if passed alongside them) ────────────────────
ACTION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            HEADSCALE_PORT="$2"
            shift 2
            ;;
        --stop|--status)
            ACTION="$1"
            shift
            ;;
        *)
            err "Unknown argument: $1"
            exit 1
            ;;
    esac
done
set -- "$ACTION"

# ── Stop / disable ────────────────────────────────────────────────────────────
if [[ "$1" == "--stop" ]]; then
    info "Stopping and disabling $SERVICE_NAME..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null && ok "Stopped" || warn "Was not running"
    systemctl disable "$SERVICE_NAME" 2>/dev/null && ok "Disabled" || warn "Was not enabled"
    exit 0
fi

# ── Status ───────────────────────────────────────────────────────────────────
if [[ "$1" == "--status" ]]; then
    systemctl status "$SERVICE_NAME" --no-pager || true
    echo ""
    info "Last 30 log lines:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    echo ""
    info "Registered nodes:"
    "$BINARY_PATH" nodes list 2>/dev/null || warn "headscale binary not found or server not reachable"
    exit 0
fi

# ── Install ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Headscale — self-hosted mesh VPN control plane installer${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    err "This script must be run with sudo — Headscale is a system service"
    echo "  sudo $0"
    exit 1
fi

# ── Resolve port ─────────────────────────────────────────────────────────────
if [[ -n "$HEADSCALE_PORT" ]]; then
    # Explicit --port: respect it, but fail loudly rather than silently
    # picking something else if it's actually taken.
    if port_in_use "$HEADSCALE_PORT"; then
        err "Port $HEADSCALE_PORT (requested via --port) is already in use"
        ss -tlnp 2>/dev/null | grep ":$HEADSCALE_PORT\b" || true
        exit 1
    fi
    ok "Using requested port: $HEADSCALE_PORT"
else
    HEADSCALE_PORT="$DEFAULT_PORT"
    if port_in_use "$HEADSCALE_PORT"; then
        warn "Default port $HEADSCALE_PORT is already in use:"
        ss -tlnp 2>/dev/null | grep ":$HEADSCALE_PORT\b" || true
        for candidate in 8091 8092 8093 8094 8095 9091 9092; do
            if ! port_in_use "$candidate"; then
                HEADSCALE_PORT="$candidate"
                break
            fi
        done
        if port_in_use "$HEADSCALE_PORT"; then
            err "Could not find a free port automatically — pick one and re-run with --port <N>"
            exit 1
        fi
        info "Falling back to port $HEADSCALE_PORT — re-run with --port <N> to choose explicitly"
    fi
    ok "Using port: $HEADSCALE_PORT"
fi

# Detect architecture for the release download
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  HS_ARCH="amd64" ;;
    aarch64) HS_ARCH="arm64" ;;
    *) err "Unsupported architecture: $ARCH"; exit 1 ;;
esac
ok "Detected architecture: $ARCH ($HS_ARCH)"

if [[ -x "$BINARY_PATH" ]]; then
    ok "Headscale binary already installed: $($BINARY_PATH version 2>/dev/null || echo present)"
else
    info "Fetching latest Headscale release info..."
    LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/${HEADSCALE_REPO}/releases/latest" | grep -oP '"tag_name":\s*"\K[^"]+') \
        || { err "Failed to query GitHub releases API"; exit 1; }
    VERSION="${LATEST_TAG#v}"
    DEB_URL="https://github.com/${HEADSCALE_REPO}/releases/download/${LATEST_TAG}/headscale_${VERSION}_linux_${HS_ARCH}.deb"
    info "Downloading Headscale ${LATEST_TAG} for linux/${HS_ARCH}..."

    TMP_DEB="$(mktemp --suffix=.deb)"
    curl -fsSL -o "$TMP_DEB" "$DEB_URL" || { err "Download failed: $DEB_URL"; exit 1; }
    dpkg -i "$TMP_DEB" || { err "dpkg install failed"; rm -f "$TMP_DEB"; exit 1; }
    rm -f "$TMP_DEB"
    ok "Headscale ${LATEST_TAG} installed to $BINARY_PATH"
fi

# ── Config ───────────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR" /var/lib/headscale /var/run/headscale

if [[ -f "$CONFIG_FILE" ]]; then
    ok "Config already exists: $CONFIG_FILE (not overwriting — remove it first to regenerate)"
    # Found live 2026-07-23: the .deb package's own postinst had already
    # dropped its stock default config here (port 8080, base_domain
    # example.com) before this script's own "if not exists" check ever ran
    # -- so the intended port/domain silently never applied, and the
    # service failed with "bind: address already in use" against LMStudio.
    # Don't just trust an existing file blindly a second time — check.
    EXISTING_PORT="$(grep -oP '^listen_addr:\s*127\.0\.0\.1:\K[0-9]+' "$CONFIG_FILE" 2>/dev/null || echo "")"
    if [[ -n "$EXISTING_PORT" ]] && [[ "$EXISTING_PORT" != "$HEADSCALE_PORT" ]]; then
        warn "Existing config uses port $EXISTING_PORT, not the requested $HEADSCALE_PORT"
        if port_in_use "$EXISTING_PORT"; then
            err "Port $EXISTING_PORT (from existing config) is already in use by something else:"
            ss -tlnp 2>/dev/null | grep ":$EXISTING_PORT\b" || true
            echo "  Fix: sudo sed -i 's|:$EXISTING_PORT|:$HEADSCALE_PORT|g' $CONFIG_FILE && sudo systemctl restart $SERVICE_NAME"
        fi
    fi
else
    cat > "$CONFIG_FILE" <<EOF
# Headscale config — generated by install_headscale.sh
# Self-hosted control plane for MoJoAssistant's mesh network. Loopback-only
# by design for Phase 1 (single node = this machine); widen listen_addr only
# when a second machine actually needs to join.
server_url: http://127.0.0.1:${HEADSCALE_PORT}
listen_addr: 127.0.0.1:${HEADSCALE_PORT}
metrics_listen_addr: 127.0.0.1:9090

database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite

dns:
  magic_dns: true
  base_domain: ${MAGIC_DNS_DOMAIN}
  nameservers:
    global:
      - 1.1.1.1
      - 8.8.8.8

log:
  level: info
EOF
    ok "Config written: $CONFIG_FILE"
fi

# ── System user ──────────────────────────────────────────────────────────────
if id "$HEADSCALE_USER" &>/dev/null; then
    ok "System user '$HEADSCALE_USER' already exists"
else
    useradd --system --home /var/lib/headscale --shell /usr/sbin/nologin "$HEADSCALE_USER"
    ok "Created system user '$HEADSCALE_USER'"
fi
chown -R "$HEADSCALE_USER:$HEADSCALE_USER" /var/lib/headscale /var/run/headscale

# ── systemd unit ─────────────────────────────────────────────────────────────
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Headscale — self-hosted Tailscale-compatible mesh VPN control plane
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${HEADSCALE_USER}
Group=${HEADSCALE_USER}
ExecStart=${BINARY_PATH} serve
WorkingDirectory=/var/lib/headscale
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=headscale

[Install]
WantedBy=multi-user.target
EOF
ok "Service file written: $SERVICE_FILE"

systemctl daemon-reload
ok "systemd daemon reloaded"

systemctl enable "$SERVICE_NAME"
ok "Service enabled (auto-start on boot)"

systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Headscale service is running"
else
    err "Service failed to start — check: journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# ── Bootstrap: namespace + preauth key ───────────────────────────────────────
info "Creating '$MOJO_NAMESPACE' user/namespace..."
"$BINARY_PATH" users create "$MOJO_NAMESPACE" 2>/dev/null \
    && ok "Namespace '$MOJO_NAMESPACE' created" \
    || warn "Namespace '$MOJO_NAMESPACE' may already exist (continuing)"

info "Generating a reusable preauth key for node joining..."
PREAUTH_KEY=$("$BINARY_PATH" preauthkeys create --user "$MOJO_NAMESPACE" --reusable --expiration 24h 2>/dev/null | tail -1)

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ok "Headscale installation complete"
echo ""
echo "  Preauth key (valid 24h, use to join this machine as node 1 — do NOT commit this anywhere):"
echo -e "    ${GREEN}${PREAUTH_KEY}${NC}"
echo ""
echo "  Next step — join this machine to the tailnet:"
echo "    sudo apt install tailscale"
echo "    sudo tailscale up --login-server=http://127.0.0.1:${HEADSCALE_PORT} --authkey=${PREAUTH_KEY}"
echo "    tailscale status && tailscale ip -4"
echo "    sudo headscale nodes list"
echo ""
echo "  Manage the service:"
echo "    systemctl start|stop|restart|status headscale"
echo "    journalctl -u headscale -f                      # live logs"
echo "    sudo ./scripts/install_headscale.sh --status     # quick status"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
