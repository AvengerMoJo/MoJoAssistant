from typing import Dict, List, Any, Optional, Union
import datetime
import json
import os
import re
from collections import Counter
import math
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.memory.simplified_embeddings import SimpleEmbedding
from app.memory.working_memory import WorkingMemory
from app.memory.active_memory import ActiveMemory
from app.memory.archival_memory import ArchivalMemory
from app.memory.knowledge_manager import KnowledgeManager
from app.memory.memory_page import MemoryPage
from app.config.logging_config import get_logger, log_memory_operation, log_embedding_operation, log_error_with_context


class MemoryService:
    """
    Unified memory management system integrating all memory tiers
    with enhanced embedding capabilities
    """
    def __init__(self, 
                 data_dir: str = ".memory", 
                 embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe",
                 embedding_backend: str = "huggingface",
                 embedding_device: str | None = None,
                 config: Dict[str, Any] | None = None):
        """
        Initialize the memory manager
        
        Args:
            data_dir: Directory for storing memory data
            embedding_model: Name of the embedding model to use
            embedding_backend: Embedding backend type ('huggingface', 'local', 'api', 'random')
            embedding_device: Device to run embedding model on ('cpu', 'cuda', etc.)
            config: Additional configuration options
        """
        # Initialize logger
        self.logger = get_logger(__name__)
        
        # Set up data directory
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.logger.info(f"Initializing MemoryService with data_dir={data_dir}")
        
        # Process config
        self.config = config or {}
        
        # Set up embedding system
        self._setup_embedding(
            model_name=embedding_model,
            backend=embedding_backend,
            device=embedding_device or "cpu"
        )
        
        # Initialize memory components
        self.working_memory = WorkingMemory(
            max_tokens=self.config.get('working_memory_max_tokens', 4000)
        )
        
        self.active_memory = ActiveMemory(
            max_pages=self.config.get('active_memory_max_pages', 20)
        )
        
        self.archival_memory = ArchivalMemory(
            embedding=self.embedding, 
            data_dir=os.path.join(data_dir, "archival")
        )
        
        self.knowledge_manager = KnowledgeManager(
            embedding=self.embedding, 
            data_dir=os.path.join(data_dir, "knowledge")
        )
        
        # Track the current conversation
        self.current_conversation: List[Dict[str, Any]] = []
        self.current_context: List[Dict[str, Any]] = []
        
        # Configure memory transition thresholds
        self.archival_promotion_threshold = self.config.get('archival_promotion_threshold', 0.6)
        self.memory_paging_threshold = self.config.get('memory_paging_threshold', 0.5)
        
        self.logger.info(f"Memory manager initialized with {self.embedding.backend} embeddings using model: {self.embedding.model_name}")
    
    def _setup_embedding(self, model_name: str, backend: str, device: str | None = None) -> None:
        """
        Set up the embedding system
        
        Args:
            model_name: Name of the embedding model to use
            backend: Embedding backend type
            device: Device to run embedding model on
        """
        # Initialize embedding system
        self.embedding = SimpleEmbedding(
            backend=backend,
            model_name=model_name,
            device=device or "cpu",
            cache_dir=os.path.join(self.data_dir, "embedding_cache")
        )
    
    def add_user_message(self, message: str) -> None:
        """Add a user message to memory"""
        self.working_memory.add_message("user", message)
        self.current_conversation.append({"role": "user", "content": message})
        
        # Check if working memory is getting full
        if self.working_memory.is_full():
            self._page_out_oldest_messages()
    
    def add_assistant_message(self, message: str) -> None:
        """Add an assistant message to memory"""
        self.working_memory.add_message("assistant", message)
        self.current_conversation.append({"role": "assistant", "content": message})
        
        # Check if working memory is getting full
        if self.working_memory.is_full():
            self._page_out_oldest_messages()
    
    def _page_out_oldest_messages(self, num_messages: int = 10) -> None:
        """
        Move oldest messages from working memory to active memory
        Implements the memory paging concept from MemGPT
        """
        messages = self.working_memory.get_messages()
        
        if len(messages) <= num_messages:
            return
            
        # Get oldest messages to page out
        oldest_messages = self.working_memory.remove_messages(num_messages)

        
        # Create a page in active memory
        page_content = {
            "messages": [{"role": msg.type, "content": msg.content} for msg in oldest_messages],
            "timestamp": datetime.datetime.now().isoformat()
        }
        # self.active_memory.add_page(page_content, "conversation")
        # new_memory = WorkingMemory(max_tokens=self.working_memory.max_tokens)
        # for msg in messages[num_messages:]:
        #     new_memory.add_message(msg.type, msg.content)
        # self.working_memory = new_memory

        # Add to active memory with archive callback
        page_id = self.active_memory.add_page(
            page_content, 
            "conversation",
            archive_callback=self._archive_page_callback
        )
        
        log_memory_operation("page_out", {
            "num_messages": num_messages,
            "page_id": page_id,
            "working_memory_size": len(self.working_memory.get_messages())
        }, self.logger)
    
    def end_conversation(self) -> None:
        """
        End the current conversation and store it in active memory
        """
        if not self.current_conversation:
            return
            
        # Generate a simple summary
        summary = self._generate_conversation_summary()
        
        # Store full conversation in active memory
        page_content = {
            "messages": self.current_conversation,
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": summary
        }
        page_id = self.active_memory.add_page(
            page_content, 
            "conversation_complete",
            archive_callback=self._archive_page_callback
        )
        
        # Also store in archival memory for long-term retrieval
        conversation_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in self.current_conversation])
        self.archival_memory.store(
            text=conversation_text,
            metadata={
                "type": "conversation",
                "timestamp": datetime.datetime.now().isoformat(),
                "message_count": len(self.current_conversation),
                "summary": summary,
                "active_memory_page_id": page_id,
                "content_structure": ["messages", "timestamp", "summary"]
            }
        )
        
        # Clear working memory and current conversation tracking
        self.working_memory.clear()
        self.current_conversation = []
        self.current_context = []
    
    def _generate_conversation_summary(self) -> str:
        """
        Generate a summary of the current conversation
        Uses a simple keyword extraction approach
        """
        if len(self.current_conversation) <= 2:
            return "Brief conversation with insufficient content for summarization"
            
        user_messages = [msg["content"] for msg in self.current_conversation if msg["role"] == "user"]
        
        if not user_messages:
            return "No user messages found in conversation"
            
        # Simple topic extraction
        # Extract words, ignoring common stop words
        stop_words = set([
            "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
            "at", "from", "by", "with", "about", "against", "between", "into",
            "through", "during", "before", "after", "above", "below", "to", "of",
            "in", "out", "on", "off", "over", "under", "again", "further", "then",
            "once", "here", "there", "when", "where", "why", "how", "all", "any",
            "both", "each", "few", "more", "most", "other", "some", "such", "no",
            "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s",
            "t", "can", "will", "just", "don", "should", "now", "d", "ll", "m",
            "o", "re", "ve", "y", "am", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "having", "do", "does", "did", "doing",
            "would", "could", "should", "shall", "might", "may", "must", "for",
            "that", "what", "which", "who", "whom", "this", "these", "those", "i",
            "me", "my", "mine", "myself", "you", "your", "yours", "yourself"
        ])
        
        words = []
        for msg in user_messages:
            # Extract words, convert to lowercase, remove punctuation
            msg_words = re.findall(r'\b[a-zA-Z]{4,}\b', msg.lower())
            for word in msg_words:
                if word not in stop_words:
                    words.append(word)
        
        # Count occurrences
        word_counter = Counter(words)
        
        # Get most common words as topics
        top_words = word_counter.most_common(5)
        main_topics = [word for word, count in top_words if count >= 2]
        
        if main_topics:
            return f"Conversation about {', '.join(main_topics)}"
        else:
            return "General conversation without specific focus"
    
    def get_context_for_query(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """
        Synchronous version of get_context_for_query
        Retrieve relevant context from all memory tiers to support the current query
        """
        # Validate input parameters
        if not query or not isinstance(query, str) or query.strip() == "":
            self.logger.warning("Empty or invalid query provided")
            return []

        if not isinstance(max_items, int) or max_items <= 0:
            self.logger.warning(f"Invalid max_items: {max_items}, using default value 10")
            max_items = 10

        # Run synchronous retrieval
        try:
            return self._get_context_sequential(query, max_items)
        except Exception as e:
            self.logger.warning(f"Sequential retrieval failed: {e}")
            return []

    async def get_context_for_query_async(self, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        """
        Async version of get_context_for_query that can be called from async contexts
        Retrieve relevant context from all memory tiers to support the current query
        Uses parallel async retrieval for optimal performance
        """
        # Validate input parameters
        if not query or not isinstance(query, str) or query.strip() == "":
            self.logger.warning("Empty or invalid query provided")
            return []

        if not isinstance(max_items, int) or max_items <= 0:
            self.logger.warning(f"Invalid max_items: {max_items}, using default value 10")
            max_items = 10

        # Run async retrieval and return results
        try:
            return await self._get_context_parallel(query, max_items)
        except Exception as e:
            self.logger.warning(f"Parallel retrieval failed, falling back to sequential: {e}")
            return self._get_context_sequential(query, max_items)

    async def _get_context_parallel(self, query: str, max_items: int) -> List[Dict[str, Any]]:
        """
        Parallel async context retrieval from all memory tiers
        """
        query_embedding = self.embedding.get_text_embedding(query, prompt_name='query')
        if query_embedding is None:
            self.logger.warning("Could not generate embedding for the query. Skipping context search.")
            return []

        # Create tasks for parallel execution
        tasks = [
            self._search_working_memory_async(query_embedding),
            self._search_active_memory_async(query_embedding),
            self._search_archival_memory_async(query, max_items),
            self._search_knowledge_base_async(query, max_items)
        ]

        # Execute all searches in parallel
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        search_time = time.time() - start_time

        # Merge results from all tiers
        context_items = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tier_names = ["working", "active", "archival", "knowledge"]
                self.logger.warning(f"Search failed for {tier_names[i]} memory: {result}")
                continue
            if isinstance(result, list):
                context_items.extend(result)

        # Sort by relevance and limit results
        sorted_context = sorted(context_items, key=lambda x: float(str(x.get("relevance", 0.0))), reverse=True)
        final_context = sorted_context[:max_items]

        # Store current context and log performance
        self.current_context = final_context
        self.logger.debug(f"Parallel retrieval completed in {search_time:.3f}s, found {len(final_context)} items")

        return final_context

    async def _search_working_memory_async(self, query_embedding) -> List[Dict[str, Any]]:
        """Search working memory asynchronously"""
        def search_working():
            working_context = []
            working_messages = self.working_memory.get_messages()

            for msg in working_messages:
                msg_embedding = self.embedding.get_text_embedding(msg.content)
                if not msg_embedding:
                    continue

                similarity = self.embedding._get_similarity(query_embedding, msg_embedding)
                if similarity > 0.3:
                    working_context.append({
                        "source": "working_memory",
                        "content": msg.content,
                        "relevance": similarity
                    })
            return working_context

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, search_working)

    async def _search_active_memory_async(self, query_embedding) -> List[Dict[str, Any]]:
        """Search active memory asynchronously"""
        def search_active():
            context_items = []
            active_pages = self.active_memory.pages

            for page in active_pages:
                if isinstance(page.content, dict):
                    content_text = json.dumps(page.content)
                else:
                    content_text = str(page.content)

                page_embedding = self.embedding.get_text_embedding(content_text)
                if not page_embedding:
                    continue

                similarity = self.embedding._get_similarity(query_embedding, page_embedding)
                if similarity > 0.3:
                    context_items.append({
                        "source": "active_memory",
                        "content": page.content,
                        "page_id": page.id,
                        "relevance": similarity
                    })
                    page.access()
            return context_items

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, search_active)

    async def _search_archival_memory_async(self, query: str, max_items: int) -> List[Dict[str, Any]]:
        """Search archival memory asynchronously"""
        def search_archival():
            context_items = []
            archival_results = self.archival_memory.search(query, limit=max_items)

            for result in archival_results:
                relevance_score = result.get("relevance_score", 0)

                # Try to promote highly relevant memories
                if relevance_score > 0.8:
                    promoted_page_id = self._promote_archival_to_active(result, relevance_score)
                    if promoted_page_id:
                        result["promoted_to_active"] = promoted_page_id

                context_items.append({
                    "source": "archival_memory",
                    "content": result["text"],
                    "metadata": result["metadata"],
                    "relevance": result["relevance_score"]
                })
            return context_items

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, search_archival)

    async def _search_knowledge_base_async(self, query: str, max_items: int) -> List[Dict[str, Any]]:
        """Search knowledge base asynchronously"""
        def search_knowledge():
            context_items = []
            knowledge_results = self.knowledge_manager.query(query, similarity_top_k=max_items)

            for text, score in knowledge_results:
                context_items.append({
                    "source": "knowledge_base",
                    "content": text,
                    "relevance": score
                })
            return context_items

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, search_knowledge)

    def _get_context_sequential(self, query: str, max_items: int) -> List[Dict[str, Any]]:
        """
        Fallback sequential context retrieval (original implementation)
        """
        context_items = []
        query_embedding = self.embedding.get_text_embedding(query, prompt_name='query')

        if query_embedding is None:
            self.logger.warning("Could not generate embedding for the query. Skipping context search.")
            return []

        # 1. Search working memory
        working_messages = self.working_memory.get_messages()
        for msg in working_messages:
            msg_embedding = self.embedding.get_text_embedding(msg.content)
            if not msg_embedding:
                continue

            similarity = self.embedding._get_similarity(query_embedding, msg_embedding)
            if similarity > 0.3:
                context_items.append({
                    "source": "working_memory",
                    "content": msg.content,
                    "relevance": similarity
                })

        # 2. Search active memory pages
        active_pages = self.active_memory.pages
        for page in active_pages:
            if isinstance(page.content, dict):
                content_text = json.dumps(page.content)
            else:
                content_text = str(page.content)

            page_embedding = self.embedding.get_text_embedding(content_text)
            if not page_embedding:
                continue

            similarity = self.embedding._get_similarity(query_embedding, page_embedding)
            if similarity > 0.3:
                context_items.append({
                    "source": "active_memory",
                    "content": page.content,
                    "page_id": page.id,
                    "relevance": similarity
                })
                page.access()

        # 3. Search archival memory
        archival_results = self.archival_memory.search(query, limit=max_items)
        for result in archival_results:
            relevance_score = result.get("relevance_score", 0)
            if relevance_score > 0.8:
                promoted_page_id = self._promote_archival_to_active(result, relevance_score)
                if promoted_page_id:
                    result["promoted_to_active"] = promoted_page_id

            context_items.append({
                "source": "archival_memory",
                "content": result["text"],
                "metadata": result["metadata"],
                "relevance": result["relevance_score"]
            })

        # 4. Search knowledge base
        knowledge_results = self.knowledge_manager.query(query, similarity_top_k=max_items)
        for text, score in knowledge_results:
            context_items.append({
                "source": "knowledge_base",
                "content": text,
                "relevance": score
            })

        # Sort by relevance
        sorted_context = sorted(context_items, key=lambda x: float(str(x.get("relevance", 0.0))), reverse=True)
        self.current_context = sorted_context[:max_items]
        return self.current_context

    def update_memory_from_response(self, query: str, response: str) -> None:
        """
        Update memory based on the query and response
        Extract entities, update relationships, etc.
        """
        # In a full implementation, this would extract entities and key information
        # For now, we'll just track the interaction
        self.add_user_message(query)
        self.add_assistant_message(response)
    
    def add_to_knowledge_base(self, document: str, metadata: Dict[str, Any] | None = None) -> None:
        """
        Add a document to the knowledge base
        """
        if metadata is None:
            metadata = {}
        
        self.knowledge_manager.add_documents([document], [metadata])
    
    def save_memory_state(self, file_path: str) -> None:
        """
        Serialize and save the current memory state to disk
        """
        memory_state = {
            "working_memory": {
                "messages": [
                    {"role": msg.type, "content": msg.content} 
                    for msg in self.working_memory.get_messages()
                ],
                "token_count": self.working_memory.token_count
            },
            "active_memory": {
                "pages": [page.to_dict() for page in self.active_memory.pages]
            },
            "current_conversation": self.current_conversation,
            "embedding_info": self.embedding.get_model_info(),
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        with open(file_path, "w") as f:
            json.dump(memory_state, f, indent=2)
    
    def load_memory_state(self, file_path: str) -> bool:
        """
        Load memory state from disk
        """
        try:
            with open(file_path, "r") as f:
                memory_state = json.load(f)
            
            # Restore working memory
            self.working_memory = WorkingMemory()
            for msg in memory_state["working_memory"]["messages"]:
                self.working_memory.add_message(msg["role"], msg["content"])
            
            # Restore active memory
            self.active_memory = ActiveMemory()
            for page_dict in memory_state["active_memory"]["pages"]:
                from app.memory.memory_page import MemoryPage
                page = MemoryPage(
                    content=page_dict["content"],
                    page_type=page_dict["page_type"]
                )
                page.id = page_dict["id"]
                page.created_at = page_dict["created_at"]
                page.last_accessed = page_dict["last_accessed"]
                page.access_count = page_dict["access_count"]
                self.active_memory.pages.append(page)
            
            # Restore current conversation
            self.current_conversation = memory_state["current_conversation"]
            
            # Check if we need to update the embedding model
            if "embedding_info" in memory_state:
                saved_model = memory_state["embedding_info"].get("model_name")
                saved_backend = memory_state["embedding_info"].get("backend")
                
                current_model = self.embedding.model_name
                current_backend = self.embedding.backend
                
                if saved_model != current_model or saved_backend != current_backend:
                    self.logger.info(f"Current embedding model ({current_model}) differs from saved state ({saved_model})")
            
            return True
        except Exception as e:
            log_error_with_context(e, {
                "operation": "load_memory_state",
                "file_path": file_path
            }, self.logger)
            return False
    
    def set_embedding_model(self, model_name: str, backend: str | None = None, device: str | None = None) -> bool:
        """
        Change the embedding model
        
        Args:
            model_name: Name of the model to use
            backend: Backend type ('huggingface', 'local', 'api', 'random')
            device: Device to run model on ('cpu', 'cuda', etc.)
            
        Returns:
            bool: True if successful
        """
        try:
            # Update backend if specified
            if backend:
                self.embedding.backend = backend
            
            # Update device if specified
            if device:
                self.embedding.device = device
            
            # Change embedding model
            success = self.embedding.change_model(model_name, backend or self.embedding.backend)
            
            if success:
                # Update the embedding model in other components
                self.archival_memory.embedding = self.embedding
                self.knowledge_manager.embedding = self.embedding
                
                log_embedding_operation("model_switch", model_name, backend or "unknown", 0.0, True, self.logger)
                return True
            else:
                self.logger.error(f"Failed to update embedding model to {model_name}")
                return False
                
        except Exception as e:
            log_error_with_context(e, {
                "operation": "set_embedding_model",
                "model_name": model_name,
                "backend": backend
            }, self.logger)
            return False
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """Get information about the current embedding model"""
        return self.embedding.get_model_info()

    def list_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent conversations from working, active and archival memory"""
        conversations = []

        # Get current conversation from working memory
        if self.current_conversation:
            conversations.append({
                "id": "current_conversation",
                "messages": self.current_conversation,
                "timestamp": datetime.datetime.now().isoformat(),
                "summary": f"Current conversation with {len(self.current_conversation)} messages",
                "source": "working_memory",
                "page_id": "current"
            })

        # Get messages from working memory
        working_messages = self.working_memory.get_messages()
        if working_messages:
            # Convert Message objects to dict format for consistency
            message_dicts = []
            for msg in working_messages:
                message_dicts.append({
                    "role": msg.type,
                    "content": msg.content,
                    "timestamp": msg.timestamp
                })

            conversations.append({
                "id": "working_memory_messages",
                "messages": message_dicts,
                "timestamp": working_messages[-1].timestamp if working_messages else datetime.datetime.now().isoformat(),
                "summary": f"Working memory with {len(working_messages)} messages",
                "source": "working_memory",
                "page_id": "working_messages"
            })

        # Get conversations from active memory
        for page in self.active_memory.pages:
            if page.page_type in ["conversation", "conversation_complete"] and isinstance(page.content, dict):
                if "messages" in page.content:
                    conversations.append({
                        "id": page.id,
                        "messages": page.content["messages"],
                        "timestamp": page.content.get("timestamp", page.created_at),
                        "summary": page.content.get("summary", ""),
                        "source": "active_memory",
                        "page_id": page.id
                    })
        
# Get recent conversations from archival memory
        archival_conversations = []
        for memory in self.archival_memory.memories:
            if isinstance(memory, dict) and memory.get("metadata", {}).get("type") == "conversation":
                archival_conversations.append({
                    "id": memory.get("id", ""),
                    "text": memory.get("text", ""),
                    "timestamp": memory.get("metadata", {}).get("timestamp", ""),
                    "summary": memory.get("metadata", {}).get("summary", ""),
                    "source": "archival_memory",
                    "metadata": memory.get("metadata", {})
                })
        
        # Sort by timestamp (most recent first)
        all_conversations = conversations + archival_conversations
        all_conversations.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Return limited results
        return all_conversations[:limit]
    
    def list_recent_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent documents from knowledge base"""
        documents = []
        
# Get recent documents from knowledge manager
        for doc in self.knowledge_manager.documents[-limit:]:
            documents.append({
                "id": doc.get("id", ""),
                "content": doc.get("content", doc.get("text", "")),
                "metadata": doc.get("metadata", {}),
                "timestamp": doc.get("timestamp", ""),
                "source": "knowledge_base"
            })
        
        return documents
    
    def remove_conversation_message(self, message_id: str) -> bool:
        """Remove a specific conversation message by its ID"""
        if not message_id or not message_id.strip():
            return False
        
        removed = False
        
        # Search in active memory
        for page in self.active_memory.pages[:]:  # Use slice to avoid modification during iteration
            if page.page_type in ["conversation", "conversation_complete"] and isinstance(page.content, dict):
                if "messages" in page.content:
                    # Remove messages that match the message_id
                    original_messages = page.content["messages"][:]
                    filtered_messages = [
                        msg for msg in original_messages 
                        if msg.get("id") != message_id
                    ]
                    
                    if len(filtered_messages) < len(original_messages):
                        page.content["messages"] = filtered_messages
                        removed = True
                        
                        # If conversation is empty, remove the page
                        if not filtered_messages:
                            self.active_memory.pages.remove(page)
        
        # Search in archival memory
        for memory in self.archival_memory.memories[:]:
            if isinstance(memory, dict) and memory.get("metadata", {}).get("type") == "conversation":
                if "messages" in memory:
                    original_messages = memory["messages"][:]
                    filtered_messages = [
                        msg for msg in original_messages 
                        if msg.get("id") != message_id
                    ]
                    
                    if len(filtered_messages) < len(original_messages):
                        memory["messages"] = filtered_messages
                        removed = True
                        
                        # If conversation is empty, remove the memory
                        if not filtered_messages:
                            self.archival_memory.memories.remove(memory)
        
        if removed:
            self.logger.info(f"Removed conversation message {message_id}")
        
        return removed
    
    def remove_recent_conversations(self, count: int) -> int:
        """Remove the most recent N conversations"""
        removed = 0
        
        # Remove from active memory (most recent first)
        active_pages_to_remove = min(count, len(self.active_memory.pages))
        for _ in range(active_pages_to_remove):
            if self.active_memory.pages:
                removed_page = self.active_memory.pages.pop()  # Remove most recent
                removed += 1
        
        # Remove from archival memory if needed
        if removed < count:
            archival_to_remove = count - removed
            # Since archival_memory.memories is a list, we need to remove from the end
            if len(self.archival_memory.memories) > archival_to_remove:
                del self.archival_memory.memories[-archival_to_remove:]
                removed += archival_to_remove
        
        return removed
    
    def remove_document(self, document_id: str) -> bool:
        """Remove a specific document from knowledge base"""
        if not document_id or not document_id.strip():
            return False

        original_count = len(self.knowledge_manager.documents)
        self.knowledge_manager.documents = [
            doc for doc in self.knowledge_manager.documents
            if doc.get("id") != document_id
        ]

        if len(self.knowledge_manager.documents) < original_count:
            # Also remove associated embeddings
            self.knowledge_manager.chunk_embeddings = [
                emb for emb in self.knowledge_manager.chunk_embeddings
                if emb.get("doc_id") != document_id
            ]
            # Save changes
            self.knowledge_manager._save_data()
            return True
        return False
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about the current memory state"""
        return {
            "working_memory": {
                "messages": len(self.working_memory.get_messages()),
                "tokens": self.working_memory.token_count,
                "max_tokens": self.working_memory.max_tokens
            },
            "active_memory": {
                "pages": len(self.active_memory.pages),
                "max_pages": self.active_memory.max_pages
            },
            "archival_memory": {
                "items": len(self.archival_memory.memories)
            },
            "knowledge_base": {
                "items": len(self.knowledge_manager.documents)
            },
            "embedding": self.get_embedding_info()
        }

    def _archive_page_callback(self, page: MemoryPage) -> None:
        """ Callback to archive a page from active memory to archival memory """
        # Convert page content to text for archival
        if isinstance(page.content, dict):
            # Format messages if available
            if "messages" in page.content and isinstance(page.content["messages"], list):
                messages = page.content["messages"]
                content_text = "\n".join([
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" 
                    for msg in messages
                ])
            else:
                # For other dict content, convert to JSON
                content_text = json.dumps(page.content)
        else:
            # For non-dict content, convert to string
            content_text = str(page.content)
        # Store in archival memory
        archival_id = self.archival_memory.store(
            text=content_text,
            metadata={
                "source": "active_memory",
                "page_id": page.id,
                "page_type": page.page_type,
                "created_at": page.created_at,
                "last_accessed": page.last_accessed,
                "access_count": page.access_count,
                "archived_at": datetime.datetime.now().isoformat(),
                "content_structure": list(page.content.keys()) if isinstance(page.content, dict) else None
            }
        )
        
        log_memory_operation("archive_page", {
            "page_id": page.id,
            "archival_id": archival_id,
            "page_size": len(page.content)
        }, self.logger)
    
    def _promote_archival_to_active(self, archival_item: Dict[str, Any], relevance_score: float) -> Optional[str]:
        """ Promote a highly relevant archival memory item to active memory """
        # Only promote items with high relevance
        if relevance_score < self.archival_promotion_threshold:
            return None
            
        # Check if this was originally from active memory
        metadata = archival_item.get("metadata", {})
        original_page_id = metadata.get("page_id")
        
        # If this item is already in active memory, don't duplicate
        if original_page_id:
            for page in self.active_memory.pages:
                if page.id == original_page_id:
                    # Just update its access count and timestamp
                    page.access()
                    return page.id
        
        # Create new content for active memory
        try:
            content_structure = metadata.get("content_structure", [])
            
            # Determine content format based on the archival item
            if "messages" in content_structure:
                # Try to reconstruct conversation format
                # Parse message format from text (format: role: content)
                text = archival_item.get("text", "")
                lines = text.split("\n")
                messages = []
                
                for line in lines:
                    if ":" in line:
                        role, content = line.split(":", 1)
                        messages.append({
                            "role": role.strip(),
                            "content": content.strip()
                        })
                
                page_content = {
                    "messages": messages,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "source": "archival_memory",
                    "original_timestamp": metadata.get("created_at"),
                    "promoted_due_to": "high_relevance"
                }
            else:
                # Create a content page with the archival text
                page_content = {
                    "text": archival_item.get("text", ""),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "source": "archival_memory", 
                    "metadata": metadata,
                    "promoted_due_to": "high_relevance"
                }
            # Add to active memory
            page_id = self.active_memory.add_page(
                page_content,
                page_type=metadata.get("page_type", "promoted"),
                archive_callback=self._archive_page_callback
            )
            
            log_memory_operation("promote_archival", {
                "archival_id": archival_item.get("id", "unknown"),
                "page_id": page_id,
                "relevance_score": relevance_score
            }, self.logger)
            return page_id
        except Exception as e:
            log_error_with_context(e, {
                "operation": "promote_archival_to_active",
                "archival_id": archival_item.get("id", "unknown"),
                "relevance_score": relevance_score
            }, self.logger)
            return None
    
    def __repr__(self) -> str:
        return (
            f"MemoryManager(working={len(self.working_memory.get_messages())} msgs, "
            f"active={len(self.active_memory.pages)} pages, "
            f"archival={len(self.archival_memory.memories)} items, "
            f"knowledge={len(self.knowledge_manager.documents)} items)"
        )