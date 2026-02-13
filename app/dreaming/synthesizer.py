"""
Dreaming Synthesizer - B→C Conversion

Clusters semantic chunks (B) into synthesized knowledge (C) using LLM.
Creates topic clusters, relationship maps, and timelines.

File: app/dreaming/synthesizer.py
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import defaultdict

from app.dreaming.models import BChunk, CCluster, ClusterType
from app.llm.llm_interface import LLMInterface


# Synthesis prompt for clustering B chunks into C clusters
SYNTHESIS_PROMPT = """You are a knowledge synthesis expert. Analyze the following semantic chunks and cluster them into meaningful topics and relationships.

CHUNKS:
{chunks_json}

INSTRUCTIONS:
1. Identify natural clusters:
   - TOPIC: Thematic groupings (e.g., "scheduler architecture", "error handling")
   - RELATIONSHIP: Connected concepts across chunks
   - TIMELINE: Temporal or sequential patterns
   - SUMMARY: High-level overviews

2. For each cluster, provide:
   - type: One of [TOPIC, RELATIONSHIP, TIMELINE, SUMMARY]
   - title: Concise cluster name
   - summary: 1-2 sentence synthesis
   - chunk_ids: List of chunk IDs in this cluster
   - entities: Key entities/concepts
   - insights: Novel connections or patterns discovered

3. Cross-reference clusters when concepts relate

OUTPUT FORMAT (JSON):
{
  "clusters": [
    {
      "type": "TOPIC",
      "title": "<cluster name>",
      "summary": "<synthesis of cluster content>",
      "chunk_ids": ["b_xxx_0", "b_xxx_2"],
      "entities": ["<entity1>", "<entity2>"],
      "insights": ["<insight1>", "<insight2>"],
      "related_clusters": []
    }
  ]
}

