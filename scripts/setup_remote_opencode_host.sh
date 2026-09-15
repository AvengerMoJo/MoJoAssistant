#!/usr/bin/env bash
# One-time bootstrap for a remote host that will run opencode server mode
# for MoJoAssistant's 'ssh' sandbox backend.
#
# Usage:
#   scripts/setup_remote_opencode_host.sh user@host [options]
#
# Options:
#   -i KEY          SSH identity file (default: agent/default key)
#   -p PORT         SSH port (default 22)
#   --ts-authkey K  Join the host to your Tailscale tailnet with this auth key
#                   (generate: tailscale.com admin console, or
#                    `tailscale authkey` on an authorized node)
#   --managed       Install opencode as an always-on systemd user service
#                   (opencode serve bound to 127.0.0.1:PORT with a random
#                   OPENCODE_SERVER_PASSWORD in ~/.mojo/server.env, mode 0600).
#                   MoJo then attaches to this single server with
#                   backends.ssh.use_managed=true instead of spawning per-task
#                   ephemeral servers. Expose it to the outside via the tailnet
#                   (bind 0.0.0.0 with --managed-bind 0.0.0.0, or a port forward).
#   --managed-port N  Server port for --managed (default 4096; also the bridge port)
#   --managed-bind H  Bind address for the managed server (default 127.0.0.1)
#
# What it does on the remote host:
#   1. installs opencode (bun if available, else the official curl installer)
#   2. optionally joins the tailnet (systemd service enabled)
#   3. with --managed: installs a systemd user unit `opencode-serve.service`
#      (Restart=always, linger enabled) + 0600 ~/.mojo/server.env
#   4. prints the tailscale hostname + next config steps
#
# The ssh sandbox backend can also install opencode on demand at task start;
# this script is for setting the host up ahead of time.

set -euo pipefail

DEST="${1:?usage: setup_remote_opencode_host.sh user@host [-i KEY] [-p PORT] [--ts-authkey KEY] [--managed [--managed-port N]]}"
shift || true

IDENTITY_ARGS=()
SSH_PORT=22
TS_AUTHKEY=""
MANAGED=0
MANAGED_PORT=4096
MANAGED_BIND=127.0.0.1

while [ $# -gt 0 ]; do
  case "$1" in
    -i) IDENTITY_ARGS+=(-i "$2"); shift 2 ;;
    -p) SSH_PORT="$2"; shift 2 ;;
    --ts-authkey) TS_AUTHKEY="$2"; shift 2 ;;
    --managed) MANAGED=1; shift ;;
    --managed-port) MANAGED_PORT="$2"; shift 2 ;;
    --managed-bind) MANAGED_BIND="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

