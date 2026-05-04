#!/usr/bin/env bash
set -euo pipefail

# Correlate one request across MoJoAssistant + nginx logs.
# Usage:
#   scripts/correlate_request_trace.sh --request-id <id>
#   scripts/correlate_request_trace.sh --since "2026-05-03 13:58:00" --until "2026-05-03 14:05:00"

REQUEST_ID=""
SINCE="${SINCE:-1 hour ago}"
UNTIL="${UNTIL:-now}"
SERVICE="${SERVICE:-mojoassistant}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --request-id)
      REQUEST_ID="${2:-}"
      shift 2
      ;;
    --since)
      SINCE="${2:-}"
      shift 2
      ;;
    --until)
      UNTIL="${2:-}"
      shift 2
      ;;
    --service)
      SERVICE="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$REQUEST_ID" ]]; then
  echo "No --request-id provided. Showing time-window logs only."
fi

echo "== MoJoAssistant journal ($SERVICE) =="
if [[ -n "$REQUEST_ID" ]]; then
  journalctl --user -u "$SERVICE" --since "$SINCE" --until "$UNTIL" --no-pager | rg -n "$REQUEST_ID|access request_id=" || true
else
  journalctl --user -u "$SERVICE" --since "$SINCE" --until "$UNTIL" --no-pager | rg -n "access request_id=|POST /|502|503|504|upstream|error" || true
fi

for f in /var/log/nginx/mojo_access.log /var/log/nginx/mojo_error.log /var/log/nginx/access.log /var/log/nginx/error.log; do
  if [[ -f "$f" ]]; then
    echo
    echo "== nginx: $f =="
    if [[ -n "$REQUEST_ID" ]]; then
      rg -n "$REQUEST_ID|cf_ray=|upstream_status=| 502 | 503 | 504 " "$f" | tail -n 200 || true
    else
      tail -n 400 "$f" | rg -n "cf_ray=|upstream_status=| 502 | 503 | 504 " || true
    fi
  fi
done

echo
echo "Tip: compare timestamp + request_id + cf_ray across both sides."
