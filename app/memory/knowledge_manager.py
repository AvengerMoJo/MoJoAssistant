from typing import Dict, List, Any, Tuple
import os
import json
import datetime
import uuid
import math
import re

class KnowledgeManager:
    """
    Document and knowledge management without LlamaIndex dependency
    Simple vector storage for documents with semantic search
    """
    def __init__(self, embedding, collection_name: str = "knowledge", data_dir: str = ".knowledge"):
        # Initialize with default settings
        self.embedding = embedding
        self.collection_name = collection_name
        self.data_dir = data_dir
        
        # Storage for documents and embeddings
        self.documents: List[Dict[str, Any]] = []  # Stores document text and metadata
        self.chunk_embeddings: List[Dict[str, Any]] = []  # Stores embeddings for document chunks
        
        # Create data directory if it doesn't exist
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load existing data if available
        self._load_data()
    
    def _load_data(self) -> None:
        """Load existing knowledge data"""
        knowledge_file = os.path.join(self.data_dir, f"{self.collection_name}.json")
        
        if os.path.exists(knowledge_file):
            try:
                with open(knowledge_file, 'r') as f:
                    data = json.load(f)
                    self.documents = data.get("documents", [])
                    self.chunk_embeddings = data.get("embeddings", [])
                print(f"📚 [KnowledgeManager] Loaded {len(self.documents)} documents from {knowledge_file}")
            except Exception as e:
                print(f"Error loading knowledge base: {e}")
                self.documents = []
                self.chunk_embeddings = []
    
    def _save_data(self) -> None:
        """Save knowledge data to disk"""
        knowledge_file = os.path.join(self.data_dir, f"{self.collection_name}.json")

        try:
            data = {
                "documents": self.documents,
                "embeddings": self.chunk_embeddings,
                "updated_at": datetime.datetime.now().isoformat()
            }

            # Write to temp file first, then rename (atomic operation)
            temp_file = knowledge_file + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic rename
            os.replace(temp_file, knowledge_file)

            print(f"✅ Saved {len(self.documents)} documents to {knowledge_file}")

        except Exception as e:
            print(f"❌ Error saving knowledge base to {knowledge_file}: {e}")
            import traceback
            traceback.print_exc()
            raise  # Re-raise so we know save failed
    
    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 100) -> List[str]:
        """
        Split text into chunks of approximately chunk_size characters with overlap
        
        Args:
            text: Text to chunk
            chunk_size: Target chunk size in characters
            overlap: Overlap between chunks in characters
            
        Returns:
            List[str]: List of text chunks
        """
        if len(text) <= chunk_size:
            return [text]
        
        # Try to split on paragraph breaks first
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        
        if max(len(p) for p in paragraphs) <= chunk_size:
            # If all paragraphs are smaller than chunk_size, combine them
            chunks = []
            current_chunk = ""
            
            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= chunk_size:
                    if current_chunk:
                        current_chunk += "\n\n" + para
                    else:
                        current_chunk = para
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = para
            
            if current_chunk:
                chunks.append(current_chunk)
                
            return chunks
        
        # If we have large paragraphs, split on sentences
        chunks = []
        current_chunk = ""
        
        # Simple sentence splitting - not perfect but works for most cases
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for sentence in sentences:
            if len(sentence) > chunk_size:
                # Handle very long sentences by splitting them
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                
                # Split long sentence into chunks
                for i in range(0, len(sentence), chunk_size - overlap):
                    chunks.append(sentence[i:i + chunk_size])
            elif len(current_chunk) + len(sentence) + 1 <= chunk_size:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
            else:
                chunks.append(current_chunk)
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks
    
    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]] | None = None):
        """Add documents to the knowledge base"""
        if metadatas is None:
            metadatas = [{}] * len(documents)
            
        for i, (doc, metadata) in enumerate(zip(documents, metadatas)):
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Split document into chunks for better retrieval
            chunks = self._chunk_text(doc)
            
            # Generate embeddings for each chunk
            chunk_embeddings = self.embedding.get_batch_embeddings(chunks)
            
            # Store document with chunks
            document = {
                "id": doc_id,
                "text": doc,
                "chunks": chunks,
                "metadata": metadata,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            self.documents.append(document)
            
            # Store embeddings for each chunk with reference to parent doc
            for j, embedding in enumerate(chunk_embeddings):
                self.chunk_embeddings.append({
                    "doc_id": doc_id,
                    "chunk_index": j,
                    "embedding": embedding
                })
        
        # Save to disk
        self._save_data()
    
    def query(self, query_text: str, similarity_top_k: int = 3) -> List[Tuple[str, float]]:
        """Query the knowledge base"""
        if not self.chunk_embeddings:
            return []
            
        # Generate query embedding
        query_embedding = self.embedding.get_text_embedding(query_text)
        
        # Calculate similarity with all chunks
        chunk_scores = []
        for i, chunk_data in enumerate(self.chunk_embeddings):
            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, chunk_data["embedding"])
            chunk_scores.append((i, similarity))
        
        # Sort by similarity (highest first)
        chunk_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Get top results while avoiding duplicates from same document
        results = []
        seen_docs: set[str] = set()
        
        for i, score in chunk_scores:
            chunk_data = self.chunk_embeddings[i]
            doc_id = chunk_data["doc_id"]
            
            # Skip if we already have a chunk from this document
            if doc_id in seen_docs and len(seen_docs) >= similarity_top_k:
                continue
                
            # Find the document and chunk
            for doc in self.documents:
                if doc["id"] == doc_id:
                    chunk_index = chunk_data["chunk_index"]
                    
                    if 0 <= chunk_index < len(doc["chunks"]):
                        chunk_text = doc["chunks"][chunk_index]
                        results.append((chunk_text, float(score)))
                        seen_docs.add(doc_id)
                        break
            
            # Stop if we have enough results
            if len(results) >= similarity_top_k:
                break
        
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "collection_name": self.collection_name,
            "document_count": len(self.documents),
            "chunk_count": len(self.chunk_embeddings),
            "last_updated": datetime.datetime.now().isoformat()
        }