SSH_OPTS=(-p "$SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

remote() {
  ssh "${SSH_OPTS[@]}" "${IDENTITY_ARGS[@]}" "$DEST" "$@"
}

echo "==> Checking SSH connectivity to $DEST ..."
remote 'echo ok' >/dev/null

echo "==> Installing opencode (bun if present, else curl installer) ..."
remote '
  set -e
  if command -v opencode >/dev/null 2>&1; then
    echo "opencode already at $(command -v opencode)"
  elif command -v bun >/dev/null 2>&1; then
    bun install -g opencode-ai
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL https://opencode.ai/install | bash
  else
    echo "ERROR: no bun and no curl on remote host" >&2
    exit 1
  fi
  BIN=$(command -v opencode || ls "$HOME"/.opencode/bin/opencode "$HOME"/.bun/bin/opencode 2>/dev/null | head -1)
  test -n "$BIN" || { echo "ERROR: opencode binary not found after install" >&2; exit 1; }
  echo "opencode binary: $BIN"
  "$BIN" --version || true
'

if [ -n "$TS_AUTHKEY" ]; then
  echo "==> Joining tailnet ..."
  remote "
    set -e
    if ! command -v tailscale >/dev/null 2>&1; then
      curl -fsSL https://tailscale.com/install.sh | sh
    fi
    sudo systemctl enable --now tailscaled 2>/dev/null || true
    sudo tailscale up --authkey='$TS_AUTHKEY' --hostname=\$(hostname) 2>/dev/null || \
      tailscale up --authkey='$TS_AUTHKEY' --hostname=\$(hostname)
    tailscale ip -4 | head -1
    tailscale status --self --json 2>/dev/null | grep -oE '\"[a-z0-9-]+\\.[a-z0-9.-]+\\.ts\\.net\"' | head -1 || true
  "
else
  echo "(skipping tailnet join, no --ts-authkey given)"
fi

if [ -n "$TS_AUTHKEY" ]; then
  echo "==> Joining tailnet ..."
  remote "
    set -e
    if ! command -v tailscale >/dev/null 2>&1; then
      curl -fsSL https://tailscale.com/install.sh | sh
    fi
    sudo systemctl enable --now tailscaled 2>/dev/null || true
    sudo tailscale up --authkey='$TS_AUTHKEY' --hostname=\$(hostname) 2>/dev/null || \
      tailscale up --authkey='$TS_AUTHKEY' --hostname=\$(hostname)
    tailscale ip -4 | head -1
    tailscale status --self --json 2>/dev/null | grep -oE '\"[a-z0-9-]+\\.[a-z0-9.-]+\\.ts\\.net\"' | head -1 || true
  "
else
  echo "(skipping tailnet join, no --ts-authkey given)"
fi

if [ "$MANAGED" -eq 1 ]; then
  echo "==> Installing managed opencode systemd user service (port $MANAGED_PORT, bind $MANAGED_BIND) ..."
  remote "
    set -e
    BIN=\$(command -v opencode || ls \"\$HOME\"/.opencode/bin/opencode \"\$HOME\"/.bun/bin/opencode 2>/dev/null | head -1)
    test -n \"\$BIN\" || { echo 'ERROR: opencode binary not found' >&2; exit 1; }
    mkdir -p \"\$HOME\"/.mojo \"\$HOME\"/.config/systemd/user
    PASSWORD=\$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
    umask 077 && printf 'OPENCODE_SERVER_PASSWORD=%s\n' \"\$PASSWORD\" > \"\$HOME\"/.mojo/server.env
    chmod 600 \"\$HOME\"/.mojo/server.env
    cat > \"\$HOME\"/.config/systemd/user/opencode-serve.service <<UNIT
[Unit]
Description=opencode server mode (managed by MoJoAssistant)
After=network-online.target

[Service]
Type=simple
EnvironmentFile=%h/.mojo/server.env
ExecStart=\$BIN serve --port $MANAGED_PORT --hostname $MANAGED_BIND
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now opencode-serve
    systemctl --user start opencode-serve 2>/dev/null || true
    loginctl enable-linger \"\$(whoami)\" 2>/dev/null || sudo loginctl enable-linger \"\$(whoami)\" 2>/dev/null || true
    sleep 2
    systemctl --user is-active opencode-serve
  "
  echo "==> Managed install complete. To read the remote password on the MoJo machine:"
  echo "    ssh ${DEST%:*}@${DEST#*:} 'cat ~/.mojo/server.env'   # OPENCODE_SERVER_PASSWORD=..."
fi

cat <<'EOF'

==> Done. Next steps on the MoJo machine:

1. Merge into ~/.memory/config/sandbox.json (see config/sandbox.ssh.example.json):
     "backends": { "ssh": { "host": "<tailscale-name-or-100.x-ip>", "user": "<user>", ... } }
2. Verify: ssh <user>@<host> 'command -v opencode && ss -ltn | head -1'
3. Schedule a task with config:
     {"sandbox_backend": "ssh", "working_dir": "~/projects/<your-project>"}
   MoJo will SSH in, spawn `opencode serve`, and drive it over the tailnet.

Managed mode (--managed) instead:
  1. Set "backends": { "ssh": { "host": "<tailscale-name-or-100.x-ip>", "user": "<user>",
       "use_managed": true, "managed_port": '"$MANAGED_PORT"' } }
  2. MoJo attaches to the always-on server; per-task sessions live on it.
  3. Optional: expose the same server to third-party MCP clients (Claude Desktop,
     Cursor, etc.) via the agent bridge:
       "backends": { "ssh": { ... "use_managed": true } }
       Hosts for ~/.memory/config/agent_bridge.json:
         { "hosts": { "<name>": { "base_url": "http://<tailscale-name>:'"$MANAGED_PORT"'",
                                   "password": "<OPENCODE_SERVER_PASSWORD from ~/.mojo/server.env>" } } }
     Then run: python -m app.mcp.agent_bridge  (Streamable HTTP on :8497)
EOF
