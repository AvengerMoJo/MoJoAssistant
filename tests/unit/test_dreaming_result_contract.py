"""Dreaming must fail honestly instead of reporting success for a night that consolidated nothing.

2026-10-08 (F3): global dreaming 'completed' for a week while the newest archive was 8 days old.
Mechanisms found: ResourcePoolLLMInterface.generate_response swallowed LLM failures and returned "";
the pipeline turned an empty answer into zero chunks and still reported success; and the nightly job
re-dreamed the same last 200 messages every night (no watermark).
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.llm.resource_pool_interface import DreamingLLMError, ResourcePoolLLMInterface
from app.scheduler.handlers.dreaming import DreamingHandler
from app.scheduler.models import Task, TaskType


class TestLLMInterfaceRaises(unittest.TestCase):
    def _iface(self, resource):
        rm = MagicMock()
        rm.acquire.return_value = resource
        return ResourcePoolLLMInterface(rm), rm

    def _resource(self):
        r = MagicMock()
        r.id, r.base_url, r.model, r.api_key, r.output_limit, r.provider = "r1", "http://x/v1", "m", "k", 4096, "openai"
        return r

    def test_no_resource_raises(self):
        iface, _ = self._iface(None)
        with self.assertRaises(DreamingLLMError) as cm:
            iface.generate_response("hi")
        self.assertIn("no LLM resource", str(cm.exception))

    def test_connection_failure_raises_and_is_recorded(self):
        iface, rm = self._iface(self._resource())
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=ConnectionError("refused")):
            with self.assertRaises(DreamingLLMError):
                iface.generate_response("hi")
        rm.record_usage.assert_called_with("r1", success=False, error_message="refused")

    def test_empty_completion_raises(self):
        iface, _ = self._iface(self._resource())
        async def empty(*a, **k):
            return {"choices": [{"message": {"content": "   "}}]}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=empty):
            with self.assertRaises(DreamingLLMError) as cm:
                iface.generate_response("hi")
        self.assertIn("empty completion", str(cm.exception))

    def test_good_completion_is_returned(self):
        iface, _ = self._iface(self._resource())
        async def ok(*a, **k):
            return {"choices": [{"message": {"content": '{"chunks": []}'}}]}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=ok):
            self.assertEqual(iface.generate_response("hi"), '{"chunks": []}')


class _Pipeline:
    storage = None

    def __init__(self, chunks, clusters):
        self.chunks, self.clusters = chunks, clusters

    async def process_conversation(self, conversation_id, conversation_text, metadata):
        return {"status": "success", "stages": {"D_archive": {"path": "x"}, "B_chunks": {"count": self.chunks},
                                                "C_clusters": {"count": self.clusters}}}


def _run(chunks, clusters, text, **cfg):
    ctx = MagicMock()
    ctx._memory_service = None
    ctx.get_dreaming_pipeline.return_value = _Pipeline(chunks, clusters)
    task = Task(id="t", type=TaskType.DREAMING,
                config={"conversation_id": "c", "conversation_text": text, "enforce_off_peak": False, **cfg})
    return asyncio.run(DreamingHandler().execute(task, ctx))


class TestResultContract(unittest.TestCase):
    LONG = "word " * 200   # 1000 chars

    def test_real_input_with_no_chunks_is_a_failure(self):
        r = _run(0, 0, self.LONG)
        self.assertFalse(r.success)
        self.assertIn("0 chunks and 0 clusters", r.error_message)

    def test_chunks_but_no_clusters_is_a_failure(self):
        self.assertFalse(_run(3, 0, self.LONG).success)

    def test_real_output_succeeds(self):
        r = _run(3, 2, self.LONG)
        self.assertTrue(r.success)
        self.assertEqual(r.metrics["c_clusters_count"], 2)

    def test_tiny_input_may_legitimately_produce_nothing(self):
        self.assertTrue(_run(0, 0, "hi there").success)


class TestWatermark(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.store = self.dir / "conv.json"
        self.wm = self.dir / "state" / "wm.json"
        p = patch.object(DreamingHandler, "_global_watermark_path", staticmethod(lambda: self.wm))
        p.start()
        self.addCleanup(p.stop)

    def _write(self, n, start=0):
        msgs = [{"message_type": "user", "text_content": f"message {i}", "created_at": f"2026-10-08T10:{i:02d}:00"}
                for i in range(start, start + n)]
        self.store.write_text(json.dumps(msgs), encoding="utf-8")

    def _build(self, **cfg):
        return DreamingHandler._build_automatic_dreaming_input({"conversation_store_path": str(self.store), **cfg})

    def test_first_run_takes_the_latest_n(self):
        self._write(10)
        r = self._build(lookback_messages=4)
        self.assertEqual(r["metadata"]["message_count"], 4)
        self.assertIn("message 9", r["conversation_text"])
        self.assertNotIn("message 5", r["conversation_text"])
        self.assertEqual(r["metadata"]["watermark_candidate"], "2026-10-08T10:09:00")

    def test_after_commit_only_newer_messages_are_dreamed_and_nothing_new_is_none(self):
        self._write(10)
        DreamingHandler._commit_global_watermark("2026-10-08T10:09:00")
        self.assertIsNone(self._build())                       # nothing new
        self._write(13)
        r = self._build()
        self.assertEqual(r["metadata"]["message_count"], 3)
        self.assertIn("message 10", r["conversation_text"])
        self.assertNotIn("message 9", r["conversation_text"])

    def test_backlog_is_worked_off_oldest_first(self):
        self._write(30)
        DreamingHandler._commit_global_watermark("2026-10-08T10:09:00")
        r = self._build(lookback_messages=5)
        self.assertIn("message 10", r["conversation_text"])
        self.assertIn("message 14", r["conversation_text"])
        self.assertNotIn("message 15", r["conversation_text"])
        self.assertEqual(r["metadata"]["watermark_candidate"], "2026-10-08T10:14:00")

    def test_successful_run_advances_the_watermark_but_a_contract_failure_does_not(self):
        self._write(10)
        text = "x" * 1000
        ctx = MagicMock(); ctx._memory_service = None
        task = Task(id="t", type=TaskType.DREAMING, config={"automatic": True, "enforce_off_peak": False,
                                                            "conversation_store_path": str(self.store)})
        with patch.object(DreamingHandler, "_build_automatic_dreaming_input",
                          return_value={"conversation_id": "a", "conversation_text": text,
                                        "metadata": {"watermark_candidate": "2026-10-08T10:09:00"}}):
            ctx.get_dreaming_pipeline.return_value = _Pipeline(0, 0)
            self.assertFalse(asyncio.run(DreamingHandler().execute(task, ctx)).success)
            self.assertFalse(self.wm.exists())                 # failed run -> not advanced
            ctx.get_dreaming_pipeline.return_value = _Pipeline(2, 2)
            self.assertTrue(asyncio.run(DreamingHandler().execute(task, ctx)).success)
            self.assertEqual(json.loads(self.wm.read_text())["created_at"], "2026-10-08T10:09:00")


if __name__ == "__main__":
    unittest.main()
