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


    async def test_repeated_process_v1_v2_v3(self):
        """Phase 5: Integration test for repeated processing on same conversation_id."""
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = DreamingPipeline(
                llm_interface=_FakeLLM(),
                storage_path=Path(tmp),
            )

            call_count = 0

            async def fake_chunk(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                conv_id = kwargs["conversation_id"]
                return [
                    BChunk(
                        id=f"b_{conv_id}_{call_count}",
                        parent_id=conv_id,
                        chunk_type=ChunkType.SEMANTIC,
                        content=f"message v{call_count}",
                        labels=["test"],
                        speaker="user",
                        entities=[f"entity_{call_count}"],
                    )
                ]

            async def fake_synth(*args, **kwargs):
                session_id = kwargs["session_id"]
                return [
                    CCluster(
                        id=f"c_{session_id}_{call_count}",
                        cluster_type=ClusterType.TOPIC,
                        content="summary",
                        related_chunks=[f"b_{session_id}_{call_count}"],
                        theme="topic",
                    )
                ]

            pipeline.chunker.chunk_conversation = fake_chunk
            pipeline.synthesizer.synthesize_chunks = fake_synth

            conv_id = "conv_v1v2v3"

            result_v1 = await pipeline.process_conversation(
                conversation_id=conv_id,
                conversation_text="first",
                metadata={"original_text": "first"},
            )
            result_v2 = await pipeline.process_conversation(
                conversation_id=conv_id,
                conversation_text="second",
                metadata={"original_text": "second"},
            )
            result_v3 = await pipeline.process_conversation(
                conversation_id=conv_id,
                conversation_text="third",
                metadata={"original_text": "third"},
            )

            # All succeed
            self.assertEqual(result_v1["status"], "success")
            self.assertEqual(result_v2["status"], "success")
            self.assertEqual(result_v3["status"], "success")

            # Version numbers increment
            self.assertEqual(result_v1["stages"]["D_archive"]["version"], 1)
            self.assertEqual(result_v2["stages"]["D_archive"]["version"], 2)
            self.assertEqual(result_v3["stages"]["D_archive"]["version"], 3)

            # All archive files exist
            conv_dir = Path(tmp) / conv_id
            self.assertTrue((conv_dir / "archive_v1.json").exists())
            self.assertTrue((conv_dir / "archive_v2.json").exists())
            self.assertTrue((conv_dir / "archive_v3.json").exists())

            # Manifest shows v3 as latest
            manifest = pipeline.get_manifest(conv_id)
            self.assertEqual(manifest["latest_version"], 3)

            # v1 and v2 are superseded/cold, v3 is active/hot
            self.assertEqual(manifest["versions"]["1"]["status"], "superseded")
            self.assertEqual(manifest["versions"]["1"]["storage_location"], "cold")
            self.assertEqual(manifest["versions"]["2"]["status"], "superseded")
            self.assertEqual(manifest["versions"]["2"]["storage_location"], "cold")
            self.assertEqual(manifest["versions"]["3"]["status"], "active")
            self.assertEqual(manifest["versions"]["3"]["storage_location"], "hot")

            # Default retrieval returns latest (v3)
            latest = pipeline.get_archive(conv_id)
            self.assertEqual(latest["version"], 3)

            # Explicit retrieval of all versions works
            for v in [1, 2, 3]:
                archive = pipeline.get_archive(conv_id, version=v)
                self.assertIsNotNone(archive)
                self.assertEqual(archive["version"], v)

    async def test_upgrade_quality_creates_new_version(self):
        """Phase 5: upgrade_quality creates a new version, not overwriting."""
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

            conv_id = "conv_upgrade"

            # Create v1 with original_text in metadata
            result_v1 = await pipeline.process_conversation(
                conversation_id=conv_id,
                conversation_text="original conversation",
                metadata={"original_text": "original conversation"},
            )
            self.assertEqual(result_v1["status"], "success")
            self.assertEqual(result_v1["stages"]["D_archive"]["version"], 1)

            # Upgrade quality — should create v2
            upgrade_result = await pipeline.upgrade_quality(conv_id, "good")
            self.assertEqual(upgrade_result["status"], "success")
            self.assertEqual(upgrade_result["stages"]["D_archive"]["version"], 2)
            self.assertEqual(upgrade_result["upgraded_from"], "basic")
            self.assertEqual(upgrade_result["upgraded_to"], "good")

            # Both versions exist on disk
            conv_dir = Path(tmp) / conv_id
            self.assertTrue((conv_dir / "archive_v1.json").exists())
            self.assertTrue((conv_dir / "archive_v2.json").exists())

            # v1 is superseded, v2 is active
            manifest = pipeline.get_manifest(conv_id)
            self.assertEqual(manifest["latest_version"], 2)
            self.assertEqual(manifest["versions"]["1"]["status"], "superseded")
            self.assertEqual(manifest["versions"]["2"]["status"], "active")

            # Default retrieval returns upgraded version
            latest = pipeline.get_archive(conv_id)
            self.assertEqual(latest["version"], 2)
            self.assertEqual(latest["quality_level"], "good")

    async def test_list_archives_exposes_status_and_version(self):
        """Phase 5: list_archives returns latest status and version fields."""
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

            # Create two conversations, second one with two versions
            await pipeline.process_conversation(
                conversation_id="conv_a",
                conversation_text="text a",
                metadata={"original_text": "text a"},
            )
            await pipeline.process_conversation(
                conversation_id="conv_b",
                conversation_text="text b v1",
                metadata={"original_text": "text b v1"},
            )
            await pipeline.process_conversation(
                conversation_id="conv_b",
                conversation_text="text b v2",
                metadata={"original_text": "text b v2"},
            )

            archives = pipeline.list_archives()
            self.assertEqual(len(archives), 2)

            by_id = {a["conversation_id"]: a for a in archives}

            # conv_a: version 1, active
            self.assertEqual(by_id["conv_a"]["latest_version"], 1)
            self.assertEqual(by_id["conv_a"]["status"], "active")
            self.assertEqual(by_id["conv_a"]["storage_location"], "hot")

            # conv_b: version 2, active
            self.assertEqual(by_id["conv_b"]["latest_version"], 2)
            self.assertEqual(by_id["conv_b"]["status"], "active")
            self.assertEqual(by_id["conv_b"]["storage_location"], "hot")

            # All have required fields
            for archive in archives:
                self.assertIn("quality_level", archive)
                self.assertIn("created_at", archive)
                self.assertIn("entities_count", archive)
                self.assertIn("chunks_count", archive)
                self.assertIn("clusters_count", archive)


if __name__ == "__main__":
    unittest.main()
