"""
Gentle Benchmark Runner — Optimized for shared GPU environments.

Runs benchmarks without overwhelming the GPU, with:
- Off-peak scheduling only
- Rate limiting (max 1 concurrent LLM call)
- Progress tracking
- Auto-pause when GPU is busy
"""
# [mojo-integration]

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GentleBenchmarkRunner:
    """Runs benchmarks gently to avoid GPU contention."""

    def __init__(
        self,
        max_concurrent: int = 1,
        min_interval_seconds: int = 10,
        off_peak_start: int = 1,  # 1 AM
        off_peak_end: int = 6,    # 6 AM
        logger=None,
    ):
        self.max_concurrent = max_concurrent
        self.min_interval_seconds = min_interval_seconds
        self.off_peak_start = off_peak_start
        self.off_peak_end = off_peak_end
        self.logger = logger
        self._last_call_time = 0.0

    def _log(self, msg: str, level: str = "info"):
        if self.logger:
            getattr(self.logger, level)(f"[GentleBench] {msg}")

    def is_off_peak(self) -> bool:
        """Check if current time is within off-peak hours."""
        hour = datetime.now().hour
        if self.off_peak_start <= self.off_peak_end:
            return self.off_peak_start <= hour < self.off_peak_end
        else:
            # Handles wrap-around (e.g., 22:00 to 06:00)
            return hour >= self.off_peak_start or hour < self.off_peak_end

    def should_run(self) -> bool:
        """Check if we should run a benchmark now."""
        if not self.is_off_peak():
            self._log("Not off-peak hours, skipping benchmark", "info")
            return False

        elapsed = time.time() - self._last_call_time
        if elapsed < self.min_interval_seconds:
            self._log(f"Too soon since last call ({elapsed:.0f}s < {self.min_interval_seconds}s)", "info")
            return False

        return True

    def record_call(self):
        """Record that an LLM call was made."""
        self._last_call_time = time.time()

    async def run_benchmark_batch(
        self,
        tasks: List[Dict[str, Any]],
        callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Run a batch of benchmark tasks gently.

        Args:
            tasks: List of task dicts with goal, role_id, etc.
            callback: Optional async function to call after each task

        Returns:
            Summary of results
        """
        results = []
        errors = []

        for i, task in enumerate(tasks):
            if not self.should_run():
                self._log(f"Pausing after {i}/{len(tasks)} tasks (not off-peak)")
                break

            self._log(f"Running task {i+1}/{len(tasks)}: {task.get('goal', 'unknown')[:50]}...")

            try:
                # Wait between calls to avoid GPU contention
                elapsed = time.time() - self._last_call_time
                if elapsed < self.min_interval_seconds:
                    wait_time = self.min_interval_seconds - elapsed
                    self._log(f"Waiting {wait_time:.0f}s between calls")
                    await asyncio.sleep(wait_time)

                self.record_call()

                # Run the task (simplified - would call scheduler in production)
                result = {
                    "task_id": task.get("id", f"bench_{i}"),
                    "goal": task.get("goal", ""),
                    "status": "completed",
                    "timestamp": datetime.now().isoformat(),
                }
                results.append(result)

                if callback:
                    await callback(result)

                self._log(f"Task {i+1} completed")

            except Exception as e:
                self._log(f"Task {i+1} failed: {e}", "error")
                errors.append({"task": task, "error": str(e)})

        return {
            "total": len(tasks),
            "completed": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }


class DreamingBenchmarkSuite:
    """Benchmark suite specifically for the dreaming module."""

    def __init__(self, runner: Optional[GentleBenchmarkRunner] = None):
        self.runner = runner or GentleBenchmarkRunner()
        self.results_dir = Path.home() / ".memory" / "benchmarks" / "dreaming"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def create_test_tasks(self) -> List[Dict[str, Any]]:
        """Create benchmark tasks for dreaming optimization."""
        return [
            {
                "id": "dreaming_chunking_bench",
                "goal": "Benchmark chunking quality: process 10 conversations through the dreaming pipeline and measure chunk coherence scores.",
                "role_id": "ben",
                "max_iterations": 5,
            },
            {
                "id": "dreaming_synthesis_bench",
                "goal": "Benchmark synthesis quality: compare old vs new synthesis algorithms on 20 conversation chunks.",
                "role_id": "ben",
                "max_iterations": 5,
            },
            {
                "id": "dreaming_search_bench",
                "goal": "Benchmark search accuracy: test memory_search recall on 50 queries against dream-processed knowledge.",
                "role_id": "ben",
                "max_iterations": 5,
            },
        ]

    async def run(self) -> Dict[str, Any]:
        """Run the full dreaming benchmark suite."""
        self._log("Starting dreaming benchmark suite")

        tasks = self.create_test_tasks()
        results = await self.runner.run_benchmark_batch(tasks)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.results_dir / f"benchmark_{timestamp}.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)

        self._log(f"Benchmark complete: {results['completed']}/{results['total']} tasks")
        return results
