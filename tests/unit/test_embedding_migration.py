"""Unit tests for EmbeddingMigration."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.memory.embedding_migration import EmbeddingMigration, migrate_embeddings


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory with test embeddings."""
    # Create embeddings directory structure
    embeddings_dir = tmp_path / "embeddings" / "test_collection"
    embeddings_dir.mkdir(parents=True)

    # Create test documents
    for i in range(5):
        doc = {
            "id": f"doc_{i}",
            "content": f"Test document {i} content",
            "embedding": [0.1] * 768,
            "model_version": "huggingface:BAAI/bge-m3",
        }
        (embeddings_dir / f"doc_{i}.json").write_text(json.dumps(doc))

    return str(tmp_path)


class TestEmbeddingMigration:
    def test_init(self, temp_data_dir):
        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )
        assert migration.source_model == "BAAI/bge-m3"
        assert migration.target_model == "text-embedding-3-small"

    def test_discover_collections(self, temp_data_dir):
        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )
        collections = migration._discover_collections()
        assert "test_collection" in collections

    def test_load_collection_documents(self, temp_data_dir):
        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )
        docs = migration._load_collection_documents("test_collection")
        assert len(docs) == 5
        assert all("content" in doc for doc in docs)

    def test_create_backup(self, temp_data_dir):
        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )
        migration._create_backup(["test_collection"])
        backup_path = Path(temp_data_dir) / "migration_backup" / "test_collection"
        assert backup_path.exists()
        assert len(list(backup_path.glob("*.json"))) == 5

    @patch("mojo_memory.memory.simplified_embeddings.SimpleEmbedding")
    def test_migrate_collection(self, mock_simple_embedding, temp_data_dir):
        # Mock the embedding instances
        mock_source = MagicMock()
        mock_target = MagicMock()
        mock_simple_embedding.side_effect = [mock_source, mock_target]

        # Mock batch embeddings
        mock_target.get_batch_embeddings.return_value = [[0.2] * 512] * 5

        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )

        count = migration._migrate_collection(
            "test_collection",
            mock_source,
            mock_target,
            batch_size=10,
        )
        assert count == 5

    @patch("mojo_memory.memory.simplified_embeddings.SimpleEmbedding")
    def test_migrate_with_backup(self, mock_simple_embedding, temp_data_dir):
        mock_source = MagicMock()
        mock_target = MagicMock()
        mock_simple_embedding.side_effect = [mock_source, mock_target]
        mock_target.get_batch_embeddings.return_value = [[0.2] * 512] * 5

        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )

        results = migration.migrate(
            collections=["test_collection"],
            create_backup=True,
        )
        assert results["migrated"] == 5
        assert len(results["errors"]) == 0
        assert "test_collection" in results["collections_processed"]

        # Verify backup was created
        backup_path = Path(temp_data_dir) / "migration_backup" / "test_collection"
        assert backup_path.exists()

    @patch("mojo_memory.memory.simplified_embeddings.SimpleEmbedding")
    def test_rollback(self, mock_simple_embedding, temp_data_dir):
        mock_source = MagicMock()
        mock_target = MagicMock()
        mock_simple_embedding.side_effect = [mock_source, mock_target]
        mock_target.get_batch_embeddings.return_value = [[0.2] * 512] * 5

        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=temp_data_dir,
        )

        # Run migration
        migration.migrate(
            collections=["test_collection"],
            create_backup=True,
        )

        # Rollback
        results = migration.rollback(collections=["test_collection"])
        assert "test_collection" in results["restored"]
        assert len(results["errors"]) == 0

        # Verify documents were restored
        docs = migration._load_collection_documents("test_collection")
        assert len(docs) == 5
        # Check that original embeddings are restored
        for doc in docs:
            assert len(doc.get("embedding", [])) == 768

    def test_empty_collection(self, tmp_path):
        # Create empty collection
        embeddings_dir = tmp_path / "embeddings" / "empty_collection"
        embeddings_dir.mkdir(parents=True)

        migration = EmbeddingMigration(
            source_model="BAAI/bge-m3",
            target_model="text-embedding-3-small",
            data_dir=str(tmp_path),
        )

        docs = migration._load_collection_documents("empty_collection")
        assert len(docs) == 0
