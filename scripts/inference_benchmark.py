#!/usr/bin/env python3
"""Standalone LLM inference benchmark against an OpenAI-compatible endpoint.

Measures streaming decode performance (tokens/sec from streaming timing,
first-token latency) on a fixed short and long prompt, and can optionally
snapshot GPU/RAM counters on the evo-x3 host via an opencode session.

Examples:
    python scripts/inference_benchmark.py \
        --url http://100.65.157.37:1234/v1/chat/completions --model glm-4-9b
    python scripts/inference_benchmark.py --url ... --model ... --measure-memory
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

REQUEST_TIMEOUT = 120
BRIDGE_CONFIG = Path.home() / ".memory" / "config" / "agent_bridge.json"
MEMORY_HOST = "evo-x3"

_SHORT_PROMPT = "Explain what a token is in an LLM, in two sentences."

_LONG_BASE = (
    "A distributed inference cluster schedules requests across heterogeneous "
    "workers, each with its own model replica and KV cache. Fairness matters "
    "because long prompts monopolize precompute, starving short interactive "
    "requests, while continuous batching lets newly arrived requests join "
    "running batches without draining them first. "
)
_LONG_PROMPT = (
    "Read the following context carefully, then summarize it in one sentence.\n\n"
    + _LONG_BASE * 6
)

SHORT_MAX_TOKENS = 128
LONG_MAX_TOKENS = 256

MEMORY_PS_SCRIPT = r"""
Write-Host '--- System memory ---'
try {
    $os = Get-CimInstance Win32_OperatingSystem
    "TotalVisibleMemoryGB={0:N1} FreePhysicalMemoryGB={1:N1}" -f ($os.TotalVisibleMemorySize/1MB), ($os.FreePhysicalMemory/1MB)
    $ctr = Get-Counter '\Memory\Committed Bytes','\Memory\Available MBytes' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
    $ctr.CounterSamples | ForEach-Object { "{0} = {1:N0}" -f $_.Path, $_.CookedValue }
} catch { Write-Host "System memory counters NOT AVAILABLE: $($_.Exception.Message)" }

