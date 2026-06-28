"""Local Model Benchmark Runner — 1-Shot Complexity Ceiling.

Runs 100 tasks across 5 complexity tiers to find the maximum task
complexity where the local model succeeds in exactly 1 LLM call.

Usage:
    python -m tests.benchmarks.run_local_model_benchmark
    python -m tests.benchmarks.run_local_model_benchmark --tier 1
    python -m tests.benchmarks.run_local_model_benchmark --config docs/design/autoresearch/benchmark_config.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_tasks(tier: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load benchmark tasks from ~/.memory/benchmarks/local_model/tasks/"""
    base = Path.home() / ".memory" / "benchmarks" / "local_model" / "tasks"
    tasks = []
    tiers = [tier] if tier else [1, 2, 3, 4, 5]
    for t in tiers:
        tier_dir = base / f"tier{t}"
        if not tier_dir.exists():
            continue
        for f in sorted(tier_dir.glob("*.json")):
            try:
                tasks.append(json.loads(f.read_text()))
            except Exception as e:
                print(f"Warning: failed to load {f}: {e}")
    return tasks


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load benchmark config."""
    if config_path:
        return json.loads(Path(config_path).read_text())
    default = PROJECT_ROOT / "docs" / "design" / "autoresearch" / "benchmark_config.json"
    if default.exists():
        return json.loads(default.read_text())
    return {
        "context_depth": 5,
        "pre_granted_tools": ["read_file", "memory_search"],
        "goal_phrasing": "concrete",
        "few_shot_examples": 0,
        "memory_injection": True,
        "max_context_tokens": 2000,
    }


def check_answer(task: Dict[str, Any], response: str) -> bool:
    """Check if response matches the expected answer."""
    match_type = task.get("match_type", "exact")
    correct = task.get("correct_answer", "")
    
    if not response or not correct:
        return False
    
    response = response.strip()
    correct = correct.strip()
    
    if match_type == "exact":
        return response.lower() == correct.lower()
    elif match_type == "contains":
        return correct.lower() in response.lower()
    elif match_type == "semantic":
        # For semantic matching, use simple keyword overlap
        resp_words = set(response.lower().split())
        correct_words = set(correct.lower().split())
        if not correct_words:
            return False
        overlap = len(resp_words & correct_words)
        return overlap / len(correct_words) >= 0.5
    return False


def run_task(task: Dict[str, Any], config: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Run a single benchmark task by calling the local LLM."""
    import asyncio
    task_id = task["id"]
    goal = task["goal"]
    tier = task.get("tier", 0)
    
    start = time.time()
    result = {
        "task_id": task_id,
        "tier": tier,
        "goal": goal,
        "iterations": 1,
        "success": False,
        "response": "",
        "elapsed_s": 0,
        "error": None,
    }
    
    try:
        # Load resource pool to get local model
        from app.scheduler.resource_pool import ResourceManager
        pool = ResourceManager()
        resource = pool.acquire()
        
        if not resource:
            result["error"] = "No LLM resource available"
            return result
        
        # Build messages with context injection
        system_prompt = "You are a helpful assistant. Answer the question concisely and accurately."
        
        # Inject context based on task.setup
        setup = task.get("setup", "")
        context = ""
        if setup.startswith("role="):
            role_id = setup.split("=")[1]
            role_path = Path.home() / ".memory" / "roles" / f"{role_id}.json"
            if role_path.exists():
                context = f"Role config for {role_id}:\n{role_path.read_text()[:2000]}"
        elif setup.startswith("file="):
            file_path = PROJECT_ROOT / setup.split("=", 1)[1]
            if file_path.exists():
                context = f"File {file_path.name}:\n{file_path.read_text()[:2000]}"
        elif setup == "roles":
            roles_dir = Path.home() / ".memory" / "roles"
            role_summaries = []
            for f in sorted(roles_dir.glob("*.json"))[:20]:
                try:
                    r = json.loads(f.read_text())
                    role_summaries.append(f"{r.get('id','?')}: {r.get('name','')} - capabilities: {r.get('capabilities',[])}")
                except:
                    pass
            context = "Roles:\n" + "\n".join(role_summaries)
        elif setup == "resource_pool":
            pool_path = Path.home() / ".memory" / "config" / "resource_pool.json"
            if pool_path.exists():
                context = f"Resource pool config:\n{pool_path.read_text()[:2000]}"
        elif setup == "embedding_pool":
            pool_path = Path.home() / ".memory" / "config" / "embedding_pool.json"
            if pool_path.exists():
                context = f"Embedding pool config:\n{pool_path.read_text()[:2000]}"
        
        if context:
            system_prompt += f"\n\nRelevant context:\n{context}"
        
        if config.get("memory_injection"):
            system_prompt += "\nYou have access to MoJoAssistant's memory and tools."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]
        
        # Call LLM with max_iterations=1 for 1-shot measurement
        from app.llm.unified_client import UnifiedLLMClient
        client = UnifiedLLMClient()
        
        resource_config = {
            "base_url": resource.base_url,
            "model": resource.model,
            "api_key": resource.api_key,
            "output_limit": min(resource.output_limit or 8192, 8192),
            "message_format": "openai",
            "provider": resource.provider,
        }
        
        # Use call_async for single LLM call
        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(
                client.call_async(
                    messages=messages,
                    resource_config=resource_config,
                    model_override=resource.model,
                )
            )
        finally:
            loop.close()
        
        # Extract response
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            response_text = message.get("content", "")
            result["response"] = response_text
            
            # Check if answer matches
            result["success"] = check_answer(task, response_text)
        
    except Exception as e:
        result["error"] = str(e)
    
    result["elapsed_s"] = round(time.time() - start, 1)
    
    # Save task result
    result_path = run_dir / f"{task_id}.json"
    result_path.write_text(json.dumps(result, indent=2))
    
    return result


