"""
Hybrid Memory Service - Extends existing MemoryService with multi-model support
Avoids conflicts by using same codebase with optional multi-model features
"""
import os
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional
from app.services.memory_service import MemoryService
from app.memory.multi_model_storage import MultiModelEmbeddingStorage
from app.memory.simplified_embeddings import SimpleEmbedding

class HybridMemoryService(MemoryService):
    """
    Extends MemoryService with optional multi-model support
    Falls back to single-model behavior when multi-model disabled
    """
    
    def __init__(self, 
                 data_dir: str = ".memory", 
                 embedding_model: str = "BAAI/bge-m3",
                 embedding_backend: str = "huggingface",
                 embedding_device: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None,
                 multi_model_enabled: bool = False):
        
        # Initialize parent class (existing memory service)
        super().__init__(data_dir, embedding_model, embedding_backend, embedding_device, config)
        
        self.multi_model_enabled = multi_model_enabled
        self.multi_model_storage = None
        self.embedding_models: Dict[str, SimpleEmbedding] = {}
        
        if multi_model_enabled:
            self._setup_multi_model()
    
    def _setup_multi_model(self):
        """Setup multi-model storage and embedding models"""
        try:
            self.logger.info("Setting up multi-model embedding system...")
            
            # Initialize multi-model storage
            self.multi_model_storage = MultiModelEmbeddingStorage(self.data_dir)
            
            # Setup embedding models from config
            embedding_config = self.config.get('embedding_models', {})
            
            # Priority models to load
            priority_models = [
                ('bge-m3:1024', 'BAAI/bge-m3', 1024),
                ('gemma:768', 'google/embeddinggemma-300m', 768),
                ('gemma:256', 'google/embeddinggemma-300m', 256)
            ]
            
            for model_key, model_name, embedding_dim in priority_models:
                try:
                    # Don't reload the same model that parent class loaded
                    if model_name == self.embedding.model_name:
                        # Reuse existing embedding service
                        self.embedding_models[model_key] = self.embedding
                        self.logger.info(f"Reusing existing model: {model_key}")
                    else:
                        # Check if we already have this model loaded with a different dimension
                        existing_model = None
                        for existing_key, existing_model_instance in self.embedding_models.items():
                            try:
                                if (hasattr(existing_model_instance, 'model_name') and 
                                    existing_model_instance.model_name == model_name):
                                    existing_model = existing_model_instance
                                    self.logger.info(f"Reusing existing model {model_name} for {model_key}")
                                    break
                            except Exception:
                                continue
                        
                        if existing_model:
                            # Reuse the existing model instance
                            self.embedding_models[model_key] = existing_model
                        else:
                            # Load additional models
                            cache_dir = os.path.join(self.data_dir, "embedding_cache", model_key.replace(':', '_'))
                            self.embedding_models[model_key] = SimpleEmbedding(
                                backend="huggingface",
                                model_name=model_name,
                                embedding_dim=embedding_dim,
                                cache_dir=cache_dir
                            )
                            self.logger.info(f"Loaded additional model: {model_key}")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to load {model_key}: {e}")
            
            self.logger.info(f"Multi-model setup complete: {len(self.embedding_models)} models loaded")
            
        except Exception as e:
            self.logger.error(f"Multi-model setup failed: {e}")
            self.multi_model_enabled = False
    
    def add_user_message(self, message: str) -> None:
        """Add user message - uses multi-model if enabled"""
        if self.multi_model_enabled and self.multi_model_storage and self.embedding_models:
            # Store with multi-model system
            try:
                msg_id = self.multi_model_storage.store_conversation_message(
                    content=message,
                    message_type="user", 
                    embedding_models=self.embedding_models
                )
                self.logger.debug(f"Stored user message with multi-model: {msg_id}")
            except Exception as e:
                self.logger.warning(f"Multi-model storage failed, falling back to single-model: {e}")
                super().add_user_message(message)
        else:
            # Fall back to original single-model behavior
            super().add_user_message(message)
    
    def add_assistant_message(self, message: str) -> None:
        """Add assistant message - uses multi-model if enabled"""
        if self.multi_model_enabled and self.multi_model_storage and self.embedding_models:
            try:
                msg_id = self.multi_model_storage.store_conversation_message(
                    content=message,
                    message_type="assistant",
                    embedding_models=self.embedding_models
                )
                self.logger.debug(f"Stored assistant message with multi-model: {msg_id}")
            except Exception as e:
                self.logger.warning(f"Multi-model storage failed, falling back to single-model: {e}")
                super().add_assistant_message(message)
        else:
            super().add_assistant_message(message)
    
    def add_to_knowledge_base(self, document: str, metadata: Dict[str, Any] | None = None) -> None:
        """Add document - uses multi-model if enabled"""
        if metadata is None:
            metadata = {}
            
        if self.multi_model_enabled and self.multi_model_storage and self.embedding_models:
            try:
                doc_id = self.multi_model_storage.store_document(
                    content=document,
                    metadata=metadata,
                    embedding_models=self.embedding_models
                )
                self.logger.debug(f"Stored document with multi-model: {doc_id}")
            except Exception as e:
                self.logger.warning(f"Multi-model storage failed, falling back to single-model: {e}")
                super().add_to_knowledge_base(document, metadata)
        else:
            super().add_to_knowledge_base(document, metadata)
    
    def get_context_for_query(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """Get context - uses multi-model with parallel retrieval if enabled"""
        # Validate input parameters
        if not query or not isinstance(query, str) or query.strip() == "":
            self.logger.warning("Empty or invalid query provided")
            return []

        if not isinstance(max_items, int) or max_items <= 0:
            self.logger.warning(f"Invalid max_items: {max_items}, using default value 10")
            max_items = 10

        if self.multi_model_enabled and self.multi_model_storage and self.embedding_models:
            try:
                return asyncio.run(self._get_multi_model_context_parallel(query, max_items))
            except Exception as e:
                self.logger.warning(f"Multi-model parallel search failed, trying sequential: {e}")
                try:
                    return self._get_multi_model_context(query, max_items)
                except Exception as e2:
                    self.logger.warning(f"Multi-model search failed, falling back to single-model: {e2}")

        # Fall back to parent's optimized parallel retrieval
        return super().get_context_for_query(query, max_items)
    
    def _get_multi_model_context(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """Get context using multi-model system with fallback"""
        all_results: List[Any] = []
        
        # Try models in priority order
        model_priority = [
            'bge-m3:1024',
            'gemma:768', 
            'gemma:256'
        ]
        
        for model_key in model_priority:
            if model_key not in self.embedding_models:
                continue
                
            try:
                # Generate query embedding
                embedding_service = self.embedding_models[model_key]
                query_embedding = embedding_service.get_text_embedding(query)
                
                # Search conversations
                conv_results: List[Any] = []
                if self.multi_model_storage:
                    conv_results = self.multi_model_storage.search_conversations(
                        query_embedding, model_key, max_results=max_items
                    )
                
                # Search documents
                doc_results: List[Any] = []
                if self.multi_model_storage:
                    doc_results = self.multi_model_storage.search_documents(
                        query_embedding, model_key, max_results=max_items
                    )
                
                # Combine and format results
                combined = conv_results + doc_results
                if combined:
                    # Convert to expected format
                    formatted_results = []
                    for result in combined:
                        formatted_results.append({
                            "content": result["text_content"],
                            "source": result["source"],
                            "relevance_score": result["similarity_score"],
                            "model_used": result["model_used"],
                            "metadata": result.get("user_metadata", {})
                        })
                    
                    # Sort by relevance and limit
                    formatted_results.sort(key=lambda x: x["relevance_score"], reverse=True)
                    return formatted_results[:max_items]
                    
            except Exception as e:
                self.logger.warning(f"Search with {model_key} failed: {e}")
                continue
        
        # If all multi-model searches failed, fall back to single-model
        self.logger.warning("All multi-model searches failed, using single-model fallback")
        return super().get_context_for_query(query, max_items)

    async def _get_multi_model_context_parallel(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """Get context using parallel multi-model system"""
        # Try models in priority order
        model_priority = [
            'bge-m3:1024',
            'gemma:768',
            'gemma:256'
        ]

        # Find the first available model for embedding generation
        query_embedding = None
        embedding_service = None
        for model_key in model_priority:
            if model_key in self.embedding_models:
                try:
                    embedding_service = self.embedding_models[model_key]
                    query_embedding = embedding_service.get_text_embedding(query)
                    if query_embedding is not None:
                        break
                except Exception as e:
                    self.logger.warning(f"Failed to generate embedding with {model_key}: {e}")
                    continue

        if query_embedding is None:
            self.logger.warning("Could not generate query embedding with any multi-model")
            return []

        # Create parallel search tasks for all available models
        start_time = time.time()
        tasks = []
        for model_key in model_priority:
            if model_key in self.embedding_models:
                tasks.append(self._search_multi_model_async(query, model_key, max_items))

        # Execute all searches in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        search_time = time.time() - start_time

        # Merge and deduplicate results
        all_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.warning(f"Multi-model search failed for {model_priority[i] if i < len(model_priority) else 'unknown'}: {result}")
                continue
            if isinstance(result, list):
                all_results.extend(result)

        # Remove duplicates based on content
        seen_content = set()
        unique_results = []
        for result in all_results:
            content_key = str(result.get("content", ""))[:100]  # Use first 100 chars as key
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_results.append(result)

        # Sort by relevance and limit
        sorted_results = sorted(unique_results, key=lambda x: x.get("relevance_score", 0), reverse=True)
        final_results = sorted_results[:max_items]

        self.logger.debug(f"Parallel multi-model retrieval completed in {search_time:.3f}s, found {len(final_results)} unique items")
        return final_results

    async def _search_multi_model_async(self, query: str, model_key: str, max_items: int) -> List[Dict[str, Any]]:
        """Search with a specific model asynchronously"""
        def search_model():
            try:
                # Generate query embedding
                embedding_service = self.embedding_models[model_key]
                query_embedding = embedding_service.get_text_embedding(query)
                if query_embedding is None:
                    return []

                # Search conversations and documents
                conv_results = []
                doc_results = []

                if self.multi_model_storage:
                    conv_results = self.multi_model_storage.search_conversations(
                        query_embedding, model_key, max_results=max_items
                    )
                    doc_results = self.multi_model_storage.search_documents(
                        query_embedding, model_key, max_results=max_items
                    )

                # Combine and format results
                combined = conv_results + doc_results
                formatted_results = []
                for result in combined:
                    formatted_results.append({
                        "content": result["text_content"],
                        "source": result["source"],
                        "relevance_score": result["similarity_score"],
                        "model_used": result["model_used"],
                        "metadata": result.get("user_metadata", {})
                    })

                return formatted_results

            except Exception as e:
                self.logger.warning(f"Search with {model_key} failed: {e}")
                return []

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, search_model)

    def get_multi_model_stats(self) -> Dict[str, Any]:
        """Get statistics including multi-model info"""
        stats = super().get_memory_stats()
        
        if self.multi_model_enabled and self.multi_model_storage:
            try:
                model_counts = self.multi_model_storage.get_available_models()
                stats["multi_model"] = {
                    "enabled": True,
                    "loaded_models": list(self.embedding_models.keys()),
                    "model_content_counts": model_counts,
                    "total_multi_model_items": sum(model_counts.values())
                }
            except Exception as e:
                stats["multi_model"] = {"enabled": True, "error": str(e)}
        else:
            stats["multi_model"] = {"enabled": False}
        
        return stats
    
    def enable_multi_model(self) -> bool:
        """Enable multi-model support at runtime"""
        if not self.multi_model_enabled:
            self.multi_model_enabled = True
            self._setup_multi_model()
        return self.multi_model_enabled
    
    def disable_multi_model(self) -> bool:
        """Disable multi-model support (fall back to single-model)"""
        self.multi_model_enabled = False
        return True
    
    def list_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent conversations for management"""
        if self.multi_model_enabled and self.multi_model_storage:
            return self.multi_model_storage.list_recent_conversations(limit)
        else:
            # For single-model, we'd need to implement this in the base MemoryService
            # For now, return empty list with a note
            return []
    
    def remove_conversation_message(self, message_id: str) -> bool:
        """Remove a specific conversation message"""
        if self.multi_model_enabled and self.multi_model_storage:
            return self.multi_model_storage.remove_conversation_message(message_id)
        else:
            # For single-model, would need base MemoryService support
            self.logger.warning("Conversation removal only supported in multi-model mode")
            return False
    
    def remove_recent_conversations(self, count: int) -> int:
        """Remove the most recent N conversations"""
        if self.multi_model_enabled and self.multi_model_storage:
            return self.multi_model_storage.remove_recent_conversations(count)
        else:
            self.logger.warning("Conversation removal only supported in multi-model mode")
            return 0
    
    def list_recent_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent documents for management"""
        if self.multi_model_enabled and self.multi_model_storage:
            return self.multi_model_storage.list_recent_documents(limit)
        else:
            return []
    
    def remove_document(self, document_id: str) -> bool:
        """Remove a specific document"""
        if self.multi_model_enabled and self.multi_model_storage:
            return self.multi_model_storage.remove_document(document_id)
        else:
            self.logger.warning("Document removal only supported in multi-model mode")
            return False