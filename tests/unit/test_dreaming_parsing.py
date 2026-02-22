"""Unit tests for Dreaming parser resilience and fail-fast behavior."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.dreaming.chunker import ConversationChunker
from app.dreaming.synthesizer import DreamingSynthesizer
from app.dreaming.models import BChunk, ChunkType


class _FakeActiveInterface:
    def __init__(self, model: str = "fake-model"):
        self.model = model


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.active_interface_name = "fake-provider"
        self.active_interface = _FakeActiveInterface("fake-model")

    def generate_response(self, query=None, context=None):
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


class TestDreamingParsing(unittest.IsolatedAsyncioTestCase):
    async def test_chunker_parses_json_embedded_in_prose(self):
        llm = _FakeLLM(
            [
                'Here is the result:\n{"chunks":[{"content":"hello","language":"en","labels":["x"],"speaker":"user","entities":[],"summary":"s"}]}\nThanks'
            ]
        )
        chunker = ConversationChunker(llm_interface=llm)

        chunks = await chunker.chunk_conversation("conv_1", "User: hello")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "hello")
        self.assertEqual(chunks[0].speaker, "user")

    async def test_chunker_uses_llm_repair_then_succeeds(self):
        llm = _FakeLLM(
            [
                "not json at all",
                '{"chunks":[{"content":"repaired","language":"en","labels":[],"speaker":"assistant","entities":[],"summary":"ok"}]}'
            ]
        )
        chunker = ConversationChunker(llm_interface=llm)

        chunks = await chunker.chunk_conversation("conv_2", "Assistant: fixed")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "repaired")
        self.assertEqual(chunks[0].speaker, "assistant")

    async def test_chunker_fails_fast_when_parse_and_repair_fail(self):
        llm = _FakeLLM([
            "not json",
            "still not json",
        ])
        chunker = ConversationChunker(llm_interface=llm)

        with self.assertRaises(RuntimeError) as ctx:
            await chunker.chunk_conversation("conv_3", "broken")

        self.assertIn("Dreaming A->B failed (no fallback)", str(ctx.exception))
        self.assertIn("provider=fake-provider", str(ctx.exception))

    def test_synthesizer_normalizes_list_payload(self):
        llm = _FakeLLM([])
        synthesizer = DreamingSynthesizer(llm_interface=llm)

        parsed = synthesizer._parse_llm_response(
            '[{"type":"TOPIC","title":"T","summary":"S","chunk_ids":["b1"],"entities":[],"insights":[],"related_clusters":[]}]'
        )

        self.assertIn("clusters", parsed)
        self.assertEqual(len(parsed["clusters"]), 1)

    async def test_synthesizer_fails_fast_when_parse_and_repair_fail(self):
        llm = _FakeLLM([
            "invalid",
            "invalid-repair",
        ])
        synthesizer = DreamingSynthesizer(llm_interface=llm)
        chunks = [
            BChunk(
                id="b1",
                parent_id="conv",
                chunk_type=ChunkType.SEMANTIC,
                content="x",
                labels=[],
                speaker="user",
                entities=[],
            )
        ]

        with self.assertRaises(RuntimeError) as ctx:
            await synthesizer.synthesize_chunks(chunks=chunks, session_id="conv")

        self.assertIn("Dreaming B->C failed (no fallback)", str(ctx.exception))
        self.assertIn("provider=fake-provider", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
