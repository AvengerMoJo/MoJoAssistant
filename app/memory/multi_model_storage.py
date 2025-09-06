"""
Multi-Model Embedding Storage System
Stores text + embeddings from multiple models with dynamic retrieval
"""
import json
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

class MultiModelEmbeddingStorage:
    """Stores text with embeddings from multiple models"""
    
    def __init__(self, data_dir: str = ".memory"):
        self.data_dir = data_dir
        self.conversations_file = os.path.join(data_dir, "conversations_multi_model.json")
        self.documents_file = os.path.join(data_dir, "knowledge_multi_model.json") 
        
        # Load existing data
        self.conversations = self._load_data(self.conversations_file)
        self.documents = self._load_data(self.documents_file)
    
    def _load_data(self, file_path: str) -> List[Dict[str, Any]]:
        """Load data from JSON file"""
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
        return []
    
    def _save_data(self, data: List[Dict[str, Any]], file_path: str):
        """Save data to JSON file"""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def store_conversation_message(self, content: str, message_type: str, 
                                 embedding_models: Dict[str, Any]) -> str:
        """
        Store conversation message with text + multiple embeddings
        
        Args:
            content: Raw text content (always preserved)
            message_type: "user" or "assistant"  
            embedding_models: {"model_name:dim": embedding_service_instance}
        
        Returns:
            message_id: Unique ID for this message
        """
        message_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.conversations)}"
        
        # Generate embeddings from all available models
        embeddings = {}
        model_versions = {}
        
        for model_key, embedding_service in embedding_models.items():
            try:
                embedding = embedding_service.get_text_embedding(content)
                embeddings[model_key] = embedding
                model_versions[model_key] = embedding_service.model_version
                print(f"✅ Generated embedding for {model_key}: {len(embedding)} dims")
            except Exception as e:
                print(f"❌ Failed to generate embedding for {model_key}: {e}")
        
        # Store message with all embeddings
        message_entry = {
            "message_id": message_id,
            "text_content": content,  # Always preserve original text
            "message_type": message_type,
            "embeddings": embeddings,
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "model_versions": model_versions,
                "available_models": list(embeddings.keys())
            }
        }
        
        self.conversations.append(message_entry)
        self._save_data(self.conversations, self.conversations_file)
        
        return message_id
    
    def store_document(self, content: str, metadata: Dict[str, Any],
                      embedding_models: Dict[str, Any]) -> str:
        """Store document with text + multiple embeddings"""
        doc_id = f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.documents)}"
        
        # Generate embeddings from all available models
        embeddings = {}
        model_versions = {}
        
        for model_key, embedding_service in embedding_models.items():
            try:
                embedding = embedding_service.get_text_embedding(content)
                embeddings[model_key] = embedding
                model_versions[model_key] = embedding_service.model_version
            except Exception as e:
                print(f"Failed to generate embedding for {model_key}: {e}")
        
        doc_entry = {
            "document_id": doc_id,
            "text_content": content,  # Always preserve original text
            "embeddings": embeddings,
            "user_metadata": metadata,
            "system_metadata": {
                "created_at": datetime.now().isoformat(),
                "model_versions": model_versions,
                "available_models": list(embeddings.keys())
            }
        }
        
        self.documents.append(doc_entry)
        self._save_data(self.documents, self.documents_file)
        
        return doc_id
    
    def search_conversations(self, query_embedding: List[float], model_key: str, 
                           max_results: int = 10, similarity_threshold: float = 0.3) -> List[Dict[str, Any]]:
        """
        Search conversations using specific model embeddings
        
        Args:
            query_embedding: Query vector from specific model
            model_key: Which model's embeddings to use (e.g. "gemma:768")
            max_results: Max number of results
            similarity_threshold: Minimum similarity score
        """
        results = []
        
        for msg in self.conversations:
            # Check if this message has embeddings from the requested model
            if model_key not in msg.get("embeddings", {}):
                continue
                
            msg_embedding = msg["embeddings"][model_key]
            
            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, msg_embedding)
            
            if similarity >= similarity_threshold:
                results.append({
                    "message_id": msg["message_id"],
                    "text_content": msg["text_content"],
                    "message_type": msg["message_type"], 
                    "similarity_score": similarity,
                    "source": "conversation",
                    "model_used": model_key
                })
        
        # Sort by similarity score
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:max_results]
    
    def search_documents(self, query_embedding: List[float], model_key: str,
                        max_results: int = 10, similarity_threshold: float = 0.3) -> List[Dict[str, Any]]:
        """Search documents using specific model embeddings"""
        results = []
        
        for doc in self.documents:
            if model_key not in doc.get("embeddings", {}):
                continue
                
            doc_embedding = doc["embeddings"][model_key]
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            
            if similarity >= similarity_threshold:
                results.append({
                    "document_id": doc["document_id"],
                    "text_content": doc["text_content"],
                    "user_metadata": doc["user_metadata"],
                    "similarity_score": similarity,
                    "source": "knowledge_base",
                    "model_used": model_key
                })
        
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:max_results]
    
    def add_embedding_to_existing_content(self, embedding_models: Dict[str, Any]):
        """
        Add embeddings from new models to existing text content
        This allows upgrading to new models without losing old data
        """
        print("Adding new model embeddings to existing conversations...")
        
        for msg in self.conversations:
            for model_key, embedding_service in embedding_models.items():
                # Skip if already has this model's embedding
                if model_key in msg.get("embeddings", {}):
                    continue
                
                try:
                    # Generate embedding for existing text
                    embedding = embedding_service.get_text_embedding(msg["text_content"])
                    
                    # Add to existing embeddings
                    if "embeddings" not in msg:
                        msg["embeddings"] = {}
                    msg["embeddings"][model_key] = embedding
                    
                    # Update model versions
                    if "model_versions" not in msg["metadata"]:
                        msg["metadata"]["model_versions"] = {}
                    msg["metadata"]["model_versions"][model_key] = embedding_service.model_version
                    msg["metadata"]["available_models"] = list(msg["embeddings"].keys())
                    
                    print(f"✅ Added {model_key} embedding to message {msg['message_id']}")
                    
                except Exception as e:
                    print(f"❌ Failed to add {model_key} embedding to {msg['message_id']}: {e}")
        
        # Save updated conversations
        self._save_data(self.conversations, self.conversations_file)
        
        # Do the same for documents
        print("Adding new model embeddings to existing documents...")
        
        for doc in self.documents:
            for model_key, embedding_service in embedding_models.items():
                if model_key in doc.get("embeddings", {}):
                    continue
                
                try:
                    embedding = embedding_service.embed_text(doc["text_content"])
                    
                    if "embeddings" not in doc:
                        doc["embeddings"] = {}
                    doc["embeddings"][model_key] = embedding
                    
                    if "model_versions" not in doc["system_metadata"]:
                        doc["system_metadata"]["model_versions"] = {}
                    doc["system_metadata"]["model_versions"][model_key] = embedding_service.model_version
                    doc["system_metadata"]["available_models"] = list(doc["embeddings"].keys())
                    
                    print(f"✅ Added {model_key} embedding to document {doc['document_id']}")
                    
                except Exception as e:
                    print(f"❌ Failed to add {model_key} embedding to {doc['document_id']}: {e}")
        
        # Save updated documents  
        self._save_data(self.documents, self.documents_file)
    
    def get_available_models(self) -> Dict[str, int]:
        """Get count of content that has each model's embeddings"""
        model_counts = {}
        
        # Check conversations
        for msg in self.conversations:
            for model_key in msg.get("embeddings", {}):
                model_counts[model_key] = model_counts.get(model_key, 0) + 1
        
        # Check documents
        for doc in self.documents:
            for model_key in doc.get("embeddings", {}):
                model_counts[model_key] = model_counts.get(model_key, 0) + 1
        
        return model_counts
    
    def list_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent conversations with basic info for management"""
        recent = self.conversations[-limit:] if len(self.conversations) > limit else self.conversations
        return [{
            "message_id": msg["message_id"],
            "message_type": msg["message_type"],
            "text_preview": msg["text_content"][:100] + "..." if len(msg["text_content"]) > 100 else msg["text_content"],
            "created_at": msg["metadata"]["created_at"]
        } for msg in reversed(recent)]
    
    def remove_conversation_message(self, message_id: str) -> bool:
        """Remove a specific conversation message by ID"""
        original_count = len(self.conversations)
        self.conversations = [msg for msg in self.conversations if msg["message_id"] != message_id]
        
        if len(self.conversations) < original_count:
            self._save_data(self.conversations, self.conversations_file)
            return True
        return False
    
    def remove_recent_conversations(self, count: int) -> int:
        """Remove the most recent N conversation messages"""
        if count >= len(self.conversations):
            removed = len(self.conversations)
            self.conversations.clear()
        else:
            removed = count
            self.conversations = self.conversations[:-count]
        
        self._save_data(self.conversations, self.conversations_file)
        return removed
    
    def list_recent_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent documents with basic info for management"""
        recent = self.documents[-limit:] if len(self.documents) > limit else self.documents
        return [{
            "document_id": doc["document_id"],
            "text_preview": doc["text_content"][:100] + "..." if len(doc["text_content"]) > 100 else doc["text_content"],
            "user_metadata": doc["user_metadata"],
            "created_at": doc["system_metadata"]["created_at"]
        } for doc in reversed(recent)]
    
    def remove_document(self, document_id: str) -> bool:
        """Remove a specific document by ID"""
        original_count = len(self.documents)
        self.documents = [doc for doc in self.documents if doc["document_id"] != document_id]
        
        if len(self.documents) < original_count:
            self._save_data(self.documents, self.documents_file)
            return True
        return False
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if len(vec1) != len(vec2):
            return 0.0
            
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(a * a for a in vec2) ** 0.5
        
        if magnitude1 == 0.0 or magnitude2 == 0.0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)