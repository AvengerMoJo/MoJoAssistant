# Request Tracing Runbook (Cloudflare -> Nginx -> MoJoAssistant)

## Goal
Provide deterministic tracing for intermittent `502/503/504` by correlating a single request across:
- Cloudflare edge events
- Nginx reverse proxy logs
- MoJoAssistant app logs

This runbook assumes request-ID propagation is enabled in MoJoAssistant HTTP adapter and nginx.

## Request ID Contract
- Client may send `X-Request-ID`.
- If absent, MoJoAssistant generates a UUID.
- MoJoAssistant returns `X-Request-ID` in response headers.
- Nginx should forward `X-Request-ID` upstream.

## Nginx Logging Contract
Use a log format that includes:
- `request_id`
- `cf_ray`
- `status`
- `upstream_status`
- `request_time`
- `upstream_response_time`
- client IP / `x-forwarded-for`

Reference snippet: [MCP_INTEGRATION_GUIDE.md](/home/alex/Development/Personal/MoJoAssistant/docs/claude-guide/MCP_INTEGRATION_GUIDE.md)

## App Logging Contract
MoJoAssistant HTTP middleware logs one structured access line per request with:
- `request_id`
- method/path/query
- status
- latency
- remote IP / forwarded IP
- Cloudflare headers when present (`cf-ray`, `cf-connecting-ip`)

Code location: [http.py](/home/alex/Development/Personal/MoJoAssistant/app/mcp/adapters/http.py)

## Quick Verification
1. Restart service:
```bash
systemctl --user restart mojoassistant
```

2. Send test request:
```bash
curl -i -H 'X-Request-ID: trace-smoke-001' http://127.0.0.1:8000/
```

3. Confirm response contains:
- `X-Request-ID: trace-smoke-001`

4. Correlate logs:
```bash
scripts/correlate_request_trace.sh --request-id trace-smoke-001
```

## Incident Triage (502)
1. Record exact timestamp and request ID.
2. Check Cloudflare events at that time:
- Firewall events
- Rate limiting
- Bot management actions
3. Correlate local logs:
```bash
scripts/correlate_request_trace.sh --request-id <REQUEST_ID>
```
4. Interpret:
- Cloudflare blocks/challenges and no local request: edge-side decision.
- Nginx has request with failing `upstream_status`: origin availability/readiness/restart window.
- App access line with 2xx/4xx but client saw 502: proxy path inconsistency.

## Known Operational Behavior
- Right after restart, MoJoAssistant can have a warmup window before it accepts traffic.
- During warmup, concurrent agent bursts can amplify transient upstream errors.

## Recommended Hardening
1. Add retry policy on MCP clients for `502/503/504` with short exponential backoff.
2. Add readiness gate to avoid routing traffic before app startup is complete.
3. Optionally add restart drain/lock to pause new agent dispatch during restart windows.
