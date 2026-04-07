#!/usr/bin/env python3
"""
Direct repro for LM Studio / Gemma 4 duplicate identical tool_calls.

This script calls the raw OpenAI-compatible /v1/chat/completions endpoint and
prints whether the assistant returned repeated identical tool calls in a single
message. It bypasses MoJo's executor dedup layer on purpose.

Example:
  python3 scripts/repro_lmstudio_duplicate_tool_calls.py \
    --model google/gemma-4-27b-it \
    --base-url http://localhost:1234/v1 \
    --runs 3

Expected bug shape when present:
  - assistant message contains tool_calls array
  - same (function.name, function.arguments) repeated many times
  - only tool_call.id differs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "google/gemma-4-27b-it")
DEFAULT_API_KEY = os.environ.get("LMSTUDIO_API_KEY", "")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash_exec",
            "description": "Execute a single shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
    }
]


def _build_payload(model: str, command: str, parallel_tool_calls: bool, tool_choice: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 300,
        "parallel_tool_calls": parallel_tool_calls,
        "tool_choice": tool_choice,
        "tools": TOOLS,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are testing tool calling. "
                    "Call the provided tool exactly once. "
                    "Do not explain. Do not plan. "
                    "Return one tool call only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f'Use bash_exec exactly once with command: "{command}". '
                    "Do not produce more than one tool call."
                ),
            },
        ],
    }


def _post_json(url: str, payload: dict[str, Any], timeout: int, api_key: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tool_signature(tc: dict[str, Any]) -> tuple[str, str]:
    fn = tc.get("function") or {}
    return (fn.get("name", ""), fn.get("arguments", ""))


def _analyze_tool_calls(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    counter = Counter(_tool_signature(tc) for tc in tool_calls)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for tc in tool_calls:
        groups[_tool_signature(tc)].append(tc.get("id", ""))

    duplicates = [
        {
            "function_name": sig[0],
            "arguments": sig[1],
            "count": count,
            "ids": groups[sig][:10],
        }
        for sig, count in counter.items()
        if count > 1
    ]
    duplicates.sort(key=lambda x: x["count"], reverse=True)

    return {
        "tool_call_count": len(tool_calls),
        "unique_signatures": len(counter),
        "has_duplicate_identical_calls": bool(duplicates),
        "duplicate_groups": duplicates,
    }


def _extract_message(data: dict[str, Any]) -> dict[str, Any]:
    try:
        return data["choices"][0]["message"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected response shape: {exc}; keys={list(data.keys())}") from exc


def run_once(base_url: str, model: str, timeout: int, run_index: int, parallel_tool_calls: bool, api_key: str = "", tool_choice: str = "required") -> dict[str, Any]:
    command = f"printf gemma_dup_probe_run_{run_index}"
    payload = _build_payload(model=model, command=command, parallel_tool_calls=parallel_tool_calls, tool_choice=tool_choice)
    data = _post_json(f"{base_url.rstrip('/')}/chat/completions", payload, timeout=timeout, api_key=api_key)
    message = _extract_message(data)
    tool_calls = message.get("tool_calls") or []
    analysis = _analyze_tool_calls(tool_calls)
    return {
        "payload_command": command,
        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
        "content": message.get("content"),
        "analysis": analysis,
        "raw_response": data,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce duplicate identical tool_calls from LM Studio Gemma 4.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL, e.g. http://localhost:1234/v1")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name loaded in LM Studio")
    parser.add_argument("--runs", type=int, default=3, help="How many independent calls to make")
    parser.add_argument("--timeout", type=int, default=90, help="Per-request timeout seconds")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Bearer token for LM Studio if auth is enabled")
    parser.add_argument("--tool-choice", choices=("auto", "required", "none"), default="required", help="tool_choice value to send")
    parser.add_argument("--parallel-tool-calls", choices=("false", "true"), default="false", help="Value to send in payload")
    parser.add_argument("--save-dir", default="/tmp/gemma4_toolcall_repro", help="Directory to save raw JSON responses")
    args = parser.parse_args()

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    parallel_tool_calls = args.parallel_tool_calls == "true"

    print(f"Base URL: {args.base_url}")
    print(f"Model: {args.model}")
    print(f"parallel_tool_calls: {parallel_tool_calls}")
    print(f"Runs: {args.runs}")
    print()

    any_duplicate_bug = False

    for i in range(1, args.runs + 1):
        print(f"=== Run {i} ===")
        started = time.time()
        try:
            result = run_once(
                base_url=args.base_url,
                model=args.model,
                timeout=args.timeout,
                run_index=i,
                parallel_tool_calls=parallel_tool_calls,
                api_key=args.api_key,
                tool_choice=args.tool_choice,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"HTTP {exc.code}: {body}")
            return 1
        except Exception as exc:
            print(f"Request failed: {exc}")
            return 1

        elapsed = time.time() - started
        analysis = result["analysis"]
        tool_call_count = analysis["tool_call_count"]
        unique_signatures = analysis["unique_signatures"]
        has_dupes = analysis["has_duplicate_identical_calls"]
        any_duplicate_bug = any_duplicate_bug or has_dupes

        print(f"finish_reason: {result['finish_reason']}")
        print(f"elapsed_s: {elapsed:.1f}")
        print(f"tool_call_count: {tool_call_count}")
        print(f"unique_signatures: {unique_signatures}")
        print(f"duplicate_identical_calls: {has_dupes}")

        if has_dupes:
            top = analysis["duplicate_groups"][0]
            print(f"top_duplicate_count: {top['count']}")
            print(f"top_duplicate_function: {top['function_name']}")
            print(f"top_duplicate_arguments: {top['arguments']}")
            print(f"sample_ids: {top['ids']}")
        elif tool_call_count:
            tc = (result["raw_response"]["choices"][0]["message"]["tool_calls"] or [None])[0]
            if tc:
                print(f"single_tool_name: {(tc.get('function') or {}).get('name')}")
                print(f"single_tool_arguments: {(tc.get('function') or {}).get('arguments')}")
        else:
            print(f"content: {result['content']!r}")

        out_path = save_dir / f"run_{i}.json"
        out_path.write_text(json.dumps(result["raw_response"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"saved_raw: {out_path}")
        print()

    if any_duplicate_bug:
        print("RESULT: Duplicate identical tool_calls reproduced.")
        return 0

    print("RESULT: No duplicate identical tool_calls observed in these runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
