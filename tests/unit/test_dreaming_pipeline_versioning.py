"""Unit tests for Dreaming archive versioning and manifest lifecycle."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.dreaming.pipeline import DreamingPipeline
from app.dreaming.models import BChunk, CCluster, ChunkType, ClusterType


class _FakeLLM:
    def generate_response(self, query=None, context=None):
        return "{}"


class TestDreamingPipelineVersioning(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_creates_incrementing_versions_and_manifest_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = DreamingPipeline(
                llm_interface=_FakeLLM(),
                storage_path=Path(tmp),
            )

            async def fake_chunk(*args, **kwargs):
                conv_id = kwargs["conversation_id"]
                return [
                    BChunk(
                        id=f"b_{conv_id}_0",
                        parent_id=conv_id,
                        chunk_type=ChunkType.SEMANTIC,
                        content="message",
                        labels=["test"],
                        speaker="user",
                        entities=["MoJo"],
                    )
                ]

            async def fake_synth(*args, **kwargs):
                session_id = kwargs["session_id"]
                return [
                    CCluster(
                        id=f"c_{session_id}_0",
                        cluster_type=ClusterType.TOPIC,
                        content="summary",
                        related_chunks=[f"b_{session_id}_0"],
                        theme="topic",
                    )
                ]

            pipeline.chunker.chunk_conversation = fake_chunk
            pipeline.synthesizer.synthesize_chunks = fake_synth

            result_v1 = await pipeline.process_conversation(
                conversation_id="conv_ver",
                conversation_text="first",
                metadata={"original_text": "first"},
            )
            result_v2 = await pipeline.process_conversation(
                conversation_id="conv_ver",
                conversation_text="second",
                metadata={"original_text": "second"},
            )

            self.assertEqual(result_v1["status"], "success")
            self.assertEqual(result_v2["status"], "success")
            self.assertEqual(result_v1["stages"]["D_archive"]["version"], 1)
            self.assertEqual(result_v2["stages"]["D_archive"]["version"], 2)

            conv_dir = Path(tmp) / "conv_ver"
            archive_v1 = conv_dir / "archive_v1.json"
            archive_v2 = conv_dir / "archive_v2.json"
            self.assertTrue(archive_v1.exists())
            self.assertTrue(archive_v2.exists())

            with open(archive_v1, "r", encoding="utf-8") as f:
                v1_data = json.load(f)
            # Archive files are immutable snapshots and keep creation-time metadata.
            self.assertTrue(v1_data["metadata"]["is_latest"])
            self.assertEqual(v1_data["metadata"]["status"], "active")

            manifest = pipeline.get_manifest("conv_ver")
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest["latest_version"], 2)

            v1_lifecycle = manifest["versions"]["1"]
            v2_lifecycle = manifest["versions"]["2"]
            self.assertFalse(v1_lifecycle["is_latest"])
            self.assertEqual(v1_lifecycle["status"], "superseded")
            self.assertEqual(v1_lifecycle["storage_location"], "cold")
            self.assertTrue(v2_lifecycle["is_latest"])
            self.assertEqual(v2_lifecycle["status"], "active")
            self.assertEqual(v2_lifecycle["storage_location"], "hot")

            latest = pipeline.get_archive("conv_ver")
            explicit_v1 = pipeline.get_archive("conv_ver", version=1)
            self.assertEqual(latest["version"], 2)
            self.assertEqual(explicit_v1["version"], 1)

            latest_lifecycle = pipeline.get_archive_lifecycle("conv_ver")
            self.assertEqual(latest_lifecycle["version"], 2)
            self.assertEqual(latest_lifecycle["status"], "active")


if __name__ == "__main__":
    unittest.main()
