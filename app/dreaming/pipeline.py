"""
Dreaming Pipeline - A→B→C→D Executor

Orchestrates the full memory consolidation workflow:
- A: Raw conversation input
- B: Semantic chunking
- C: Synthesis and clustering
- D: Archival and versioning

File: app/dreaming/pipeline.py
"""

import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from app.dreaming.models import BChunk, CCluster
from app.dreaming.chunker import ConversationChunker
from app.dreaming.synthesizer import DreamingSynthesizer
from app.llm.llm_interface import LLMInterface


class DreamingPipeline:
    """
    Full A→B→C→D dreaming pipeline executor

    Transforms raw conversations into consolidated knowledge base
    """

    def __init__(
        self,
        llm_interface: LLMInterface,
        quality_level: str = "basic",
        storage_path: Optional[Path] = None,
        logger=None
    ):
        """
        Initialize pipeline

        Args:
            llm_interface: LLM interface instance
            quality_level: Target quality (basic/good/premium)
            storage_path: Path for storing D archives
            logger: Optional logger instance
        """
        self.llm = llm_interface
        self.quality_level = quality_level
        self.storage_path = storage_path or Path.home() / ".memory" / "dreams"
        self.logger = logger

        # Create storage directory
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.chunker = ConversationChunker(
            llm_interface=llm_interface,
            quality_level=quality_level,
            logger=logger
        )
        self.synthesizer = DreamingSynthesizer(
            llm_interface=llm_interface,
            quality_level=quality_level,
            logger=logger
        )

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[DreamingPipeline] {message}")

    def _archive_version_from_path(self, path: Path) -> Optional[int]:
        """Extract numeric version from archive filename like archive_v12.json."""
        match = re.match(r"archive_v(\d+)\.json$", path.name)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _get_archive_files_sorted(self, conv_dir: Path) -> List[Path]:
        """Get archive files sorted by numeric version ascending."""
        files = list(conv_dir.glob("archive_v*.json"))
        files_with_versions = []
        for f in files:
            version = self._archive_version_from_path(f)
            if version is not None:
                files_with_versions.append((version, f))
        files_with_versions.sort(key=lambda item: item[0])
        return [f for _, f in files_with_versions]

    def _manifest_path(self, conversation_id: str) -> Path:
        """Path to per-conversation manifest file."""
        return self.storage_path / conversation_id / "manifest.json"

    def _load_manifest(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Load manifest if present."""
        manifest_path = self._manifest_path(conversation_id)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            self._log(f"Failed to load manifest for {conversation_id}: {e}", "error")
        return None

    def get_manifest(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Public read-only manifest accessor.
        Returns existing manifest, or an in-memory bootstrap view when missing.
        """
        manifest = self._load_manifest(conversation_id)
        if manifest is not None:
            return manifest
        conv_dir = self.storage_path / conversation_id
        if not conv_dir.exists():
            return None
        return self._build_manifest_from_existing_archives(conversation_id)

    def _save_manifest(self, conversation_id: str, manifest: Dict[str, Any]) -> None:
        """Atomically save manifest for a conversation."""
        conv_dir = self.storage_path / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._manifest_path(conversation_id)
        temp_path = manifest_path.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        temp_path.replace(manifest_path)

    def _build_manifest_from_existing_archives(
        self, conversation_id: str
    ) -> Dict[str, Any]:
        """Bootstrap manifest from existing archive_v*.json files."""
        conv_dir = self.storage_path / conversation_id
        archive_files = self._get_archive_files_sorted(conv_dir)
        versions = [self._archive_version_from_path(p) for p in archive_files]
        versions = [v for v in versions if v is not None]
        latest = versions[-1] if versions else 0

        version_map: Dict[str, Any] = {}
        for v in versions:
            version_map[str(v)] = {
                "status": "active" if v == latest else "superseded",
                "storage_location": "hot" if v == latest else "cold",
                "is_latest": v == latest,
                "previous_version": (v - 1) if v > 1 else None,
                "supersedes_version": (v - 1) if v > 1 else None,
            }

        return {
            "conversation_id": conversation_id,
            "latest_version": latest,
            "updated_at": datetime.now().isoformat(),
            "versions": version_map,
        }

    def _get_or_init_manifest(
        self, conversation_id: str, persist_if_missing: bool = True
    ) -> Dict[str, Any]:
        """Get manifest, bootstrapping from existing archives if needed."""
        manifest = self._load_manifest(conversation_id)
        if manifest is not None:
            return manifest
        manifest = self._build_manifest_from_existing_archives(conversation_id)
        if persist_if_missing:
            self._save_manifest(conversation_id, manifest)
        return manifest

    def _update_manifest_for_new_version(
        self,
        conversation_id: str,
        new_version: int,
        previous_version: Optional[int],
    ) -> None:
        """Update lifecycle/lineage metadata in manifest for a newly created version."""
        manifest = self._get_or_init_manifest(conversation_id)
        versions = manifest.setdefault("versions", {})

        # Demote previous latest lifecycle in manifest (immutable archive files stay untouched).
        if previous_version is not None:
            prev_key = str(previous_version)
            prev = versions.get(prev_key, {})
            prev["is_latest"] = False
            prev["status"] = "superseded"
            prev["storage_location"] = "cold"
            prev["superseded_by_version"] = new_version
            prev["superseded_at"] = datetime.now().isoformat()
            versions[prev_key] = prev

        new_key = str(new_version)
        versions[new_key] = {
            "is_latest": True,
            "status": "active",
            "storage_location": "hot",
            "previous_version": previous_version,
            "supersedes_version": previous_version,
        }

        manifest["latest_version"] = new_version
        manifest["updated_at"] = datetime.now().isoformat()
        self._save_manifest(conversation_id, manifest)

    def _get_next_archive_version(self, conversation_id: str) -> int:
        """Return next archive version for a conversation (1-based)."""
        manifest = self._get_or_init_manifest(
            conversation_id, persist_if_missing=False
        )
        latest_version = int(manifest.get("latest_version", 0))
        return latest_version + 1

    def _get_latest_archive_path_and_version(
        self, conversation_id: str
    ) -> tuple[Optional[Path], Optional[int]]:
        """Return latest archive path and numeric version for a conversation."""
        conv_dir = self.storage_path / conversation_id
        if not conv_dir.exists():
            return None, None
        manifest = self._get_or_init_manifest(conversation_id)
        latest_version = int(manifest.get("latest_version", 0))
        if latest_version <= 0:
            archive_files = self._get_archive_files_sorted(conv_dir)
            if not archive_files:
                return None, None
            latest_path = archive_files[-1]
            latest_version = self._archive_version_from_path(latest_path)
            return latest_path, latest_version
        latest_path = conv_dir / f"archive_v{latest_version}.json"
        if not latest_path.exists():
            # Manifest may be stale; fallback to file scan.
            archive_files = self._get_archive_files_sorted(conv_dir)
            if not archive_files:
                return None, None
            latest_path = archive_files[-1]
            latest_version = self._archive_version_from_path(latest_path)
        return latest_path, latest_version

    def get_archive_lifecycle(
        self, conversation_id: str, version: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get lifecycle/lineage metadata for an archive version from manifest.
        If version is None, returns lifecycle for latest version.
        """
        manifest = self.get_manifest(conversation_id)
        if not manifest:
            return None

        if version is None:
            version = int(manifest.get("latest_version", 0))

        versions = manifest.get("versions", {})
        lifecycle = versions.get(str(version))
        if not lifecycle:
            return None

        return {
            "conversation_id": conversation_id,
            "version": version,
            **lifecycle,
        }

    async def process_conversation(
        self,
        conversation_id: str,
        conversation_text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a single conversation through A→B→C→D pipeline

        Args:
            conversation_id: Unique conversation identifier
            conversation_text: Raw conversation content (A)
            metadata: Optional metadata for the conversation

        Returns:
            Dict with processing results and paths to stored artifacts
        """
        self._log(f"Processing conversation: {conversation_id}")

        metadata = metadata or {}
        results = {
            "conversation_id": conversation_id,
            "quality_level": self.quality_level,
            "started_at": datetime.now().isoformat(),
            "stages": {}
        }

        try:
            # Stage 1: A→B (Chunking)
            self._log("Stage A→B: Chunking conversation")
            b_chunks = await self.chunker.chunk_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata=metadata
            )
            results["stages"]["B_chunks"] = {
                "count": len(b_chunks),
                "chunk_ids": [c.id for c in b_chunks]
            }
            self._log(f"Created {len(b_chunks)} B chunks")

            # Stage 2: B→C (Synthesis)
            self._log("Stage B→C: Synthesizing clusters")
            c_clusters = await self.synthesizer.synthesize_chunks(
                chunks=b_chunks,
                session_id=conversation_id,
                metadata=metadata
            )
            results["stages"]["C_clusters"] = {
                "count": len(c_clusters),
                "cluster_ids": [c.id for c in c_clusters],
                "types": [c.cluster_type.value for c in c_clusters]
            }
            self._log(f"Created {len(c_clusters)} C clusters")

            # Stage 3: C→D (Archival)
            self._log("Stage C→D: Archiving knowledge")
            _latest_path, latest_version = self._get_latest_archive_path_and_version(
                conversation_id
            )
            next_version = self._get_next_archive_version(conversation_id)
            d_archive = self._create_archive(
                conversation_id=conversation_id,
                version=next_version,
                previous_version=latest_version,
                b_chunks=b_chunks,
                c_clusters=c_clusters,
                metadata=metadata
            )

            # Save archive to disk
            archive_path = self._save_archive(d_archive)
            self._update_manifest_for_new_version(
                conversation_id=conversation_id,
                new_version=next_version,
                previous_version=latest_version,
            )
            results["stages"]["D_archive"] = {
                "archive_id": d_archive["id"],
                "path": str(archive_path),
                "version": d_archive["version"],
                "entities_count": len(d_archive["entities"]),
                "relationships_count": len(d_archive["relationships"]),
                "previous_version": d_archive["metadata"].get("previous_version"),
                "supersedes_version": d_archive["metadata"].get("supersedes_version"),
                "status": d_archive["metadata"].get("status"),
                "storage_location": d_archive["metadata"].get("storage_location"),
            }
            self._log(f"Archived to: {archive_path}")

            results["completed_at"] = datetime.now().isoformat()
            results["status"] = "success"

            return results

        except Exception as e:
            self._log(f"Pipeline error: {e}", "error")
            results["completed_at"] = datetime.now().isoformat()
            results["status"] = "failed"
            results["error"] = str(e)
            return results

    def _create_archive(
        self,
        conversation_id: str,
        version: int,
        previous_version: Optional[int],
        b_chunks: List[BChunk],
        c_clusters: List[CCluster],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create archive dictionary from B chunks and C clusters"""

        # Collect all entities and relationships
        all_entities = set()
        relationships = []

        for chunk in b_chunks:
            all_entities.update(chunk.entities)

        # Note: CCluster doesn't have entities field directly
        # Collect entities from chunks referenced by clusters
        for cluster in c_clusters:
            # Get entities from chunks in this cluster
            for chunk_id in cluster.related_chunks:
                chunk = next((c for c in b_chunks if c.id == chunk_id), None)
                if chunk:
                    all_entities.update(chunk.entities)

        # Create archive dictionary
        archive_id = f"d_{conversation_id}"
        archive = {
            "id": archive_id,
            "conversation_id": conversation_id,
            "version": version,
            "b_chunks": b_chunks,
            "c_clusters": c_clusters,
            "entities": list(all_entities),
            "relationships": relationships[:100],  # Limit relationships
            "metadata": {
                **metadata,
                "previous_version": previous_version,
                "supersedes_version": previous_version,
                "is_latest": True,
                "status": "active",
                "storage_location": "hot",
            },
            "quality_level": self.quality_level,
            "created_at": datetime.now()
        }

        return archive

    def _save_archive(self, archive: Dict[str, Any]) -> Path:
        """Save archive to disk as JSON"""

        # Create directory for this conversation
        conv_dir = self.storage_path / archive["conversation_id"]
        conv_dir.mkdir(parents=True, exist_ok=True)

        # Archive filename with version
        filename = f"archive_v{archive['version']}.json"
        archive_path = conv_dir / filename
        temp_path = conv_dir / f"{filename}.tmp"

        # Convert to JSON-serializable format
        archive_data = {
            "id": archive["id"],
            "conversation_id": archive["conversation_id"],
            "version": archive["version"],
            "quality_level": archive["quality_level"],
            "created_at": archive["created_at"].isoformat(),
            "entities": archive["entities"],
            "relationships": archive["relationships"],
            "metadata": archive["metadata"],
            "b_chunks": [
                {
                    "id": c.id,
                    "content": c.content,
                    "labels": c.labels,
                    "speaker": c.speaker,
                    "entities": c.entities,
                    "confidence": c.confidence
                }
                for c in archive["b_chunks"]
            ],
            "c_clusters": [
                {
                    "id": c.id,
                    "cluster_type": c.cluster_type.value,
                    "theme": c.theme,
                    "content": c.content,
                    "related_chunks": c.related_chunks,
                    "confidence": c.confidence
                }
                for c in archive["c_clusters"]
            ]
        }

        # Write to file
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)
        temp_path.replace(archive_path)

        return archive_path

    async def upgrade_quality(
        self,
        conversation_id: str,
        target_quality: str = "good"
    ) -> Dict[str, Any]:
        """
        Upgrade existing archive to higher quality

        Args:
            conversation_id: ID of conversation to upgrade
            target_quality: Target quality level (good/premium)

        Returns:
            Dict with upgrade results
        """
        self._log(f"Upgrading {conversation_id} to {target_quality} quality")

        # Load existing archive
        conv_dir = self.storage_path / conversation_id
        if not conv_dir.exists():
            raise ValueError(f"Archive not found for {conversation_id}")

        # Find latest version
        archive_files = self._get_archive_files_sorted(conv_dir)
        if not archive_files:
            raise ValueError(f"No archive files found for {conversation_id}")

        latest_archive_path = archive_files[-1]

        with open(latest_archive_path, 'r', encoding='utf-8') as f:
            archive_data = json.load(f)

        # Extract original conversation (if available in metadata)
        original_text = archive_data.get("metadata", {}).get("original_text", "")
        if not original_text:
            raise ValueError("Original text not found in archive metadata")

        # Re-process with higher quality
        old_quality = self.quality_level
        self.quality_level = target_quality

        # Update components
        self.chunker.quality_level = target_quality
        self.synthesizer.quality_level = target_quality

        try:
            results = await self.process_conversation(
                conversation_id=conversation_id,
                conversation_text=original_text,
                metadata=archive_data.get("metadata", {})
            )

            results["upgraded_from"] = old_quality
            results["upgraded_to"] = target_quality

            return results

        finally:
            # Restore quality level
            self.quality_level = old_quality
            self.chunker.quality_level = old_quality
            self.synthesizer.quality_level = old_quality

    def get_archive(self, conversation_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve archive from storage

        Args:
            conversation_id: ID of conversation
            version: Specific version to retrieve (None = latest)

        Returns:
            Archive data dict or None if not found
        """
        conv_dir = self.storage_path / conversation_id
        if not conv_dir.exists():
            return None

        if version is not None:
            archive_path = conv_dir / f"archive_v{version}.json"
            if not archive_path.exists():
                return None
        else:
            # Get latest version
            latest_path, _latest_version = self._get_latest_archive_path_and_version(
                conversation_id
            )
            if latest_path is None:
                return None
            archive_path = latest_path

        with open(archive_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_archives(self) -> List[Dict[str, Any]]:
        """List all available archives"""
        archives = []

        for conv_dir in self.storage_path.iterdir():
            if not conv_dir.is_dir():
                continue

            archive_files = self._get_archive_files_sorted(conv_dir)
            if not archive_files:
                continue

            # Get latest version info
            latest_path, latest_version = self._get_latest_archive_path_and_version(
                conv_dir.name
            )
            if latest_path is None:
                continue
            with open(latest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            manifest = self._load_manifest(conv_dir.name) or {}
            latest_meta = (
                manifest.get("versions", {}).get(str(latest_version), {})
                if latest_version is not None
                else {}
            )

            archives.append({
                "conversation_id": conv_dir.name,
                "latest_version": latest_version if latest_version is not None else data.get("version", 1),
                "quality_level": data.get("quality_level", "unknown"),
                "created_at": data.get("created_at"),
                "status": latest_meta.get("status", "unknown"),
                "storage_location": latest_meta.get("storage_location", "unknown"),
                "entities_count": len(data.get("entities", [])),
                "chunks_count": len(data.get("b_chunks", [])),
                "clusters_count": len(data.get("c_clusters", []))
            })

        return archives