def run_benchmark(
    config: Dict[str, Any],
    tier: Optional[int] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full benchmark or a single tier."""
    tasks = load_tasks(tier)
    if not tasks:
        print("No tasks found!")
        return {}
    
    # Create run directory
    if not run_id:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path.home() / ".memory" / "benchmarks" / "local_model" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Running benchmark: {run_id}")
    print(f"Tasks: {len(tasks)}")
    print(f"Config: {json.dumps(config, indent=2)}")
    print()
    
    # Run tasks
    results = []
    tier_stats = {}
    
    for task in tasks:
        t = task.get("tier", 0)
        print(f"  {task['id']} (T{t}): {task['goal'][:60]}...", end=" ")
        
        result = run_task(task, config, run_dir)
        results.append(result)
        
        if t not in tier_stats:
            tier_stats[t] = {"total": 0, "success": 0, "iterations": []}
        tier_stats[t]["total"] += 1
        if result["success"]:
            tier_stats[t]["success"] += 1
        tier_stats[t]["iterations"].append(result["iterations"])
        
        status = "✓" if result["success"] else "✗"
        print(f"{status} ({result['iterations']} iter, {result['elapsed_s']:.1f}s)")
    
    # Calculate per-tier 1SR
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    
    tier_scores = {}
    for t in sorted(tier_stats.keys()):
        stats = tier_stats[t]
        sr = stats["success"] / stats["total"] if stats["total"] > 0 else 0
        avg_iter = sum(stats["iterations"]) / len(stats["iterations"]) if stats["iterations"] else 0
        tier_scores[f"1SR_T{t}"] = round(sr, 3)
        print(f"  T{t}: 1SR={sr:.3f} ({stats['success']}/{stats['total']}), avg_iter={avg_iter:.1f}")
    
    # Find boundary tier
    boundary = 0
    for t in sorted(tier_stats.keys()):
        stats = tier_stats[t]
        sr = stats["success"] / stats["total"] if stats["total"] > 0 else 0
        if sr >= 0.80:
            boundary = t
    
    print(f"\nBoundary tier: T{boundary} (1SR >= 0.80)")
    
    # Save summary
    summary = {
        "run_id": run_id,
        "config": config,
        "tier_scores": tier_scores,
        "boundary": boundary,
        "total_tasks": len(tasks),
        "timestamp": datetime.now().isoformat(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run local model benchmark")
    parser.add_argument("--tier", type=int, help="Run specific tier only")
    parser.add_argument("--config", help="Path to benchmark_config.json")
    parser.add_argument("--run-id", help="Custom run ID")
    args = parser.parse_args()
    
    config = load_config(args.config)
    run_benchmark(config, tier=args.tier, run_id=args.run_id)


if __name__ == "__main__":
    main()
