from typing import Dict, List, Any, Optional, Union
import datetime
import json
import os
import re
from collections import Counter
import math

from app.memory.simplified_embeddings import SimpleEmbedding
from app.memory.working_memory import WorkingMemory
from app.memory.active_memory import ActiveMemory
from app.memory.archival_memory import ArchivalMemory
from app.memory.knowledge_manager import KnowledgeManager
from app.memory.memory_page import MemoryPage


class MemoryService:
    """
    Unified memory management system integrating all memory tiers
    with enhanced embedding capabilities
    """
    def __init__(self, 
                 data_dir: str = ".memory", 
                 embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe",
                 embedding_backend: str = "huggingface",
                 embedding_device: str = None,
                 config: Dict[str, Any] = None):
        """
        Initialize the memory manager
        
        Args:
            data_dir: Directory for storing memory data
            embedding_model: Name of the embedding model to use
            embedding_backend: Embedding backend type ('huggingface', 'local', 'api', 'random')
            embedding_device: Device to run embedding model on ('cpu', 'cuda', etc.)
            config: Additional configuration options
        """
        # Set up data directory
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Process config
        self.config = config or {}
        
        # Set up embedding system
        self._setup_embedding(
            model_name=embedding_model,
            backend=embedding_backend,
            device=embedding_device
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
        self.current_conversation = []
        self.current_context = []
        
        # Configure memory transition thresholds
        self.archival_promotion_threshold = self.config.get('archival_promotion_threshold', 0.6)
        self.memory_paging_threshold = self.config.get('memory_paging_threshold', 0.5)
        print(f"Memory manager initialized with {self.embedding.backend} embeddings using model: {self.embedding.model_name}")
    
    def _setup_embedding(self, model_name: str, backend: str, device: str = None) -> None:
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
            device=device,
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
        print(f"Paged out {num_messages} messages to active memory (Page ID: {page_id})")
    
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
        Retrieve relevant context from all memory tiers to support the current query
        """
        context_items = []
        query_embedding = self.embedding.get_text_embedding(query, prompt_name='query')

        # If the query embedding fails, we cannot search for context.
        if query_embedding is None:
            print("Warning: Could not generate embedding for the query. Skipping context search.")
            return []
        
        # 1. Search working memory
        working_messages = self.working_memory.get_messages()
        working_context = []
        for msg in working_messages:
            # Embed each message
            msg_embedding = self.embedding.get_text_embedding(msg.content)
            if not msg_embedding:
                continue
            
            # Calculate cosine similarity between query and message
            similarity = self.embedding._get_similarity(query_embedding, msg_embedding)
            
            if similarity > 0.3:  # Adjust threshold as needed
                working_context.append({
                    "source": "working_memory",
                    "content": msg.content,
                    "relevance": similarity
            })
        # Add working memory context
        context_items.extend(working_context)
        
        # 2. Search active memory pages
        active_pages = self.active_memory.pages
        for page in active_pages:
            # Convert page content to text for embedding
            if isinstance(page.content, dict):
                content_text = json.dumps(page.content)
            else:
                content_text = str(page.content)
            
            # Embed page content
            page_embedding = self.embedding.get_text_embedding(content_text)
            if not page_embedding:
                continue
            
            # Calculate similarity
            similarity = self.embedding._get_similarity(query_embedding, page_embedding)
            
            if similarity > 0.3:  # Adjust threshold as needed
                context_items.append({
                    "source": "active_memory",
                    "content": page.content,
                    "page_id": page.id,
                    "relevance": similarity
                })
                # Update access metadata for the page
                page.access()
        
        # 3. Search archival memory
        archival_results = self.archival_memory.search(query, limit=max_items)
        for result in archival_results:
            # Check relevance score for promotion
            relevance_score = result.get("relevance_score", 0)
            # Try to promote highly relevant memories
            if relevance_score > 0.8:  # Same threshold as in _promote_archival_to_active
                promoted_page_id = self._promote_archival_to_active(result, relevance_score)
                # Include promotion information if successful
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
        sorted_context = sorted(context_items, key=lambda x: x.get("relevance", 0), reverse=True)
        
        # Limit and store current context
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
    
    def add_to_knowledge_base(self, document: str, metadata: Dict[str, Any] = None) -> None:
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
                    print(f"Notice: Current embedding model ({current_model}) differs from saved state ({saved_model})")
            
            return True
        except Exception as e:
            print(f"Error loading memory state: {e}")
            return False
    
    def set_embedding_model(self, model_name: str, backend: str = None, device: str = None) -> bool:
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
            success = self.embedding.change_model(model_name, backend)
            
            if success:
                # Update the embedding model in other components
                self.archival_memory.embedding = self.embedding
                self.knowledge_manager.embedding = self.embedding
                
                print(f"Embedding model updated to {model_name}")
                return True
            else:
                print(f"Failed to update embedding model to {model_name}")
                return False
                
        except Exception as e:
            print(f"Error setting embedding model: {e}")
            return False
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """Get information about the current embedding model"""
        return self.embedding.get_model_info()

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
        print(f"Archived active memory page {page.id} to archival memory as {archival_id}")
    
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
            print(f"Promoted archival memory item to active memory as page {page_id}")
            return page_id
        except Exception as e:
            print(f"Error promoting archival memory: {e}")
            return None
    
    def __repr__(self) -> str:
        return (
            f"MemoryManager(working={len(self.working_memory.get_messages())} msgs, "
            f"active={len(self.active_memory.pages)} pages, "
            f"archival={len(self.archival_memory.collection.get()['ids'])} items, "
            f"knowledge={len(self.knowledge_manager.collection.get()['ids'])} items)"
        )