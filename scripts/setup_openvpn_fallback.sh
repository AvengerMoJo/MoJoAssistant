#!/usr/bin/env bash
# OpenVPN fallback VPN — independent of Tailscale, for use when Tailscale's
# control-plane/DERP traffic is throttled or blocked (e.g. from mainland
# China). Personal host infra, same category as scripts/install_headscale.sh
# — not part of the MoJoAssistant application, no NetworkProvider wiring.
#
# Runs on UDP/443 deliberately: TCP/443 is already taken by nginx on this
# host, but UDP/443 is a separate socket and is free. Using 443 instead of
# OpenVPN's default 1194 survives simple port-based firewalls; it does NOT
# guarantee DPI evasion — OpenVPN's handshake is fingerprintable regardless
# of port. If this gets blocked too, the next step is an obfuscated proxy
# (Xray/VLESS+Reality), not a port change here.
#
# Usage: sudo bash scripts/setup_openvpn_fallback.sh [client-name ...]
#   Defaults to two clients: mac-laptop phone
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Must run as root: sudo bash $0" >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  CLIENTS=("$@")
else
  CLIENTS=(mac-laptop phone)
fi

REAL_USER="${SUDO_USER:-alex}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
OUT_DIR="$REAL_HOME/.local/share/openvpn-clients"
WAN_IF=$(ip route show default | awk '{print $5; exit}')
PUBLIC_IP=$(curl -sS -4 --max-time 5 https://ifconfig.me || true)
EASYRSA_DIR=/etc/openvpn/easy-rsa
SERVER_DIR=/etc/openvpn/server
VPN_SUBNET="10.9.0.0"
VPN_NETMASK="255.255.255.0"
VPN_PORT="${VPN_PORT:-443}"
VPN_PROTO="${VPN_PROTO:-udp}"

echo "==> WAN interface: $WAN_IF"
echo "==> Detected public IP: ${PUBLIC_IP:-<unknown, fill in manually later>}"
echo "==> Clients to generate: ${CLIENTS[*]}"

echo "==> Installing easy-rsa and openvpn if missing"
if ! command -v easyrsa >/dev/null 2>&1 && [[ ! -d /usr/share/easy-rsa ]]; then
  if command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive refresh
    zypper --non-interactive install easy-rsa openvpn
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y easy-rsa openvpn
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y easy-rsa openvpn
  else
    echo "No known package manager (zypper/apt-get/dnf) found -- install easy-rsa and openvpn manually, then re-run." >&2
    exit 1
  fi
fi

# Resolve the easyrsa binary's actual location -- differs by distro/package:
#   openSUSE (zypper):  /usr/bin/easyrsa            (already on PATH)
#   Debian/Ubuntu (apt): /usr/share/easy-rsa/easyrsa (not on PATH)
if command -v easyrsa >/dev/null 2>&1; then
  EASYRSA_BIN=$(command -v easyrsa)
elif [[ -x /usr/share/easy-rsa/easyrsa ]]; then
  EASYRSA_BIN=/usr/share/easy-rsa/easyrsa
elif [[ -x /usr/share/easy-rsa/3/easyrsa ]]; then
  EASYRSA_BIN=/usr/share/easy-rsa/3/easyrsa
else
  echo "Could not find the easyrsa binary after install -- check your distro's easy-rsa package layout." >&2
  exit 1
fi
echo "    using easyrsa at $EASYRSA_BIN"

# The user/group OpenVPN drops privileges to also differs by distro:
#   Debian/Ubuntu: nobody:nogroup
#   openSUSE/RHEL: nobody:nobody
UNPRIV_USER=nobody
UNPRIV_GROUP=$(id -gn nobody 2>/dev/null || echo nogroup)

echo "==> Building PKI (EC keys — fast, no DH-param wait)"
mkdir -p "$EASYRSA_DIR"
if [[ ! -f "$EASYRSA_DIR/pki/ca.crt" ]]; then
  # Run from inside EASYRSA_DIR, same as every other easyrsa call below --
  # --pki-dir alone isn't reliably honored across easyrsa versions when
  # invoked from an unrelated cwd (seen live on openSUSE's easyrsa 3.2.2:
  # it silently created ./pki under the caller's cwd instead).
  ( cd "$EASYRSA_DIR" && EASYRSA_PKI="$EASYRSA_DIR/pki" "$EASYRSA_BIN" init-pki )
  if [[ ! -d "$EASYRSA_DIR/pki" ]]; then
    echo "init-pki did not create $EASYRSA_DIR/pki -- aborting." >&2
    exit 1
  fi
  cat > "$EASYRSA_DIR/vars" <<'EOF'
set_var EASYRSA_ALGO ec
set_var EASYRSA_CURVE secp384r1
set_var EASYRSA_CA_EXPIRE 3650
set_var EASYRSA_CERT_EXPIRE 825
set_var EASYRSA_BATCH yes
EOF
  ( cd "$EASYRSA_DIR" && EASYRSA_PKI="$EASYRSA_DIR/pki" "$EASYRSA_BIN" build-ca nopass )
  ( cd "$EASYRSA_DIR" && EASYRSA_PKI="$EASYRSA_DIR/pki" "$EASYRSA_BIN" build-server-full server nopass )
else
  echo "    PKI already exists, reusing CA/server cert"
fi

for name in "${CLIENTS[@]}"; do
  if [[ ! -f "$EASYRSA_DIR/pki/issued/$name.crt" ]]; then
    echo "==> Issuing client cert: $name"
    ( cd "$EASYRSA_DIR" && EASYRSA_PKI="$EASYRSA_DIR/pki" "$EASYRSA_BIN" build-client-full "$name" nopass )
  else
    echo "==> Client cert already exists: $name (reusing)"
  fi
done

mkdir -p "$SERVER_DIR"
if [[ ! -f "$SERVER_DIR/tc.key" ]]; then
  echo "==> Generating tls-crypt key"
  openvpn --genkey secret "$SERVER_DIR/tc.key"
fi

cp "$EASYRSA_DIR/pki/ca.crt" "$SERVER_DIR/ca.crt"
cp "$EASYRSA_DIR/pki/issued/server.crt" "$SERVER_DIR/server.crt"
cp "$EASYRSA_DIR/pki/private/server.key" "$SERVER_DIR/server.key"
chmod 600 "$SERVER_DIR/server.key" "$SERVER_DIR/tc.key"

echo "==> Writing server config"
cat > "$SERVER_DIR/server.conf" <<EOF
port $VPN_PORT
proto $VPN_PROTO
dev tun

ca $SERVER_DIR/ca.crt
cert $SERVER_DIR/server.crt
key $SERVER_DIR/server.key
tls-crypt $SERVER_DIR/tc.key

topology subnet
server $VPN_SUBNET $VPN_NETMASK

# Route ALL client internet traffic through this VPN (the whole point of
# a China fallback) and hand out non-leaking DNS.
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 1.0.0.1"

keepalive 10 120
cipher AES-256-GCM
data-ciphers AES-256-GCM
persist-key
persist-tun

user $UNPRIV_USER
group $UNPRIV_GROUP

status /var/log/openvpn-status.log
log-append /var/log/openvpn.log
verb 3
explicit-exit-notify 1
EOF

echo "==> Enabling IP forwarding (idempotent, shared with the Tailscale exit-node setup)"
sysctl -w net.ipv4.ip_forward=1 >/dev/null
if [[ ! -f /etc/sysctl.d/99-tailscale.conf ]]; then
  echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-openvpn.conf
fi

# openSUSE (and RHEL-family) typically run firewalld, which owns its own
# nftables backend and can silently drop/override raw `iptables -A` rules
# on its next reload -- so NAT/forwarding must go through firewall-cmd
# there instead of being added directly.
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  echo "==> firewalld detected -- adding masquerade + forwarding via firewall-cmd"
  ZONE=$(firewall-cmd --get-default-zone)
  firewall-cmd --zone="$ZONE" --add-masquerade --permanent
  firewall-cmd --zone="$ZONE" --add-port="$VPN_PORT/$VPN_PROTO" --permanent
  # tun0 goes in the trusted zone, not the (usually restrictive) default
  # WAN zone -- otherwise the default zone's policy can silently block
  # forwarded VPN client traffic even though the server itself comes up.
  firewall-cmd --zone=trusted --add-interface=tun0 --permanent 2>/dev/null || true
  firewall-cmd --reload
else
  echo "==> Adding NAT (MASQUERADE) rule for $VPN_SUBNET/24 out $WAN_IF"
  if ! iptables -t nat -C POSTROUTING -s "$VPN_SUBNET/24" -o "$WAN_IF" -j MASQUERADE 2>/dev/null; then
    iptables -t nat -A POSTROUTING -s "$VPN_SUBNET/24" -o "$WAN_IF" -j MASQUERADE
  fi
  if ! iptables -C FORWARD -s "$VPN_SUBNET/24" -j ACCEPT 2>/dev/null; then
    iptables -A FORWARD -s "$VPN_SUBNET/24" -j ACCEPT
  fi
  if ! iptables -C FORWARD -d "$VPN_SUBNET/24" -j ACCEPT 2>/dev/null; then
    iptables -A FORWARD -d "$VPN_SUBNET/24" -j ACCEPT
  fi

  echo "==> Persisting NAT rules across reboot (systemd oneshot, idempotent)"
  cat > /etc/systemd/system/openvpn-nat.service <<EOF
[Unit]
Description=OpenVPN NAT rules (fallback VPN subnet)
After=network-online.target
Wants=network-online.target
Before=openvpn-server@server.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'iptables -t nat -C POSTROUTING -s $VPN_SUBNET/24 -o $WAN_IF -j MASQUERADE || iptables -t nat -A POSTROUTING -s $VPN_SUBNET/24 -o $WAN_IF -j MASQUERADE'
ExecStart=/bin/sh -c 'iptables -C FORWARD -s $VPN_SUBNET/24 -j ACCEPT || iptables -A FORWARD -s $VPN_SUBNET/24 -j ACCEPT'
ExecStart=/bin/sh -c 'iptables -C FORWARD -d $VPN_SUBNET/24 -j ACCEPT || iptables -A FORWARD -d $VPN_SUBNET/24 -j ACCEPT'

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now openvpn-nat.service
fi

systemctl daemon-reload
systemctl enable --now openvpn-server@server.service

echo "==> Waiting for openvpn-server@server to come up"
sleep 2
systemctl --no-pager status openvpn-server@server.service | head -6

echo "==> Generating client .ovpn files (inline certs, single file, drag-and-drop import)"
mkdir -p "$OUT_DIR"
for name in "${CLIENTS[@]}"; do
  OVPN="$OUT_DIR/$name.ovpn"
  cat > "$OVPN" <<EOF
client
dev tun
proto $VPN_PROTO
remote ${PUBLIC_IP:-REPLACE_WITH_PUBLIC_IP} $VPN_PORT
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
data-ciphers AES-256-GCM
verb 3

<ca>
$(cat "$EASYRSA_DIR/pki/ca.crt")
</ca>
<cert>
$(sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' "$EASYRSA_DIR/pki/issued/$name.crt")
</cert>
<key>
$(cat "$EASYRSA_DIR/pki/private/$name.key")
</key>
<tls-crypt>
$(cat "$SERVER_DIR/tc.key")
</tls-crypt>
EOF
  chown "$REAL_USER:$REAL_USER" "$OVPN"
  chmod 600 "$OVPN"
  echo "    wrote $OVPN"
done
chown -R "$REAL_USER:$REAL_USER" "$OUT_DIR"

echo ""
echo "=== Done ==="
echo "Server listening on $VPN_PROTO/$VPN_PORT, subnet $VPN_SUBNET/24"
echo "Client configs: $OUT_DIR/"
echo ""
echo "If external $VPN_PROTO/$VPN_PORT isn't already forwarded to this machine's LAN IP"
echo "($(hostname -I | awk '{print $1}')), that's the one remaining step I can't do remotely"
echo "-- router admin page. Public IP baked into the configs: ${PUBLIC_IP:-<fill in manually>}"
