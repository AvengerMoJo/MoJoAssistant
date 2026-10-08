"""Endpoint liveness probe for LLM resources.

Deliberately dependency-free (stdlib only, no MoJoAssistant imports) so it can
move into the standalone resource-manager project unchanged.

Incident 2026-10-08: LM Studio's server was rebound from loopback to the
Tailscale address while every resource still pointed at localhost:8080. The
pool kept reporting the local models healthy until tasks failed on them, one
at a time, with no recorded reason. A probe turns "the endpoint answers or it
does not" into state the pool can act on before a task is assigned.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Optional

LIVE = "live"
UNREACHABLE = "unreachable"  # connection refused / timeout / DNS
AUTH_FAILED = "auth_failed"  # server answered 401/403: key missing or wrong
ERROR = "error"  # server answered, but not with a usable models listing


@dataclass
class ProbeResult:
    state: str
    detail: str
    checked_at: float
    latency_ms: Optional[int] = None
    # When the state last changed -- lets a maintainer tell a blip from an outage.
    since: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def probe_endpoint(base_url: str, api_key: str = "", timeout: float = 5.0) -> ProbeResult:
    """GET {base_url}/models and classify the answer. Never raises."""
    now = time.time()
    if not base_url:
        return ProbeResult(ERROR, "no base_url configured", now)

    url = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
            latency = int((time.monotonic() - started) * 1000)
            body = resp.read(1_000_000)
            try:
                json.loads(body)
            except ValueError:
                return ProbeResult(ERROR, f"{url} returned HTTP {resp.status} but not JSON", now, latency)
            return ProbeResult(LIVE, f"HTTP {resp.status}", now, latency)
    except urllib.error.HTTPError as e:
        latency = int((time.monotonic() - started) * 1000)
        if e.code in (401, 403):
            return ProbeResult(AUTH_FAILED, f"HTTP {e.code} from {url}", now, latency)
        if e.code == 429:
            # Quota is the rate-limit logic's concern; the endpoint itself is up.
            return ProbeResult(LIVE, "HTTP 429 (reachable, quota-limited)", now, latency)
        return ProbeResult(ERROR, f"HTTP {e.code} from {url}", now, latency)
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return ProbeResult(UNREACHABLE, f"{type(reason).__name__}: {reason}", now)
