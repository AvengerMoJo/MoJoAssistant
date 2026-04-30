#!/usr/bin/env python3
"""
LM Studio Tool Calling Benchmark - WITH TOOL DEFINITIONS

Tests whether local models call tools WHEN TOOL DEFINITIONS ARE PROVIDED.
"""

import json
import requests
import time
from dataclasses import dataclass
from typing import Optional, List, Dict

LMSTUDIO_BASE_URL = "http://localhost:8080/v1"
AUTH_HEADER = {"Authorization": "Bearer sk-lm-06MXupHm:0uQer5WlAbNPQl3lP0FZ"}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash_exec",
            "description": "Execute a bash command on the user's system",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    }
]

@dataclass
class ToolCallResult:
    model: str
    test_name: str
    made_tool_call: bool
    correct_tool: bool
    tool_name: Optional[str]
    arguments: Optional[str]
    reasoning_tokens: int
    response_time_ms: float
    error: Optional[str]


def test_tool_calling(model: str, test_name: str, prompt: str, expected_tool: str) -> ToolCallResult:
    start = time.time()
    
    try:
        resp = requests.post(
            f"{LMSTUDIO_BASE_URL}/chat/completions",
            headers=AUTH_HEADER,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "tools": TOOLS,
                "max_tokens": 500,
                "temperature": 0.1
            },
            timeout=30
        )
        elapsed = (time.time() - start) * 1000
        
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        
        reasoning_tokens = data.get("usage", {}).get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        
        tool_calls = msg.get("tool_calls", [])
        made_tool_call = len(tool_calls) > 0
        correct_tool = tool_calls[0]["function"]["name"] == expected_tool if tool_calls else False
        tool_name = tool_calls[0]["function"]["name"] if tool_calls else None
        arguments = tool_calls[0]["function"]["arguments"] if tool_calls else None
        
        return ToolCallResult(
            model=model,
            test_name=test_name,
            made_tool_call=made_tool_call,
            correct_tool=correct_tool,
            tool_name=tool_name,
            arguments=arguments,
            reasoning_tokens=reasoning_tokens,
            response_time_ms=elapsed,
            error=None
        )
        
    except Exception as e:
        return ToolCallResult(
            model=model,
            test_name=test_name,
            made_tool_call=False,
            correct_tool=False,
            tool_name=None,
            arguments=None,
            reasoning_tokens=0,
            response_time_ms=0,
            error=str(e)
        )


def run_benchmark():
    models = [
        "qwen/qwen3.6-35b-a3b",
        "qwen/qwen3.5-35b-a3b", 
        "google/gemma-4-26b-a4b"
    ]
    
    test_cases = [
        {
            "name": "get_public_ip",
            "prompt": "Get your public IP address using curl to ifconfig.me. Execute now.",
            "expected_tool": "bash_exec"
        },
        {
            "name": "list_files",
            "prompt": "List files in /tmp directory using list_files.",
            "expected_tool": "list_files"
        },
        {
            "name": "write_file",
            "prompt": "Write 'hello world' to /tmp/test.txt using write_file.",
            "expected_tool": "write_file"
        }
    ]
    
    all_results = {}
    
    for model in models:
        print(f"\n{'='*60}")
        print(f"Testing: {model}")
        print(f"{'='*60}")
        
        model_results = []
        for test in test_cases:
            result = test_tool_calling(model, test['name'], test['prompt'], test['expected_tool'])
            model_results.append(result)
            
            status = "PASS" if result.correct_tool else "FAIL"
            print(f"\n{status} {test['name']}")
            print(f"   Expected: {test['expected_tool']}")
            print(f"   Got: {result.tool_name or 'NO CALL'}")
            print(f"   Reasoning tokens: {result.reasoning_tokens}")
            print(f"   Response time: {result.response_time_ms:.0f}ms")
            
            if result.arguments:
                print(f"   Arguments: {result.arguments}")
            
            if result.error:
                print(f"   ERROR: {result.error}")
        
        all_results[model] = model_results
    
    print(f"\n{'='*60}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*60}")
    
    for model, model_results in all_results.items():
        tool_calls_made = sum(1 for r in model_results if r.made_tool_call)
        correct_tools = sum(1 for r in model_results if r.correct_tool)
        total_reasoning = sum(r.reasoning_tokens for r in model_results)
        avg_response = sum(r.response_time_ms for r in model_results) / len(model_results)
        
        print(f"\n{model}:")
        print(f"  Tool calls made: {tool_calls_made}/{len(model_results)}")
        print(f"  Correct tools: {correct_tools}/{len(model_results)}")
        print(f"  Total reasoning tokens: {total_reasoning}")
        print(f"  Avg response time: {avg_response:.0f}ms")
        
        if correct_tools == len(model_results):
            print(f"  Status: ALL TOOLS CORRECT")
        elif tool_calls_made > 0:
            print(f"  Status: PARTIAL (wrong tools)")
        else:
            print(f"  Status: NO TOOL CALLS")
    
    return all_results


if __name__ == "__main__":
    print("LM Studio Tool Calling Benchmark (WITH TOOL DEFINITIONS)")
    results = run_benchmark()
    
    output_file = f"/tmp/lmstudio_tool_calling_benchmark_{int(time.time())}.json"
    save_data = []
    for model, model_results in results.items():
        for r in model_results:
            save_data.append({
                "model": r.model,
                "test": r.test_name,
                "made_tool_call": r.made_tool_call,
                "correct_tool": r.correct_tool,
                "tool_name": r.tool_name,
                "arguments": r.arguments,
                "reasoning_tokens": r.reasoning_tokens,
                "response_time_ms": r.response_time_ms,
                "error": r.error
            })
    
    with open(output_file, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\nResults saved to: {output_file}")