Return ONLY valid JSON, no additional text."""


class DreamingSynthesizer:
    """
    Synthesizes B chunks into C clusters using LLM

    Uses existing app/llm/llm_interface for provider abstraction
    """

    def __init__(
        self,
        llm_interface: LLMInterface,
        quality_level: str = "basic",
        logger=None
    ):
        """
        Initialize synthesizer

        Args:
            llm_interface: LLM interface instance
            quality_level: Target quality (basic/good/premium)
            logger: Optional logger instance
        """
        self.llm = llm_interface
        self.quality_level = quality_level
        self.logger = logger

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[Synthesizer] {message}")

    async def synthesize_chunks(
        self,
        chunks: List[BChunk],
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[CCluster]:
        """
        Synthesize B chunks into C clusters

        Args:
            chunks: List of B chunks to synthesize
            session_id: Session identifier (parent for clusters)
            metadata: Optional metadata

        Returns:
            List of C clusters
        """
        self._log(f"Synthesizing {len(chunks)} chunks into clusters")

        if not chunks:
            self._log("No chunks to synthesize", "warning")
            return []

        try:
            # Prepare chunks for LLM (simplified format)
            chunks_data = []
            for chunk in chunks:
                chunks_data.append({
                    "id": chunk.id,
                    "content": chunk.content[:200],  # Limit length
                    "labels": chunk.labels,
                    "speaker": chunk.speaker,
                    "entities": chunk.entities
                })

            # Format prompt
            chunks_json = json.dumps(chunks_data, indent=2, ensure_ascii=False)
            prompt = SYNTHESIS_PROMPT.format(chunks_json=chunks_json)

            # Call LLM
            response = self.llm.generate_response(query=prompt, context=None)

            # Parse response
            clusters_data = self._parse_llm_response(response)

            # Convert to CCluster objects
            c_clusters = self._create_c_clusters(
                session_id=session_id,
                clusters_data=clusters_data,
                source_chunks=chunks
            )

            self._log(f"Created {len(c_clusters)} C clusters")
            return c_clusters

        except Exception as e:
            self._log(f"Error in LLM synthesis: {e}", "error")
            self._log("Falling back to rule-based clustering", "warning")
            return self._fallback_clustering(chunks, session_id)

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM JSON response"""
        # Clean up response (remove markdown code blocks)
        response_clean = response.strip()
        if response_clean.startswith("```json"):
            response_clean = response_clean[7:]
        if response_clean.startswith("```"):
            response_clean = response_clean[3:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]
        response_clean = response_clean.strip()

        return json.loads(response_clean)

    def _create_c_clusters(
        self,
        session_id: str,
        clusters_data: Dict[str, Any],
        source_chunks: List[BChunk]
    ) -> List[CCluster]:
        """Create CCluster objects from LLM output"""
        c_clusters = []
        clusters = clusters_data.get("clusters", [])

        # Get LLM provider info for quality tracking
        llm_info = self._get_llm_info()

        for i, cluster_data in enumerate(clusters):
            # Generate cluster ID
            cluster_id = f"c_{session_id}_{i}"

            # Parse cluster type
            cluster_type_str = cluster_data.get("type", "TOPIC").upper()
            try:
                cluster_type = ClusterType[cluster_type_str]
            except KeyError:
                cluster_type = ClusterType.TOPIC

            # Create CCluster
            c_cluster = CCluster(
                id=cluster_id,
                cluster_type=cluster_type,
                content=cluster_data.get("summary", ""),  # Summary becomes content
                related_chunks=cluster_data.get("chunk_ids", []),
                related_clusters=cluster_data.get("related_clusters", []),
                theme=cluster_data.get("title", f"Cluster {i}"),
                confidence=0.9 if self.quality_level == "good" else 0.7,
                created_at=datetime.now()
            )

            # Add quality metadata
            if hasattr(c_cluster, '__dict__'):
                c_cluster.__dict__['quality_level'] = self.quality_level
                c_cluster.__dict__['needs_upgrade'] = (self.quality_level == "basic")
                c_cluster.__dict__['llm_used'] = llm_info.get("model")

            c_clusters.append(c_cluster)

        return c_clusters

    def _get_llm_info(self) -> Dict[str, Any]:
        """Get current LLM provider info"""
        try:
            if hasattr(self.llm, 'active_interface_name'):
                return {
                    "provider": self.llm.active_interface_name,
                    "model": "unknown"
                }
        except:
            pass

        return {"provider": "unknown", "model": "unknown"}

    def _fallback_clustering(
        self,
        chunks: List[BChunk],
        session_id: str
    ) -> List[CCluster]:
        """Simple rule-based clustering fallback if LLM fails"""
        self._log("Using rule-based fallback clustering", "warning")

        # Group by labels
        label_groups = defaultdict(list)
        for chunk in chunks:
            for label in chunk.labels:
                label_groups[label].append(chunk)

        # If no labels, create single cluster
        if not label_groups:
            label_groups["general"] = chunks

        c_clusters = []
        for i, (label, grouped_chunks) in enumerate(label_groups.items()):
            cluster_id = f"c_{session_id}_{i}_fallback"

            # Collect entities
            all_entities = []
            for chunk in grouped_chunks:
                all_entities.extend(chunk.entities)
            unique_entities = list(set(all_entities))

            c_cluster = CCluster(
                id=cluster_id,
                cluster_type=ClusterType.TOPIC,
                content=f"Chunks related to {label}",
                related_chunks=[c.id for c in grouped_chunks],
                theme=f"Topic: {label}",
                confidence=0.5,  # Low confidence for fallback
                created_at=datetime.now()
            )

            # Mark as low quality
            if hasattr(c_cluster, '__dict__'):
                c_cluster.__dict__['quality_level'] = "basic"
                c_cluster.__dict__['needs_upgrade'] = True
                c_cluster.__dict__['llm_used'] = "fallback"

            c_clusters.append(c_cluster)

        return c_clusters
