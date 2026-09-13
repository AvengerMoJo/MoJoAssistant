#!/usr/bin/env bash
# Xray-core with VLESS + Reality -- the GFW-resistant fallback, one level
# up from OpenVPN. Reality makes the server's TLS handshake indistinguishable
# from a real connection to a legitimate site (DEST_DOMAIN below): anyone
# without the right key gets transparently proxied through to that real
# site, so active probing/DPI sees a perfectly normal HTTPS handshake.
#
# Must run AFTER scripts/setup_nginx_sni_router.sh, which frees up
# 127.0.0.1:11443 for this to bind to (nginx's stream{} block forwards any
# non-matching SNI on the public :443 socket there).
#
# Usage: sudo bash scripts/setup_xray_reality.sh
#   Optional env override: DEST_DOMAIN=www.microsoft.com (default)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Must run as root: sudo bash $0" >&2
  exit 1
fi

XRAY_BIN=/usr/local/bin/xray
XRAY_SHARE=/usr/local/share/xray
XRAY_CONF_DIR=/usr/local/etc/xray
XRAY_LOCAL_PORT=11443
DEST_DOMAIN="${DEST_DOMAIN:-www.microsoft.com}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-avengergear.com}"

echo "==> Disguise target (dest/SNI): $DEST_DOMAIN"
echo "==> Public domain clients will connect to: $PUBLIC_DOMAIN"

if [[ ! -x "$XRAY_BIN" ]]; then
  echo "==> Fetching latest Xray-core release"
  TMPDIR=$(mktemp -d)
  trap 'rm -rf "$TMPDIR"' EXIT
  TAG=$(curl -sS https://api.github.com/repos/XTLS/Xray-core/releases/latest | grep -oP '"tag_name":\s*"\K[^"]+')
  if [[ -z "$TAG" ]]; then
    echo "Could not resolve latest Xray-core release tag from GitHub API." >&2
    exit 1
  fi
  echo "    latest release: $TAG"
  URL="https://github.com/XTLS/Xray-core/releases/download/${TAG}/Xray-linux-64.zip"
  curl -sSL -o "$TMPDIR/xray.zip" "$URL"
  mkdir -p "$XRAY_SHARE"
  unzip -oq "$TMPDIR/xray.zip" -d "$XRAY_SHARE"
  install -m 755 "$XRAY_SHARE/xray" "$XRAY_BIN"
  echo "    installed to $XRAY_BIN"
else
  echo "==> Xray already installed at $XRAY_BIN, reusing"
fi

mkdir -p "$XRAY_CONF_DIR"

if [[ -f "$XRAY_CONF_DIR/config.json" ]]; then
  echo "==> $XRAY_CONF_DIR/config.json already exists -- reusing existing keys/UUID unchanged"
  UUID=$(grep -oP '"id":\s*"\K[^"]+' "$XRAY_CONF_DIR/config.json" | head -1)
  PRIVATE_KEY=$(grep -oP '"privateKey":\s*"\K[^"]+' "$XRAY_CONF_DIR/config.json" | head -1)
  SHORT_ID=$(grep -oP '"shortIds":\s*\[\s*"\K[^"]+' "$XRAY_CONF_DIR/config.json" | head -1)
  # Public key isn't stored server-side (only derivable from the private
  # key), so recompute it the same way we did on first generation.
  PUBLIC_KEY=$("$XRAY_BIN" x25519 -i "$PRIVATE_KEY" | grep -oP '(Public key:|PublicKey:|Password \(PublicKey\):|Password:)\s*\K\S+' || true)
else
  echo "==> Generating Reality keypair, UUID, short ID"
  KEYGEN_OUT=$("$XRAY_BIN" x25519)
  PRIVATE_KEY=$(echo "$KEYGEN_OUT" | grep -oP '(Private key:|PrivateKey:)\s*\K\S+')
  PUBLIC_KEY=$(echo "$KEYGEN_OUT" | grep -oP '(Public key:|PublicKey:|Password \(PublicKey\):|Password:)\s*\K\S+')
  UUID=$("$XRAY_BIN" uuid)
  SHORT_ID=$(openssl rand -hex 8)

  cat > "$XRAY_CONF_DIR/config.json" <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "listen": "127.0.0.1",
      "port": $XRAY_LOCAL_PORT,
      "protocol": "vless",
      "settings": {
        "clients": [ { "id": "$UUID", "flow": "xtls-rprx-vision" } ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "$DEST_DOMAIN:443",
          "xver": 0,
          "serverNames": [ "$DEST_DOMAIN" ],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": [ "$SHORT_ID" ]
        }
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" }
  ]
}
EOF
fi

for var_name in UUID PRIVATE_KEY PUBLIC_KEY SHORT_ID; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Failed to determine $var_name (xray's x25519/uuid output format may have" >&2
    echo "changed) -- run '$XRAY_BIN x25519' and '$XRAY_BIN uuid' by hand and check" >&2
    echo "the label text this script's grep patterns expect." >&2
    exit 1
  fi
done

echo "==> Writing systemd unit"
cat > /etc/systemd/system/xray.service <<EOF
[Unit]
Description=Xray Service (VLESS + Reality)
After=network.target nss-lookup.target

[Service]
User=nobody
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=$XRAY_BIN run -config $XRAY_CONF_DIR/config.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now xray.service

echo "==> Waiting for xray to come up"
sleep 2
systemctl --no-pager status xray.service | head -6

VLESS_URI="vless://${UUID}@${PUBLIC_DOMAIN}:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${DEST_DOMAIN}&fp=chrome&pbk=${PUBLIC_KEY}&sid=${SHORT_ID}&type=tcp&headerType=none#avengergear-reality"

echo ""
echo "=== Done ==="
echo "Xray listening on 127.0.0.1:$XRAY_LOCAL_PORT, reached via nginx's stream router on public :443."
echo ""
echo "Client import URI (paste into v2rayN/v2rayNG, Shadowrocket, Stash, NekoBox, V2Box, etc.):"
echo ""
echo "$VLESS_URI"
echo ""
echo "$VLESS_URI" > "$XRAY_CONF_DIR/client-uri.txt"
chmod 600 "$XRAY_CONF_DIR/client-uri.txt"
echo "(also saved to $XRAY_CONF_DIR/client-uri.txt, root-readable only)"
