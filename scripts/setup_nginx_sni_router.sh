#!/usr/bin/env bash
# Splits port 443 between existing real HTTPS vhosts and a new Xray/Reality
# VPN listener, using nginx's stream module + SNI sniffing (ssl_preread) --
# no TLS termination happens here, just blind byte-forwarding based on the
# ClientHello's SNI, so it's fully transparent to both sides.
#
# Existing vhosts (avengergear.com, ai.avengergear.com, pray.avengergear.com)
# move from `listen 443 ssl` to `listen 127.0.0.1:8443 ssl` -- nginx still
# terminates their TLS exactly as before, just on a loopback-only port that
# the new stream router forwards real traffic to. Anything whose SNI does
# NOT match one of those (e.g. a Reality client presenting a disguise SNI
# like www.microsoft.com) falls through to the `default` map entry, which
# goes to Xray on 127.0.0.1:11443 instead.
#
# Safe by construction: nginx -t is run before any reload, and every edited
# file is backed up first and restored automatically if the test fails --
# the live site is never left broken.
#
# Usage: sudo bash scripts/setup_nginx_sni_router.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Must run as root: sudo bash $0" >&2
  exit 1
fi

SITES_DIR=/etc/nginx/sites-available
NGINX_CONF=/etc/nginx/nginx.conf
STREAM_DIR=/etc/nginx/stream.d
BACKUP_DIR="/root/nginx-sni-router-backup-$(date +%Y%m%d-%H%M%S)"
XRAY_LOCAL_PORT=11443
NGINX_LOOPBACK_PORT=8443

mkdir -p "$BACKUP_DIR"
echo "==> Backing up nginx.conf and sites-available/ to $BACKUP_DIR"
cp "$NGINX_CONF" "$BACKUP_DIR/nginx.conf"
cp -r "$SITES_DIR" "$BACKUP_DIR/sites-available"

restore_and_exit() {
  echo "!! nginx -t failed -- restoring backups, nothing was reloaded." >&2
  cp "$BACKUP_DIR/nginx.conf" "$NGINX_CONF"
  rm -rf "$SITES_DIR"
  cp -r "$BACKUP_DIR/sites-available" "$SITES_DIR"
  rm -f "$STREAM_DIR"/reality-router.conf
  exit 1
}

echo "==> Discovering HTTPS vhosts (on plain 443, or already migrated to the loopback port by a prior run)"
mapfile -t VHOST_FILES < <(grep -lE "listen\s+(\[::\]:|\[::1\]:|127\.0\.0\.1:)?(443|$NGINX_LOOPBACK_PORT)\s+ssl" "$SITES_DIR"/* 2>/dev/null || true)
if [[ ${#VHOST_FILES[@]} -eq 0 ]]; then
  echo "No HTTPS vhosts found in $SITES_DIR -- nothing to move, aborting." >&2
  exit 1
fi

declare -A SNI_SEEN=()
declare -a SNIS=()
for f in "${VHOST_FILES[@]}"; do
  if grep -qE "listen\s+(\[::1\]:|127\.0\.0\.1:)$NGINX_LOOPBACK_PORT\s+ssl" "$f"; then
    echo "    $f already migrated to 127.0.0.1:$NGINX_LOOPBACK_PORT, leaving as-is"
  else
    echo "    moving $f: 443 -> 127.0.0.1:$NGINX_LOOPBACK_PORT"
  fi
  sed -i \
    -E "s/listen(\s+)\[::\](\s*):443(\s+ssl)([^;]*);/listen [::1]:$NGINX_LOOPBACK_PORT ssl;/" \
    "$f"
  sed -i \
    -E "s/listen(\s+)443(\s+ssl)([^;]*);/listen 127.0.0.1:$NGINX_LOOPBACK_PORT ssl;/" \
    "$f"
  # Collect every server_name in this file (deduplicated -- the same name
  # can legitimately appear in both the :80 and :443 server{} blocks, and
  # nginx's map{} directive rejects duplicate keys outright).
  while read -r name; do
    if [[ -n "$name" && "$name" != "_" && -z "${SNI_SEEN[$name]:-}" ]]; then
      SNIS+=("$name")
      SNI_SEEN[$name]=1
    fi
  done < <(grep -oP '(?<=server_name\s)[^;]+' "$f" | tr -d ';' | tr ' ' '\n')
done

if [[ ${#SNIS[@]} -eq 0 ]]; then
  echo "Could not find any server_name in the moved vhosts -- aborting before reload." >&2
  restore_and_exit
fi
echo "==> Real vhost SNIs found: ${SNIS[*]}"

echo "==> Ensuring nginx.conf includes $STREAM_DIR/*.conf at top level"
mkdir -p "$STREAM_DIR"
if ! grep -q "include $STREAM_DIR/\*.conf;" "$NGINX_CONF"; then
  # Insert right before the `http {` line -- stream{} must be a top-level
  # sibling of http{}, not nested inside it.
  sed -i "0,/^http {/s|^http {|include ${STREAM_DIR}/*.conf;\n\nhttp {|" "$NGINX_CONF"
fi

echo "==> Writing SNI router (stream {} block)"
{
  echo "stream {"
  echo "    map \$ssl_preread_server_name \$sni_backend {"
  for name in "${SNIS[@]}"; do
    echo "        $name    127.0.0.1:$NGINX_LOOPBACK_PORT;"
  done
  echo "        default    127.0.0.1:$XRAY_LOCAL_PORT;"
  echo "    }"
  echo ""
  echo "    server {"
  echo "        listen 443;"
  echo "        listen [::]:443;"
  echo "        proxy_pass \$sni_backend;"
  echo "        ssl_preread on;"
  echo "    }"
  echo "}"
} > "$STREAM_DIR/reality-router.conf"

echo "==> Testing nginx config before touching the live service"
if ! nginx -t; then
  restore_and_exit
fi

echo "==> Config OK -- reloading nginx"
systemctl reload nginx

echo ""
echo "=== Done ==="
echo "Real vhosts (${SNIS[*]}) now served via 127.0.0.1:$NGINX_LOOPBACK_PORT, unchanged from the outside."
echo "Anything else hitting :443 (including a Reality client's disguise SNI) forwards to 127.0.0.1:$XRAY_LOCAL_PORT."
echo "Next: run scripts/setup_xray_reality.sh to actually stand up Xray on that port."
echo "Backup kept at $BACKUP_DIR in case anything needs reverting by hand."
