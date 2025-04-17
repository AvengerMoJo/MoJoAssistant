from typing import Dict, List, Any
import datetime
import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.memory.memory_page import MemoryPage

class ArchivalMemory:
    """
    Long-term vector-based memory storage
    Uses Qdrant as the vector database
    """
    def __init__(self, embedding, collection_name: str = "memory", embedding_dim: int = 384):
        # Initialize with in-memory Qdrant for simplicity
        # For production, use persistent storage
        self.client = QdrantClient(":memory:")
        self.collection_name = collection_name
        self.embedding = embedding
        self.embedding_dim = embedding_dim
        
        # Initialize embedding model (using smaller model for efficiency)
        # self.embedding = HuggingFaceEmbedding(
        #   model_name="all-MiniLM-L6-v2"
        # )
        
        # Create collection if it doesn't exist
        self._create_collection_if_not_exists()
    
    def _create_collection_if_not_exists(self) -> None:
        """Create the vector collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        collection_names = [collection.name for collection in collections]
        
        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
    
    def store(self, text: str, metadata: Dict[str, Any]) -> str:
        """Store a memory in archival storage with embedding"""
        # Generate ID
        memory_id = str(uuid.uuid4())
        
        # Generate embedding
        embedding = self.embedding.get_text_embedding(text)

        # Store in vector database
        point = PointStruct(
            id=memory_id,
            vector=embedding,
            payload={
                "text": text,
                "metadata": metadata,
                "created_at": datetime.datetime.now().isoformat()
            }
        )
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        
        return memory_id
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant memories based on semantic similarity"""
        # Generate query embedding
        query_embedding = self.embedding.get_text_embedding(query)
        
        # Search in vector database
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit
        )
        
        # Format results
        memories = []
        for result in results:
            memories.append({
                "id": result.id,
                "text": result.payload["text"],
                "metadata": result.payload["metadata"],
                "created_at": result.payload["created_at"],
                "relevance_score": result.score
            })
            
        return memories
    
    def store_page(self, page: MemoryPage) -> str:
        """Archive a memory page"""
        # Convert page content to text for embedding
        content_text = json.dumps(page.content)
        
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

