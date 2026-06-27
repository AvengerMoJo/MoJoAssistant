"""Embedding Model Benchmark Runner for MoJoAssistant.

Uses MTEB to evaluate embedding models on retrieval and similarity tasks.
Results are used to set priorities in the embedding resource pool.

Usage:
    python -m tests.benchmarks.run_embedding_benchmark --models bge-m3,bge-small
    python -m tests.benchmarks.run_embedding_benchmark --all
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# MTEB tasks relevant to MoJoAssistant's memory/knowledge retrieval use case
RETRIEVAL_TASKS = [
    "MSMARCO",
    "NQ",
    "HotPotQA",
    "FiQA2018",
    "TRECCOVID",
]

SIMILARITY_TASKS = [
    "STS12",
    "STS13",
    "STS14",
    "STS15",
    "STS16",
    "STSBenchmark",
    "SICK-R",
]

CLUSTERING_TASKS = [
    "TwentyNewsgroupsClustering",
    "StackExchangeClustering",
]

# Model configurations matching our embedding pool
MODELS = {
    "bge-m3": {
        "model_name": "BAAI/bge-m3",
        "backend": "huggingface",
        "dim": 1024,
    },
    "bge-small": {
        "model_name": "BAAI/bge-small-en-v1.5",
        "backend": "huggingface",
        "dim": 384,
    },
    "gemma-300m": {
        "model_name": "google/embeddinggemma-300m",
        "backend": "huggingface",
        "dim": 768,
    },
    "all-minilm": {
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "backend": "huggingface",
        "dim": 384,
    },
}


def run_benchmark(model_key: str, tasks: List[str], output_dir: str) -> Dict[str, Any]:
    """Run MTEB benchmark for a single model."""
    import mteb

    model_cfg = MODELS[model_key]
    model_name = model_cfg["model_name"]

    print(f"\n{'='*60}")
    print(f"Benchmarking: {model_key} ({model_name})")
    print(f"{'='*60}")

    try:
        model = mteb.get_model(model_name)
    except Exception as e:
        print(f"Failed to load model: {e}")
        return {"model": model_key, "error": str(e)}

    results = {}
    for task_name in tasks:
        print(f"\n  Running {task_name}...")
        start = time.time()
        try:
            task = mteb.get_tasks(tasks=[task_name])
            result = mteb.evaluate(model, tasks=task)
            elapsed = time.time() - start

            # Extract main score
            score = None
            for r in result:
                if hasattr(r, "scores"):
                    for split_scores in r.scores.values():
                        for score_entry in split_scores:
                            if hasattr(score_entry, "main_score"):
                                score = score_entry.main_score
                                break

            results[task_name] = {
                "score": score,
                "elapsed_s": round(elapsed, 1),
            }
            print(f"    Score: {score:.4f} ({elapsed:.1f}s)")

        except Exception as e:
            print(f"    Failed: {e}")
            results[task_name] = {"error": str(e)}

    return {
        "model": model_key,
        "model_name": model_name,
        "dim": model_cfg["dim"],
        "results": results,
    }


def compute_priority(model_key: str, scores: Dict[str, float]) -> int:
    """Compute priority based on benchmark scores. Higher score = lower priority number."""
    # Weight retrieval heavily (most relevant to MoJoAssistant)
    retrieval_scores = [scores.get(t, 0) for t in RETRIEVAL_TASKS if t in scores]
    similarity_scores = [scores.get(t, 0) for t in SIMILARITY_TASKS if t in scores]

    if not retrieval_scores and not similarity_scores:
        return 50  # Unknown — low priority

    avg_retrieval = sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else 0
    avg_similarity = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0

    # Weighted average: 70% retrieval, 30% similarity
    combined = avg_retrieval * 0.7 + avg_similarity * 0.3

    # Map to priority: best model = 1, worst = 50
    # Assume scores are 0-1, typical range 0.3-0.8
    priority = max(1, min(50, int((1 - combined) * 100)))
    return priority


def update_pool(results: List[Dict[str, Any]]) -> None:
    """Update embedding pool config with benchmark-derived priorities."""
    config_path = Path.home() / ".memory" / "config" / "embedding_pool.json"

    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {"embedding_models": {}}

    for result in results:
        if "error" in result:
            continue

        model_key = result["model"]
        scores = {k: v["score"] for k, v in result["results"].items() if "score" in v}
        priority = compute_priority(model_key, scores)

        # Find or create entry
        models = config.get("embedding_models", {})
        entry = models.get(model_key, {})
        entry["priority"] = priority
        entry["benchmark_scores"] = scores
        entry["benchmark_date"] = time.strftime("%Y-%m-%d")
        models[model_key] = entry

    config["embedding_models"] = models

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))
    print(f"\nUpdated {config_path} with benchmark priorities")


def main():
    parser = argparse.ArgumentParser(description="Benchmark embedding models")
    parser.add_argument("--models", help="Comma-separated model keys to benchmark")
    parser.add_argument("--all", action="store_true", help="Benchmark all configured models")
    parser.add_argument("--tasks", default="retrieval", choices=["retrieval", "similarity", "clustering", "all"])
    parser.add_argument("--output", default="/tmp/embedding_benchmark")
    parser.add_argument("--update-pool", action="store_true", help="Update embedding pool priorities")
    args = parser.parse_args()

    if args.all:
        model_keys = list(MODELS.keys())
    elif args.models:
        model_keys = [m.strip() for m in args.models.split(",")]
    else:
        print("Specify --models or --all")
        return

    if args.tasks == "retrieval":
        tasks = RETRIEVAL_TASKS
    elif args.tasks == "similarity":
        tasks = SIMILARITY_TASKS
    elif args.tasks == "clustering":
        tasks = CLUSTERING_TASKS
    else:
        tasks = RETRIEVAL_TASKS + SIMILARITY_TASKS + CLUSTERING_TASKS

    Path(args.output).mkdir(parents=True, exist_ok=True)

    all_results = []
    for model_key in model_keys:
        if model_key not in MODELS:
            print(f"Unknown model: {model_key}")
            continue
        result = run_benchmark(model_key, tasks, args.output)
        all_results.append(result)

        # Save individual result
        result_path = Path(args.output) / f"{model_key}.json"
        result_path.write_text(json.dumps(result, indent=2))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for result in all_results:
        if "error" in result:
            print(f"  {result['model']}: ERROR - {result['error']}")
        else:
            scores = {k: v.get("score", 0) for k, v in result["results"].items()}
            avg = sum(scores.values()) / len(scores) if scores else 0
            print(f"  {result['model']}: avg={avg:.4f} dim={result['dim']}")

    if args.update_pool:
        update_pool(all_results)


if __name__ == "__main__":
    main()