Write-Host '--- GPU process memory (WDDM/DirectML path) ---'
try {
    $g = Get-Counter '\GPU Process Memory(*)\Dedicated Usage','\GPU Process Memory(*)\Shared Usage' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
    $g.CounterSamples | Where-Object { $_.CookedValue -gt 0 } | Sort-Object CookedValue -Descending |
        ForEach-Object { "{0} = {1:N1} MB" -f $_.InstanceName, ($_.CookedValue/1MB) }
    if (-not ($g.CounterSamples | Where-Object { $_.CookedValue -gt 0 })) { Write-Host 'GPU process memory: no nonzero samples' }
} catch { Write-Host "GPU/DirectML VRAM counters NOT AVAILABLE on this host: $($_.Exception.Message)" }
"""

MEMORY_PROMPT = (
    "You are on Windows 11. Run the following PowerShell script EXACTLY as written "
    "and return its raw output verbatim, including any NOT AVAILABLE lines. "
    "Do not summarize or omit anything:\n```powershell\n" + MEMORY_PS_SCRIPT + "\n```\n"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Streaming benchmark
# ---------------------------------------------------------------------------

def stream_benchmark(
    url: str, model: str, prompt: str, max_tokens: int
) -> dict[str, Any]:
    """Stream one completion and time first token + steady decode rate.

    tok/s is computed from the interval between the first and last streamed
    tokens (generation time), not total wall-clock, so prompt processing and
    TTFT are excluded from the decode-rate figure.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream_options": {"include_usage": True},
    }

    t0 = time.perf_counter()
    try:
        resp = requests.post(url, json=payload, stream=True, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        fail(f"Request to {url} timed out after {REQUEST_TIMEOUT}s")
    except requests.exceptions.ConnectionError as exc:
        fail(f"Cannot reach {url}: {exc}")

    if resp.status_code == 400 and "stream_options" in resp.text:
        payload.pop("stream_options")
        resp = requests.post(url, json=payload, stream=True, timeout=REQUEST_TIMEOUT)

    if resp.status_code != 200:
        body = resp.text[:300]
        hint = ""
        if resp.status_code in (400, 404) and "model" in body.lower():
            hint = f" (model name '{model}' likely invalid for this endpoint)"
        fail(f"{url} returned HTTP {resp.status_code}{hint}: {body}")

    t0 = time.perf_counter()
    first_ts: float | None = None
    last_ts: float | None = None
    chunk_tokens = 0
    usage_tokens: int | None = None
    prompt_tokens: int | None = None
    text_parts: list[str] = []

    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if data.get("usage"):
                usage_tokens = data["usage"].get("completion_tokens", usage_tokens)
                prompt_tokens = data["usage"].get("prompt_tokens", prompt_tokens)
            delta = ""
            choices = data.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content") or ""
            if delta:
                now = time.perf_counter()
                if first_ts is None:
                    first_ts = now
                last_ts = now
                chunk_tokens += 1
                text_parts.append(delta)
    except requests.exceptions.RequestException as exc:
        fail(f"Stream interrupted mid-response: {exc}")

    if first_ts is None:
        fail("Server returned 200 but no streamed tokens arrived (empty response)")

    wall_s = time.perf_counter() - t0
    ttft_ms = (first_ts - t0) * 1000
    gen_s = (last_ts - first_ts) if last_ts and last_ts > first_ts else 0.0

    if usage_tokens is not None and usage_tokens > 1:
        tokens, token_source = usage_tokens, "usage"
    else:
        tokens, token_source = chunk_tokens, "chunk-count(approx)"
    tps = (tokens - 1) / gen_s if gen_s > 0 and tokens > 1 else 0.0

    return {
        "ttft_ms": ttft_ms,
        "gen_s": gen_s,
        "wall_s": wall_s,
        "tokens": tokens,
        "token_source": token_source,
        "tok_s": tps,
        "prompt_tokens": prompt_tokens,
        "text": "".join(text_parts),
    }


def print_result(label: str, r: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    ptok = f"{r['prompt_tokens']}" if r["prompt_tokens"] is not None else "n/a"
    print(
        f"first-token latency : {r['ttft_ms']:8.1f} ms\n"
        f"generation time     : {r['gen_s']:8.2f} s\n"
        f"completion tokens   : {r['tokens']:8d}   (source: {r['token_source']})\n"
        f"prompt tokens       : {ptok:>8}\n"
        f"decode rate         : {r['tok_s']:8.1f} tok/s   (first→last token interval)\n"
        f"wall clock          : {r['wall_s']:8.2f} s"
    )
    print("--- raw response text ---")
    print(r["text"])


# ---------------------------------------------------------------------------
# Remote memory sampling via opencode session on evo-x3
# ---------------------------------------------------------------------------

def load_bridge_host() -> tuple[str, str]:
    try:
        config = json.loads(BRIDGE_CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"Config file not found: {BRIDGE_CONFIG} (needed for --measure-memory)")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read {BRIDGE_CONFIG}: {exc}")
    host = (config.get("hosts") or {}).get(MEMORY_HOST) or {}
    base_url, password = host.get("base_url"), host.get("password")
    if not base_url or not password:
        fail(f"Host '{MEMORY_HOST}' missing base_url/password in {BRIDGE_CONFIG}")
    return base_url.rstrip("/"), password


def extract_reply(payload: dict[str, Any]) -> str:
    parts = payload.get("parts") or []
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(t for t in texts if t)


def run_remote_memory_check(phase: str) -> None:
    """Send a PowerShell counter-sampling prompt to an opencode session on evo-x3.

    DirectML/AMD often exposes no reliable per-process VRAM counter; the remote
    script prints explicit NOT AVAILABLE lines rather than fabricated numbers,
    and we pass them through unedited.
    """
    base_url, password = load_bridge_host()
    auth = ("opencode", password)
    try:
        resp = requests.post(f"{base_url}/session", json={}, auth=auth, timeout=30)
        resp.raise_for_status()
        session_id = (resp.json().get("info") or {}).get("id")
        if not session_id:
            fail(f"Unexpected /session response from {base_url}: no info.id")
        print(f"[memory:{phase}] opencode session {session_id} on {MEMORY_HOST}")
        msg = requests.post(
            f"{base_url}/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": MEMORY_PROMPT}]},
            auth=auth,
            timeout=300,
        )
        msg.raise_for_status()
        reply = extract_reply(msg.json())
        if not reply:
            msgs = requests.get(
                f"{base_url}/session/{session_id}/message", auth=auth, timeout=30
            )
            for m in reversed(msgs.json()):
                if (m.get("info") or {}).get("role") == "assistant":
                    reply = extract_reply(m)
                    if reply:
                        break
        print(f"\n--- memory counters ({phase} benchmark) ---")
        print(reply or "NO REPLY from opencode session (cannot report memory)")
        requests.delete(f"{base_url}/session/{session_id}", auth=auth, timeout=30)
    except requests.exceptions.ConnectionError as exc:
        fail(f"--measure-memory: cannot reach opencode host {base_url}: {exc}")
    except requests.exceptions.RequestException as exc:
        fail(f"--measure-memory: opencode session call failed: {exc}")


