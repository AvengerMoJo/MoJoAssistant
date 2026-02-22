"""Unit tests for scheduler Dreaming automation behavior."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.scheduler.core import Scheduler
from app.scheduler.executor import TaskExecutor
from app.scheduler.models import Task, TaskType, TaskResources


class TestSchedulerDreamingAutomation(unittest.IsolatedAsyncioTestCase):
    def test_task_resources_round_trip(self):
        original = TaskResources(
            llm_provider="lmstudio",
            max_tokens=4096,
            max_duration_seconds=120,
            requires_gpu=True,
        )
        restored = TaskResources.from_dict(original.to_dict())

        self.assertEqual(restored.llm_provider, "lmstudio")
        self.assertEqual(restored.max_tokens, 4096)
        self.assertEqual(restored.max_duration_seconds, 120)
        self.assertTrue(restored.requires_gpu)

    def test_scheduler_ensures_default_dreaming_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(storage_path=str(Path(tmp) / "tasks.json"), tick_interval=60)
            scheduler._ensure_default_dreaming_task()

            task = scheduler.get_task("dreaming_nightly_offpeak_default")
            self.assertIsNotNone(task)
            self.assertEqual(task.type, TaskType.DREAMING)
            self.assertEqual(task.cron_expression, "0 3 * * *")
            self.assertTrue(task.config.get("automatic"))
            self.assertTrue(task.config.get("enforce_off_peak"))
            self.assertEqual(task.resources.requires_gpu, True)

    async def test_executor_skips_dreaming_outside_off_peak(self):
        executor = TaskExecutor()
        executor._is_within_off_peak = lambda *_args, **_kwargs: False

        task = Task(
            id="dream_skip",
            type=TaskType.DREAMING,
            config={
                "automatic": True,
                "enforce_off_peak": True,
                "off_peak_start": "01:00",
                "off_peak_end": "05:00",
            },
        )

        result = await executor._execute_dreaming(task)

        self.assertTrue(result.success)
        self.assertTrue(result.metrics.get("skipped"))
        self.assertEqual(result.metrics.get("reason"), "outside_off_peak_window")

    def test_executor_builds_automatic_input_from_memory_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "conversations_multi_model.json"
            data = [
                {"message_type": "user", "text_content": "hello"},
                {"message_type": "assistant", "text_content": "world"},
            ]
            with open(store, "w", encoding="utf-8") as f:
                json.dump(data, f)

            executor = TaskExecutor()
            built = executor._build_automatic_dreaming_input(
                {
                    "conversation_store_path": str(store),
                    "lookback_messages": 10,
                }
            )

            self.assertIsNotNone(built)
            self.assertTrue(built["conversation_id"].startswith("auto_dream_"))
            self.assertIn("[user] hello", built["conversation_text"])
            self.assertIn("[assistant] world", built["conversation_text"])

    async def test_executor_skips_automatic_when_no_recent_data(self):
        executor = TaskExecutor()
        executor._is_within_off_peak = lambda *_args, **_kwargs: True

        task = Task(
            id="dream_no_data",
            type=TaskType.DREAMING,
            config={
                "automatic": True,
                "enforce_off_peak": True,
                "conversation_store_path": "/tmp/does-not-exist-for-test.json",
            },
        )

        result = await executor._execute_dreaming(task)

        self.assertTrue(result.success)
        self.assertTrue(result.metrics.get("skipped"))
        self.assertEqual(result.metrics.get("reason"), "no_recent_conversation_data")


if __name__ == "__main__":
    unittest.main()
