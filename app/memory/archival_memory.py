from typing import Dict, List, Any
import datetime
import uuid
import os
import json
import math
from app.memory.memory_page import MemoryPage

class ArchivalMemory:
    """
    Long-term vector-based memory storage
    Simplified implementation without Qdrant dependency
    """
    def __init__(self, embedding, collection_name: str = "memory", data_dir: str = ".archival_memory"):
        self.embedding = embedding
        self.collection_name = collection_name
        self.data_dir = data_dir
        
        # Initialize storage
        self.memories = []  # Stores documents and metadata
        self.vectors = []   # Stores corresponding embeddings
        
        # Create data directory if it doesn't exist
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load existing data if available
        self._load_data()
    
    def _load_data(self) -> None:
        """Load existing archival memory data"""
        memory_file = os.path.join(self.data_dir, f"{self.collection_name}.json")
        
        if os.path.exists(memory_file):
            try:
                with open(memory_file, 'r') as f:
                    data = json.load(f)
                    self.memories = data.get("memories", [])
                    self.vectors = data.get("vectors", [])
                print(f"Loaded {len(self.memories)} documents from archival memory")
            except Exception as e:
                print(f"Error loading archival memory: {e}")
                self.memories = []
                self.vectors = []
    
    def _save_data(self) -> None:
        """Save archival memory data to disk"""
        memory_file = os.path.join(self.data_dir, f"{self.collection_name}.json")
        
        try:
            data = {
                "memories": self.memories,
                "vectors": self.vectors,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(memory_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving archival memory: {e}")
    
    def store(self, text: str, metadata: Dict[str, Any]) -> str:
        """Store a memory in archival storage with embedding"""
        # Generate ID
        memory_id = str(uuid.uuid4())
        
        # Generate embedding
        embedding = self.embedding.get_text_embedding(text)
        
        # Store in memory
        memory = {
            "id": memory_id,
            "text": text,
            "metadata": metadata,
            "created_at": datetime.datetime.now().isoformat()
        }
        
        self.memories.append(memory)
        self.vectors.append(embedding)
        
        # Save periodically
        if len(self.memories) % 10 == 0:
            self._save_data()
        
        return memory_id
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant memories based on semantic similarity"""
        if not self.memories:
            return []
        
        # Generate query embedding
        query_embedding = self.embedding.get_text_embedding(query)
        
        # Calculate similarity scores
        scores = []
        for i, memory_embedding in enumerate(self.vectors):
            # Cosine similarity calculation
            similarity = self._cosine_similarity(query_embedding, memory_embedding)
            scores.append((i, similarity))
        
        # Sort by similarity (highest first)
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top results
        results = []
        for i, score in scores[:limit]:
            memory = self.memories[i].copy()
            memory["relevance_score"] = float(score)
            results.append(memory)
            
        return results
    
    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        # Calculate dot product
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        
        # Calculate magnitudes
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        
        # Calculate similarity
        if mag_a > 0 and mag_b > 0:
            return dot_product / (mag_a * mag_b)
        return 0.0
    
    def store_page(self, page: MemoryPage) -> str:
        """Archive a memory page"""
        # Convert page content to text for embedding
        if isinstance(page.content, dict):
            # For dictionaries with messages, extract text
            if "messages" in page.content and isinstance(page.content["messages"], list):
                text_parts = []
                for msg in page.content["messages"]:
                    if isinstance(msg, dict) and "content" in msg:
                        role = msg.get("role", "unknown")
                        text_parts.append(f"{role}: {msg['content']}")
                content_text = "\n".join(text_parts)
            else:
                # For other dictionaries, convert to JSON
                content_text = json.dumps(page.content)
        else:
            # For non-dict content, convert directly
            content_text = str(page.content)
        
        # Store with page metadata
        return self.store(
            text=content_text,
            metadata={
                "page_id": page.id,
                "page_type": page.page_type,
                "created_at": page.created_at,
                "access_count": page.access_count
            }
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "collection_name": self.collection_name,
            "memory_count": len(self.memories),
            "last_updated": datetime.datetime.now().isoformat()
        }