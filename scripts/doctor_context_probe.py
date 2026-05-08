#!/usr/bin/env python3
"""
Generic context-limit discovery probe for LLM resources.

Usage examples:
  python3 scripts/doctor_context_probe.py --resource-id lmstudio_qwen36
  python3 scripts/doctor_context_probe.py --all-enabled-local

Writes results into ~/.memory/config/resource_pool_meta.json under:
  verified_context.<resource_id>
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


DEFAULT_LADDER = [1_000_000, 512_000, 262_000, 131_000, 65_000, 32_000]


def _memory_path() -> Path:
    return Path(os.getenv("MEMORY_PATH", str(Path.home() / ".memory")))


def _meta_file() -> Path:
    return _memory_path() / "config" / "resource_pool_meta.json"


def _load_meta() -> Dict[str, Any]:
    p = _meta_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_meta(data: Dict[str, Any]) -> None:
    p = _meta_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def _classify_fail(exc_or_http: str) -> str:
    s = (exc_or_http or "").lower()
    if "read timed out" in s:
        return "FAIL_READ_TIMEOUT"
    if "connect timeout" in s:
        return "FAIL_CONNECT_TIMEOUT"
    if "http 400" in s or "n_ctx" in s or "context length" in s:
        return "FAIL_HTTP_CONTEXT"
    if "http " in s:
        return "FAIL_HTTP"
    return "FAIL_OTHER"


def _probe_one(resource: Any, ladder: List[int], timeout: Tuple[int, int]) -> Dict[str, Any]:
    model = getattr(resource, "model", "") or ""
    base_url = (getattr(resource, "base_url", "") or "").rstrip("/")
    api_key = getattr(resource, "api_key", None)
    if not api_key:
        env_name = getattr(resource, "api_key_env", None)
        if env_name:
            api_key = os.getenv(env_name)

    url = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    results: List[Dict[str, Any]] = []
    max_passed = 0
    n_ctx_reported = None

    for approx_words in ladder:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return exactly OK."},
                {"role": "user", "content": ("t " * approx_words).strip()},
            ],
            "max_tokens": 4,
            "temperature": 0,
        }
        t0 = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            dt = round(time.time() - t0, 2)
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                max_passed = max(max_passed, prompt_tokens or approx_words)
                results.append(
                    {
                        "target_words": approx_words,
                        "status": "PASS",
                        "latency_s": dt,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "finish_reason": ((data.get("choices") or [{}])[0] or {}).get("finish_reason"),
                    }
                )
            else:
                body = (resp.text or "")[:400]
                status = _classify_fail(f"HTTP {resp.status_code} {body}")
                # Best effort parse n_ctx from known llama.cpp-style message.
                if "n_ctx:" in body:
                    try:
                        seg = body.split("n_ctx:", 1)[1]
                        n_ctx_reported = int("".join(ch for ch in seg if ch.isdigit())[:6] or "0") or None
                    except Exception:
                        pass
                results.append(
                    {
                        "target_words": approx_words,
                        "status": status,
                        "latency_s": dt,
                        "http_status": resp.status_code,
                        "error": body,
                    }
                )
        except Exception as e:
            dt = round(time.time() - t0, 2)
            results.append(
                {
                    "target_words": approx_words,
                    "status": _classify_fail(str(e)),
                    "latency_s": dt,
                    "error": str(e),
                }
            )

    return {
        "model": model,
        "max_passed_prompt_tokens": max_passed,
        "n_ctx_reported": n_ctx_reported,
        "timeout": {"connect_s": timeout[0], "read_s": timeout[1]},
        "ladder": ladder,
        "results": results,
        "tested_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-id", default=None)
    parser.add_argument("--all-enabled-local", action="store_true")
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--read-timeout", type=int, default=120)
    parser.add_argument("--ladder", default=",".join(str(v) for v in DEFAULT_LADDER))
    args = parser.parse_args()

    ladder = [int(x.strip()) for x in args.ladder.split(",") if x.strip()]
    timeout = (int(args.connect_timeout), int(args.read_timeout))

    from app.scheduler.resource_pool import ResourceManager

    rm = ResourceManager()
    resources = rm._resources

    targets: Dict[str, Any] = {}
    if args.resource_id:
        r = resources.get(args.resource_id)
        if not r:
            print(json.dumps({"status": "error", "message": f"Resource '{args.resource_id}' not found"}))
            return 2
        targets[args.resource_id] = r
    elif args.all_enabled_local:
        for rid, r in resources.items():
            if getattr(r, "enabled", False) and getattr(r, "type", "") == "local":
                targets[rid] = r
    else:
        print(json.dumps({"status": "error", "message": "Pass --resource-id or --all-enabled-local"}))
        return 2

    meta = _load_meta()
    vc = meta.setdefault("verified_context", {})
    out: Dict[str, Any] = {"status": "success", "probed": []}

    for rid, r in targets.items():
        result = _probe_one(r, ladder=ladder, timeout=timeout)
        vc[rid] = result
        out["probed"].append({"resource_id": rid, **result})

    _save_meta(meta)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

