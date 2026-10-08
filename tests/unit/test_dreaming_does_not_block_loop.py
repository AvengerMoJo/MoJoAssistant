"""The dreaming pipeline must not freeze the scheduler's event loop.

2026-10-08: a dreaming run stopped every scheduler tick for 2m38s. The pipeline is async in
name only -- its chunker/synthesizer call ResourcePoolLLMInterface.generate_response(),
which blocks the calling thread until the LLM answers (sampled: 158s inside that call).
"""
import asyncio
import time
import unittest
from unittest.mock import MagicMock

from app.scheduler.handlers.dreaming import DreamingHandler
from app.scheduler.models import Task, TaskType


class _BlockingPipeline:
    """Async on the surface, but blocks its thread like the real chunker/synthesizer do."""

    storage = None

    async def process_conversation(self, conversation_id, conversation_text, metadata):
        time.sleep(1.2)
        return {"status": "success", "stages": {"D_archive": {"path": "x"}, "B_chunks": {"count": 1},
                                                "C_clusters": {"count": 1}}}

    async def process_document(self, doc_id, document_text, metadata):
        time.sleep(1.2)
        return {"status": "success", "stages": {"knowledge_units": {"count": 1, "total_links": 0}}}


def _run(config):
    ctx = MagicMock()
    ctx._memory_service = None
    ctx.get_dreaming_pipeline.return_value = _BlockingPipeline()
    task = Task(id="t", type=TaskType.DREAMING, config=config)

    async def go():
        beats = []

        async def heartbeat():
            while True:
                beats.append(time.monotonic())
                await asyncio.sleep(0.05)

        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.15)
        result = await DreamingHandler().execute(task, ctx)
        await asyncio.sleep(0.15)  # let a post-run beat land, or a stall would go unrecorded
        hb.cancel()
        return result, beats

    return asyncio.run(go())


class TestDreamingOffLoop(unittest.TestCase):
    def _assert_loop_stayed_responsive(self, beats):
        self.assertLess(max(b - a for a, b in zip(beats, beats[1:])), 0.5,
                        "event loop was blocked while the pipeline ran")

    def test_conversation_mode_keeps_loop_responsive_and_still_succeeds(self):
        result, beats = _run({"conversation_id": "c", "conversation_text": "hello", "enforce_off_peak": False})
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.metrics["c_clusters_count"], 1)
        self._assert_loop_stayed_responsive(beats)

    def test_document_mode_keeps_loop_responsive_and_still_succeeds(self):
        result, beats = _run({"mode": "document", "doc_id": "d", "conversation_text": "doc", "role_id": "r",
                              "enforce_off_peak": False})
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.metrics["knowledge_units_count"], 1)
        self._assert_loop_stayed_responsive(beats)


if __name__ == "__main__":
    unittest.main()


class TestAutomaticInputIsBuiltOffLoop(unittest.TestCase):
    """Building the nightly input parses the whole 171MB conversation store; the watchdog logged a 5.5s stall."""

    def test_slow_input_builder_does_not_stall_the_loop(self):
        from unittest.mock import patch

        def slow_builder(config):
            time.sleep(1.0)    # stands in for json.load of the store
            return {"conversation_id": "a", "conversation_text": "hello", "metadata": {}}
        ctx = MagicMock()
        ctx._memory_service = None
        ctx.get_dreaming_pipeline.return_value = _BlockingPipeline()
        task = Task(id="t", type=TaskType.DREAMING, config={"automatic": True, "enforce_off_peak": False})

        async def go():
            beats = []

            async def heartbeat():
                while True:
                    beats.append(time.monotonic())
                    await asyncio.sleep(0.05)
            hb = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.15)
            with patch.object(DreamingHandler, "_build_automatic_dreaming_input", staticmethod(slow_builder)):
                await DreamingHandler().execute(task, ctx)
            await asyncio.sleep(0.15)
            hb.cancel()
            return beats
        beats = asyncio.run(go())
        # the pipeline stub itself blocks 1.2s on its own (thread); only the builder phase is under test,
        # so require that the loop kept ticking during the first second
        first_second = [b for b in beats if b - beats[0] < 1.0]
        self.assertGreater(len(first_second), 10, "loop did not tick while the input builder ran")