# ---------------------------------------------------------------------------
# MTP check stub
# ---------------------------------------------------------------------------
# How MTP (Multi-Token Prediction) engagement would ACTUALLY be confirmed for
# real runs, rather than assumed from high tok/s numbers:
#
#   1. Server-side logs are the only authoritative source. llama.cpp/LM Studio
#      builds with MTP support log per-step accepted-token counts (e.g.
#      "mtp accepted N/M" lines); vLLM logs spec-decode accept-rate stats
#      (" acceptance_rate=..."). Without access to those logs we cannot
#      distinguish MTP-accelerated decode from an unusually fast single-token
#      decode loop.
#   2. A client-side signature is possible but weaker: with MTP engaged, each
#      SSE chunk typically carries >1 token, so chunks-per-second * tokens-per-
#      chunk exceeds the model's known single-token decode ceiling, and TTFT
#      for identical prompts drops measurably. Comparing usage.completion_tokens
#      against the number of received chunks gives a per-chunk token ratio; a
#      stable ratio > 1.0 is suggestive, not proof (token buffering in the
#      server can fake the same signature).
#   3. A/B against a known non-MTP server build with identical prompt, quant,
#      and context length is the practical fallback when logs are unavailable.
#
# This stub does none of the above; it only records that verification was
# requested, because the benchmark target here exposes no server-side logs.


def report_mtp_stub() -> None:
    print(
        "\n[MTP] Verification requested but NOT performed: confirming MTP "
        "engagement requires server-side logs (per-step accepted-token counts "
        "or spec-decode acceptance-rate stats), which this endpoint does not "
        "expose. See the comment block above report_mtp_stub() in this file "
        "for the full verification procedure."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark LLM inference (streaming TTFT + decode tok/s) "
        "against an OpenAI-compatible endpoint."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="OpenAI-compatible chat/completions URL "
        "(e.g. http://localhost:1234/v1/chat/completions)",
    )
    parser.add_argument(
        "--model", required=True, help="model name to benchmark"
    )
    parser.add_argument(
        "--measure-memory",
        action="store_true",
        help="sample GPU/RAM counters on evo-x3 via opencode session, "
        "before and after the benchmark",
    )
    parser.add_argument(
        "--check-mtp",
        action="store_true",
        help="stub: prints why MTP engagement cannot be confirmed from the "
        "client side (server-side logs required)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = args.url.rstrip("/")

    if args.measure_memory:
        run_remote_memory_check("before")

    if args.check_mtp:
        report_mtp_stub()

    short = stream_benchmark(url, args.model, _SHORT_PROMPT, SHORT_MAX_TOKENS)
    print_result(f"short prompt (~50 tok ctx), max_tokens={SHORT_MAX_TOKENS}", short)

    long = stream_benchmark(url, args.model, _LONG_PROMPT, LONG_MAX_TOKENS)
    print_result(f"long prompt (~300-400 tok ctx), max_tokens={LONG_MAX_TOKENS}", long)

    print("\n=== summary ===")
    print(f"{'prompt':<8} {'ttft_ms':>9} {'tok/s':>8} {'tokens':>7} {'source':<20}")
    for label, r in (("short", short), ("long", long)):
        print(
            f"{label:<8} {r['ttft_ms']:>9.1f} {r['tok_s']:>8.1f} "
            f"{r['tokens']:>7d} {r['token_source']:<20}"
        )

    if args.measure_memory:
        run_remote_memory_check("after")


if __name__ == "__main__":
    main()
