#!/usr/bin/env python3
"""
Compare local models' tool-calling behavior across:

1. Raw MoJo registry tool schemas ("registry")
2. Runtime-corrected tool schemas for known mismatches ("runtime_fixed")

and across two prompt styles:

1. tools_only
2. capability_overlay

This is intended to debug cases where a role has a capability like "file",
but the model either:
- emits malformed tool calls
- uses the wrong argument names
- duplicates identical calls
- or behaves differently depending on how the tool surface is described

The harness uses MoJo's real CapabilityRegistry definitions by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.config_loader import load_layered_json_config
from app.scheduler.capability_registry import CapabilityRegistry


DEFAULT_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:8080/v1")
DEFAULT_MODELS = os.environ.get(
    "LMSTUDIO_COMPARE_MODELS",
    "qwen/qwen3.5-35b-a3b,google/gemma-4-26b-a4b",
)
DEFAULT_API_KEY = os.environ.get("LMSTUDIO_API_KEY", "")
DEFAULT_SAVE_DIR = "/tmp/model_tool_mapping_compare"


RUNTIME_ARG_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "list_files": {
        "required": ["path"],
        "allowed": ["path"],
    },
    "read_file": {
        "required": ["path"],
        "allowed": ["path"],
    },
    # Important: runtime handler expects "query", while registry schema may still say "pattern"
    "search_in_files": {
        "required": ["query"],
        "allowed": ["query", "path"],
    },
}


TEST_CASES = [
    {
        "id": "list_files_scripts",
        "capabilities": ["file"],
        "expected_tool": "list_files",
        "user_request": (
            "Use exactly one tool call to list the files in the scripts directory. "
            f'Path: "{REPO_ROOT / "scripts"}". '
            "Do not answer in prose before the tool call."
        ),
    },
    {
        "id": "read_file_pyproject",
        "capabilities": ["file"],
        "expected_tool": "read_file",
        "user_request": (
            "Use exactly one tool call to read the file "
            f'"{REPO_ROOT / "pyproject.toml"}". '
            "Do not answer in prose before the tool call."
        ),
    },
    {
        "id": "search_in_files_parallel_tool_calls",
        "capabilities": ["file"],
        "expected_tool": "search_in_files",
        "user_request": (
            "Use exactly one tool call to search the app directory for the text "
            '"parallel_tool_calls". '
            f'Path: "{REPO_ROOT / "app"}". '
            "Use the correct runtime argument names for this tool. "
            "Do not answer in prose before the tool call."
        ),
    },
]


def _load_capability_tools(capabilities: list[str]) -> list[str]:
    catalog = load_layered_json_config("config/capability_catalog.json")
    tools_meta = catalog.get("tools", {})
    names: list[str] = []
    for tool_name, meta in tools_meta.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("always_injected") or meta.get("internal"):
            continue
        if meta.get("category") in set(capabilities):
            names.append(tool_name)
    return names


def _tool_defs_for_capabilities(
    registry: CapabilityRegistry,
    capabilities: list[str],
    schema_source: str,
) -> list[dict[str, Any]]:
    tool_names = _load_capability_tools(capabilities)
    tools: list[dict[str, Any]] = []
    for name in tool_names:
        tdef = registry._tools.get(name)
        if not tdef:
            continue
        tool = deepcopy(tdef.to_openai_function())
        if schema_source == "runtime_fixed" and name in RUNTIME_ARG_EXPECTATIONS:
            expected = RUNTIME_ARG_EXPECTATIONS[name]
            params = deepcopy(tool["function"]["parameters"])
            props = params.setdefault("properties", {})
            # For known mismatches, normalize the runtime-facing argument names.
            if name == "search_in_files":
                props.pop("pattern", None)
                props["query"] = {
                    "type": "string",
                    "description": "Text or regex query to search for",
                }
            params["required"] = expected["required"]
            tool["function"]["parameters"] = params
        tools.append(tool)
    return tools


def _build_system_prompt(
    prompt_style: str,
    capabilities: list[str],
    tool_defs: list[dict[str, Any]],
) -> str:
    if prompt_style == "tools_only":
        return (
            "You are testing OpenAI-style tool calling. "
            "Use exactly one tool call. "
            "Do not explain, plan, or ask questions before the tool call. "
            "Do not emit XML. Do not invent tools or argument names."
        )

    if prompt_style == "capability_overlay":
        lines = [
            "You are testing capability-to-tool mapping.",
            "You have these capabilities: " + ", ".join(capabilities),
            "Use exactly one mapped tool call. Do not explain before the tool call.",
            "Do not emit XML. Do not invent tools or argument names.",
            "Mapped tools:",
        ]
        for tool in tool_defs:
            fn = tool["function"]
            props = fn.get("parameters", {}).get("properties", {})
            required = fn.get("parameters", {}).get("required", [])
            arg_names = ", ".join(props.keys()) or "no args"
            lines.append(
                f'- {fn["name"]}({arg_names}) required={required}'
            )
        return "\n".join(lines)

    raise ValueError(f"Unknown prompt_style: {prompt_style}")


def _build_payload(
    model: str,
    prompt_style: str,
    schema_source: str,
    case: dict[str, Any],
    tool_defs: list[dict[str, Any]],
) -> dict[str, Any]:
    system = _build_system_prompt(prompt_style, case["capabilities"], tool_defs)
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 512,
        "parallel_tool_calls": False,
        "tool_choice": "required",
        "tools": tool_defs,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"[schema_source={schema_source}] [case={case['id']}] "
                    + case["user_request"]
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


def _extract_message(data: dict[str, Any]) -> dict[str, Any]:
    return data["choices"][0]["message"]


def _tool_signature(tc: dict[str, Any]) -> tuple[str, str]:
    fn = tc.get("function") or {}
    return fn.get("name", ""), fn.get("arguments", "")


def _validate_against_runtime(tool_name: str, parsed_args: Any) -> dict[str, Any]:
    expected = RUNTIME_ARG_EXPECTATIONS.get(tool_name)
    if not expected:
        return {"runtime_schema_known": False, "runtime_valid": None, "missing": [], "unexpected": []}
    if not isinstance(parsed_args, dict):
        return {
            "runtime_schema_known": True,
            "runtime_valid": False,
            "missing": expected["required"],
            "unexpected": [],
        }
    missing = [k for k in expected["required"] if k not in parsed_args]
    unexpected = [k for k in parsed_args.keys() if k not in expected["allowed"]]
    return {
        "runtime_schema_known": True,
        "runtime_valid": not missing and not unexpected,
        "missing": missing,
        "unexpected": unexpected,
    }


def _analyze_response(case: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    message = _extract_message(data)
    tool_calls = message.get("tool_calls") or []
    sig_counter = Counter(_tool_signature(tc) for tc in tool_calls)
    duplicates = {f"{k[0]}::{k[1]}": v for k, v in sig_counter.items() if v > 1}

    first_name = None
    first_args_raw = None
    first_args_parsed = None
    first_args_parse_error = None
    runtime_validation = {"runtime_schema_known": False, "runtime_valid": None, "missing": [], "unexpected": []}

    if tool_calls:
        fn = tool_calls[0].get("function") or {}
        first_name = fn.get("name")
        first_args_raw = fn.get("arguments")
        if isinstance(first_args_raw, str):
            try:
                first_args_parsed = json.loads(first_args_raw)
            except Exception as exc:
                first_args_parse_error = str(exc)
        elif isinstance(first_args_raw, dict):
            first_args_parsed = first_args_raw
        runtime_validation = _validate_against_runtime(first_name or "", first_args_parsed)

    return {
        "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
        "tool_call_count": len(tool_calls),
        "unique_signatures": len(sig_counter),
        "duplicate_identical_calls": bool(duplicates),
        "duplicate_groups": duplicates,
        "expected_tool": case["expected_tool"],
        "first_tool_name": first_name,
        "first_tool_matches_expected": first_name == case["expected_tool"],
        "first_args_raw": first_args_raw,
        "first_args_parsed": first_args_parsed,
        "first_args_parse_error": first_args_parse_error,
        "runtime_validation": runtime_validation,
        "assistant_content": message.get("content"),
    }


def run_matrix(
    base_url: str,
    model: str,
    timeout: int,
    api_key: str,
    save_dir: Path,
) -> list[dict[str, Any]]:
    registry = CapabilityRegistry()
    rows: list[dict[str, Any]] = []
    for schema_source in ("registry", "runtime_fixed"):
        for prompt_style in ("tools_only", "capability_overlay"):
            for case in TEST_CASES:
                tool_defs = _tool_defs_for_capabilities(registry, case["capabilities"], schema_source)
                payload = _build_payload(model, prompt_style, schema_source, case, tool_defs)
                started = time.time()
                try:
                    data = _post_json(
                        f"{base_url.rstrip('/')}/chat/completions",
                        payload,
                        timeout=timeout,
                        api_key=api_key,
                    )
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace")
                    rows.append(
                        {
                            "model": model,
                            "schema_source": schema_source,
                            "prompt_style": prompt_style,
                            "case_id": case["id"],
                            "http_error": exc.code,
                            "error_body": body,
                        }
                    )
                    continue
                except Exception as exc:
                    rows.append(
                        {
                            "model": model,
                            "schema_source": schema_source,
                            "prompt_style": prompt_style,
                            "case_id": case["id"],
                            "request_error": str(exc),
                        }
                    )
                    continue

                analysis = _analyze_response(case, data)
                row = {
                    "model": model,
                    "schema_source": schema_source,
                    "prompt_style": prompt_style,
                    "case_id": case["id"],
                    "elapsed_s": round(time.time() - started, 1),
                    **analysis,
                }
                rows.append(row)

                out_name = f"{model.replace('/', '__')}__{schema_source}__{prompt_style}__{case['id']}.json"
                (save_dir / out_name).write_text(
                    json.dumps({"payload": payload, "response": data, "analysis": row}, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
    return rows


def print_summary(rows: list[dict[str, Any]]) -> None:
    print()
    print("=== Summary ===")
    for row in rows:
        if row.get("http_error") or row.get("request_error"):
            print(
                f"{row['model']} | {row['schema_source']} | {row['prompt_style']} | {row['case_id']} "
                f"| ERROR: {row.get('http_error') or row.get('request_error')}"
            )
            continue

        rv = row["runtime_validation"]
        print(
            f"{row['model']} | {row['schema_source']} | {row['prompt_style']} | {row['case_id']} "
            f"| finish={row['finish_reason']} "
            f"| tool={row['first_tool_name']} "
            f"| match={row['first_tool_matches_expected']} "
            f"| args_ok={rv['runtime_valid']} "
            f"| dupes={row['duplicate_identical_calls']}({row['tool_call_count']})"
        )
        if row.get("first_args_parse_error"):
            print(f"  parse_error: {row['first_args_parse_error']}")
        if rv["runtime_schema_known"] and (rv["missing"] or rv["unexpected"]):
            print(f"  runtime_missing={rv['missing']} runtime_unexpected={rv['unexpected']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Qwen/Gemma tool-calling behavior against MoJo capability/tool mappings."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL")
    parser.add_argument("--models", default=DEFAULT_MODELS, help="Comma-separated model names")
    parser.add_argument("--timeout", type=int, default=90, help="Per-request timeout seconds")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Bearer token if required")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR, help="Where to save raw payload/response files")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    print(f"Base URL: {args.base_url}")
    print(f"Models: {models}")
    print(f"Save dir: {save_dir}")

    all_rows: list[dict[str, Any]] = []
    for model in models:
        print()
        print(f"=== Model: {model} ===")
        rows = run_matrix(
            base_url=args.base_url,
            model=model,
            timeout=args.timeout,
            api_key=args.api_key,
            save_dir=save_dir,
        )
        all_rows.extend(rows)

    print_summary(all_rows)
    summary_path = save_dir / "summary.json"
    summary_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print()
    print(f"Saved summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
