"""
Dreaming Data Models

Data structures for A→B→C→D memory consolidation pipeline.

File: app/dreaming/models.py
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum
import json


class ChunkType(Enum):
    """Type of B chunk"""
    SEMANTIC = "semantic"  # Topic/idea boundaries
    SPEAKER_TURN = "speaker_turn"  # Each speaker's contribution
    ENTITY = "entity"  # Named entity occurrence
    RELATIONSHIP = "relationship"  # Connection between entities


class ClusterType(Enum):
    """Type of C cluster"""
    TOPIC = "topic"  # Grouped by topic/theme
    RELATIONSHIP = "relationship"  # Explicit connections
    SUMMARY = "summary"  # High-level overview
    TIMELINE = "timeline"  # Chronological progression


class ArchiveStatus(Enum):
    """Status of D archive"""
    SUPERSEDED = "superseded"  # Replaced by newer version
    DUPLICATE = "duplicate"  # Exact or near-duplicate content
    OBSOLETE = "obsolete"  # Outdated information
    HISTORICAL = "historical"  # Kept for reference only


@dataclass
class BChunk:
    """
    Deconstructed semantic chunk (B)

    Created from raw conversation data (A) with rich metadata
    """

    # Required fields
    id: str
    parent_id: str  # Link to source A chunk
    chunk_type: ChunkType
    content: str

    # Metadata
    labels: List[str] = field(default_factory=list)
    speaker: Optional[str] = None  # user/assistant/system
    entities: List[str] = field(default_factory=list)
    confidence: float = 1.0  # AI confidence (0-1)

    # Position tracking
    token_range: tuple[int, int] = (0, 0)  # (start, end) in parent
    position_in_parent: float = 0.0  # Relative position (0-1)

    # Embedding
    embedding: Optional[List[float]] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        data = asdict(self)
        data['chunk_type'] = self.chunk_type.value
        data['created_at'] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BChunk':
        """Create from dictionary"""
        data['chunk_type'] = ChunkType(data['chunk_type'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class CCluster:
    """
    Synthesized cluster (C)

    Global consolidated view combining multiple B chunks
    """

    # Required fields
    id: str
    cluster_type: ClusterType
    content: str  # Summary or consolidated content

    # Relationships
    related_chunks: List[str] = field(default_factory=list)  # B chunk IDs
    related_clusters: List[str] = field(default_factory=list)  # Other C IDs

    # Metadata
    theme: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    confidence: float = 1.0

    # Temporal span
    time_span_start: Optional[datetime] = None
    time_span_end: Optional[datetime] = None

    # Contradiction resolution
    contradictions_resolved: List[str] = field(default_factory=list)

    # Embedding
    embedding: Optional[List[float]] = None

    # Version tracking
    version: int = 1

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        data = asdict(self)
        data['cluster_type'] = self.cluster_type.value
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        if self.time_span_start:
            data['time_span_start'] = self.time_span_start.isoformat()
        if self.time_span_end:
            data['time_span_end'] = self.time_span_end.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CCluster':
        """Create from dictionary"""
        data['cluster_type'] = ClusterType(data['cluster_type'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        if data.get('time_span_start'):
            data['time_span_start'] = datetime.fromisoformat(data['time_span_start'])
        if data.get('time_span_end'):
            data['time_span_end'] = datetime.fromisoformat(data['time_span_end'])
        return cls(**data)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class DArchive:
    """
    Archived data (D)

    Stores old/superseded C clusters with versioning
    """

    # Required fields
    id: str
    archive_type: str  # 'cluster', 'chunk', etc.
    status: ArchiveStatus
    reason: str  # Why archived

    # Version pointers
    original_id: str  # Original C or B ID
    new_version_id: Optional[str] = None  # Replacement ID (if superseded)
    version: int = 1

    # Storage metadata
    archived_at: datetime = field(default_factory=datetime.now)
    storage_location: str = "cold"  # hot/warm/cold
    embedding_removed: bool = True  # Removed from search index

    # Snapshot
    content: Dict[str, Any] = field(default_factory=dict)  # Full original data

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        data = asdict(self)
        data['status'] = self.status.value
        data['archived_at'] = self.archived_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DArchive':
        """Create from dictionary"""
        data['status'] = ArchiveStatus(data['status'])
        data['archived_at'] = datetime.fromisoformat(data['archived_at'])
        return cls(**data)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class DreamingStats:
    """Statistics for dreaming pipeline execution"""

    # Input counts
    a_chunks_processed: int = 0

    # Output counts
    b_chunks_created: int = 0
    b_chunks_updated: int = 0
    c_clusters_created: int = 0
    c_clusters_updated: int = 0
    d_archives_created: int = 0

    # Errors
    errors: List[str] = field(default_factory=list)

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data
