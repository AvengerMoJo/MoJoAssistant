"""
Embedding Migration Tool

Migrate vectors from one embedding model to another.
Supports re-embedding documents with a new model and dimension mapping.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_path

logger = logging.getLogger(__name__)


class EmbeddingMigration:
    """
    Migrate embedding data between different models.

    Handles:
    - Re-embedding documents with a new model
    - Dimension mapping (e.g., 1024 -> 768)
    - Backup of original data
    - Progress tracking
    """

    def __init__(
        self,
        source_model: str,
        target_model: str,
        source_backend: str = "huggingface",
        target_backend: str = "huggingface",
        data_dir: Optional[str] = None,
    ):
        self.source_model = source_model
        self.target_model = target_model
        self.source_backend = source_backend
        self.target_backend = target_backend
        self.data_dir = data_dir or get_memory_path()
        self.backup_dir = os.path.join(self.data_dir, "migration_backup")

    def migrate(
        self,
        collections: Optional[List[str]] = None,
        batch_size: int = 100,
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the migration.

        Args:
            collections: Specific collections to migrate (None = all)
            batch_size: Number of documents to process at once
            create_backup: Whether to backup before migration

        Returns:
            Migration results with counts and any errors
        """
        from mojo_memory.memory.simplified_embeddings import SimpleEmbedding
        from mojo_memory.embeddings.registry import create_backend

        results = {
            "total_documents": 0,
            "migrated": 0,
            "errors": [],
            "collections_processed": [],
        }

        # Create source and target embedding instances
        source_embed = SimpleEmbedding(
            backend=self.source_backend,
            model_name=self.source_model,
        )
        target_embed = SimpleEmbedding(
            backend=self.target_backend,
            model_name=self.target_model,
        )

        # Get collections to migrate
        if collections is None:
            collections = self._discover_collections()

        # Create backup if requested
        if create_backup:
            self._create_backup(collections)

        # Migrate each collection
        for collection_name in collections:
            try:
                count = self._migrate_collection(
                    collection_name,
                    source_embed,
                    target_embed,
                    batch_size,
                )
                results["collections_processed"].append(collection_name)
                results["migrated"] += count
                results["total_documents"] += count
                logger.info(f"Migrated {count} documents in '{collection_name}'")
            except Exception as e:
                error_msg = f"Failed to migrate '{collection_name}': {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)

        return results

    def _discover_collections(self) -> List[str]:
        """Discover all collections in the data directory."""
        collections = []
        embeddings_dir = os.path.join(self.data_dir, "embeddings")
        if os.path.exists(embeddings_dir):
            for item in os.listdir(embeddings_dir):
                item_path = os.path.join(embeddings_dir, item)
                if os.path.isdir(item_path):
                    collections.append(item)
        return collections

    def _migrate_collection(
        self,
        collection_name: str,
        source_embed: Any,
        target_embed: Any,
        batch_size: int,
    ) -> int:
        """Migrate a single collection."""
        # Load documents from collection
        documents = self._load_collection_documents(collection_name)
        if not documents:
            return 0

        # Re-embed documents in batches
        migrated_count = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            texts = [doc.get("content", "") for doc in batch]

            # Get new embeddings
            try:
                new_embeddings = target_embed.get_batch_embeddings(texts)
            except Exception as e:
                logger.warning(f"Batch embedding failed, falling back to single: {e}")
                new_embeddings = []
                for text in texts:
                    try:
                        new_embeddings.append(target_embed.get_text_embedding(text))
                    except Exception:
                        new_embeddings.append([])

            # Update documents with new embeddings
            for doc, embedding in zip(batch, new_embeddings):
                if embedding:
                    doc["embedding"] = embedding
                    doc["model_version"] = f"{self.target_backend}:{self.target_model}"
                    migrated_count += 1

            # Save batch
            self._save_collection_batch(collection_name, batch)

        return migrated_count

    def _load_collection_documents(self, collection_name: str) -> List[Dict[str, Any]]:
        """Load documents from a collection."""
        collection_dir = os.path.join(self.data_dir, "embeddings", collection_name)
        documents = []

        if not os.path.exists(collection_dir):
            return documents

        for filename in os.listdir(collection_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(collection_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        doc = json.load(f)
                        doc["_filename"] = filename
                        documents.append(doc)
                except Exception as e:
                    logger.warning(f"Failed to load {filepath}: {e}")

        return documents

    def _save_collection_batch(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
    ) -> None:
        """Save a batch of documents back to the collection."""
        collection_dir = os.path.join(self.data_dir, "embeddings", collection_name)
        os.makedirs(collection_dir, exist_ok=True)

        for doc in documents:
            filename = doc.pop("_filename", None)
            if filename:
                filepath = os.path.join(collection_dir, filename)
                try:
                    with open(filepath, "w") as f:
                        json.dump(doc, f)
                except Exception as e:
                    logger.warning(f"Failed to save {filepath}: {e}")

    def _create_backup(self, collections: List[str]) -> None:
        """Create a backup of collections before migration."""
        os.makedirs(self.backup_dir, exist_ok=True)

        for collection_name in collections:
            source_dir = os.path.join(self.data_dir, "embeddings", collection_name)
            if os.path.exists(source_dir):
                backup_path = os.path.join(self.backup_dir, collection_name)
                if os.path.exists(backup_path):
                    shutil.rmtree(backup_path)
                shutil.copytree(source_dir, backup_path)
                logger.info(f"Backed up '{collection_name}' to {backup_path}")

    def rollback(self, collections: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Rollback a migration by restoring from backup.

        Args:
            collections: Specific collections to rollback (None = all)

        Returns:
            Rollback results
        """
        results = {
            "restored": [],
            "errors": [],
        }

        if collections is None:
            collections = os.listdir(self.backup_dir) if os.path.exists(self.backup_dir) else []

        for collection_name in collections:
            backup_path = os.path.join(self.backup_dir, collection_name)
            target_path = os.path.join(self.data_dir, "embeddings", collection_name)

            if not os.path.exists(backup_path):
                results["errors"].append(f"No backup found for '{collection_name}'")
                continue

            try:
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                shutil.copytree(backup_path, target_path)
                results["restored"].append(collection_name)
                logger.info(f"Restored '{collection_name}' from backup")
            except Exception as e:
                results["errors"].append(f"Failed to restore '{collection_name}': {e}")

        return results


def migrate_embeddings(
    source_model: str,
    target_model: str,
    source_backend: str = "huggingface",
    target_backend: str = "huggingface",
    collections: Optional[List[str]] = None,
    batch_size: int = 100,
    create_backup: bool = True,
) -> Dict[str, Any]:
    """
    Convenience function to run embedding migration.

    Usage:
        from app.memory.embedding_migration import migrate_embeddings
        results = migrate_embeddings("BAAI/bge-m3", "text-embedding-3-small")
    """
    migration = EmbeddingMigration(
        source_model=source_model,
        target_model=target_model,
        source_backend=source_backend,
        target_backend=target_backend,
    )
    return migration.migrate(
        collections=collections,
        batch_size=batch_size,
        create_backup=create_backup,
    )
