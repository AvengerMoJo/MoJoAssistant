"""
Conversation Chunker - A→B Conversion

Transforms raw conversations (A) into semantic chunks (B) using LLM.
Reuses existing app/llm/llm_interface infrastructure.

File: app/dreaming/chunker.py
"""

import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.dreaming.models import BChunk, ChunkType
from app.llm.llm_interface import LLMInterface


# Universal chunking prompt (works across languages)
CHUNKING_PROMPT = """You are a semantic analysis expert. Analyze the following conversation and break it into meaningful semantic chunks.

CONVERSATION:
{conversation_text}

INSTRUCTIONS:
1. Identify natural semantic boundaries (topic shifts, speaker turns, logical breaks)
2. Each chunk should be 100-800 tokens
3. Extract metadata for each chunk:
   - labels: List of topic tags (e.g., ["technical", "architecture", "billing"])
   - speaker: Who is speaking (user/assistant/system)
   - entities: Named entities mentioned (people, products, concepts)
   - summary: One-sentence summary of the chunk

IMPORTANT:
- Preserve the ORIGINAL language of each chunk (do not translate)
- Multi-lingual conversations: Keep each language as-is
- Detect language per chunk: "zh", "en", "ja", etc.

OUTPUT FORMAT (JSON):
{{
  "chunks": [
    {{
      "content": "<original text, unchanged>",
      "language": "<detected language code>",
      "labels": ["<tag1>", "<tag2>"],
      "speaker": "<user|assistant|system>",
      "entities": ["<entity1>", "<entity2>"],
      "summary": "<one-sentence summary>"
    }}
  ]
}}

Return ONLY valid JSON, no additional text."""


class ConversationChunker:
    """
    Chunks conversations into semantic pieces using LLM

    Uses existing app/llm/llm_interface for provider abstraction
    """

    def __init__(
        self,
        llm_interface: LLMInterface,
        quality_level: str = "basic",
        logger=None
    ):
        """
        Initialize chunker

        Args:
            llm_interface: LLM interface instance (from app/llm)
            quality_level: Target quality (basic/good/premium)
            logger: Optional logger instance
        """
        self.llm = llm_interface
        self.quality_level = quality_level
        self.logger = logger

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[Chunker] {message}")

    async def chunk_conversation(
        self,
        conversation_id: str,
        conversation_text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[BChunk]:
        """
        Chunk a single conversation into B chunks using LLM

        Args:
            conversation_id: A chunk ID (parent)
            conversation_text: Full conversation content
            metadata: Optional metadata from A chunk

        Returns:
            List of B chunks
        """
        self._log(f"Chunking conversation {conversation_id} ({len(conversation_text)} chars)")

        try:
            # Format prompt
            prompt = CHUNKING_PROMPT.format(conversation_text=conversation_text)

            # Call LLM via existing interface
            response = self.llm.generate_response(query=prompt, context=None)

            # Parse JSON response
            chunks_data = self._parse_llm_response(response)

            # Convert to BChunk objects
            b_chunks = self._create_b_chunks(
                parent_id=conversation_id,
                chunks_data=chunks_data,
                original_text=conversation_text
            )

            self._log(f"Created {len(b_chunks)} B chunks")
            return b_chunks

        except Exception as e:
            self._log(f"Error in LLM chunking: {e}", "error")
            self._log("Falling back to rule-based chunking", "warning")
            return self._fallback_chunking(conversation_id, conversation_text)

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM JSON response

        Args:
            response: Raw LLM output

        Returns:
            Parsed JSON dict
        """
        # Clean up response (remove markdown code blocks)
        response_clean = response.strip()
        if response_clean.startswith("```json"):
            response_clean = response_clean[7:]
        if response_clean.startswith("```"):
            response_clean = response_clean[3:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]
        response_clean = response_clean.strip()

        # Parse JSON
        return json.loads(response_clean)

    def _create_b_chunks(
        self,
        parent_id: str,
        chunks_data: Dict[str, Any],
        original_text: str
    ) -> List[BChunk]:
        """
        Create BChunk objects from LLM output

        Args:
            parent_id: Parent A chunk ID
            chunks_data: Parsed LLM response
            original_text: Original conversation text

        Returns:
            List of BChunk objects
        """
        b_chunks = []
        chunks = chunks_data.get("chunks", [])

        # Get LLM provider info for quality tracking
        llm_info = self._get_llm_info()

        for i, chunk_data in enumerate(chunks):
            # Generate chunk ID
            chunk_id = f"b_{parent_id}_{i}"

            # Calculate token position (rough estimate)
            token_start = i * 400  # Rough estimate
            token_end = token_start + len(chunk_data.get("content", "").split())

            # Create BChunk
            b_chunk = BChunk(
                id=chunk_id,
                parent_id=parent_id,
                chunk_type=ChunkType.SEMANTIC,
                content=chunk_data.get("content", ""),
                labels=chunk_data.get("labels", []),
                speaker=chunk_data.get("speaker", "unknown"),
                entities=chunk_data.get("entities", []),
                confidence=0.9 if self.quality_level == "good" else 0.7,
                token_range=(token_start, token_end),
                position_in_parent=i / len(chunks) if chunks else 0.0,
                embedding=None,  # TODO: Generate embeddings separately
                created_at=datetime.now()
            )

            # Add quality metadata (custom fields)
            if hasattr(b_chunk, '__dict__'):
                b_chunk.__dict__['quality_level'] = self.quality_level
                b_chunk.__dict__['needs_upgrade'] = (self.quality_level == "basic")
                b_chunk.__dict__['llm_used'] = llm_info.get("model")
                b_chunk.__dict__['language'] = chunk_data.get("language", "unknown")

            b_chunks.append(b_chunk)

        return b_chunks

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

    def _fallback_chunking(
        self,
        parent_id: str,
        text: str
    ) -> List[BChunk]:
        """
        Simple rule-based chunking fallback if LLM fails

        Args:
            parent_id: Parent A chunk ID
            text: Conversation text

        Returns:
            List of basic BChunks
        """
        self._log("Using rule-based fallback chunking", "warning")

        # Split on double newlines (paragraphs)
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        if not paragraphs:
            # If no paragraphs, just create one chunk for entire text
            paragraphs = [text]

        b_chunks = []
        for i, para in enumerate(paragraphs):
            chunk_id = f"b_{parent_id}_{i}_fallback"

            # Detect speaker from simple patterns
            speaker = "unknown"
            if para.lower().startswith(("user:", "human:")):
                speaker = "user"
            elif para.lower().startswith(("assistant:", "ai:")):
                speaker = "assistant"

            b_chunk = BChunk(
                id=chunk_id,
                parent_id=parent_id,
                chunk_type=ChunkType.SEMANTIC,
                content=para,
                labels=[],
                speaker=speaker,
                entities=[],
                confidence=0.5,  # Low confidence for fallback
                token_range=(i * 100, (i + 1) * 100),
                position_in_parent=i / len(paragraphs) if paragraphs else 0.0,
                embedding=None,
                created_at=datetime.now()
            )

            # Mark as low quality
            if hasattr(b_chunk, '__dict__'):
                b_chunk.__dict__['quality_level'] = "basic"
                b_chunk.__dict__['needs_upgrade'] = True
                b_chunk.__dict__['llm_used'] = "fallback"

            b_chunks.append(b_chunk)

        return b_chunks
