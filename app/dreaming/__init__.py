"""
Dreaming - Memory Consolidation System

Transforms raw conversations (A) into a perfect knowledge base through:
- B: Semantic chunking with rich metadata
- C: Global synthesis and clustering
- D: Archival and versioning

File: app/dreaming/__init__.py
"""

from app.dreaming.models import BChunk, CCluster, DArchive

__all__ = [
    'BChunk',
    'CCluster',
    'DArchive',
]
