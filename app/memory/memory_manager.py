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

class MemoryManager:
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
    
    def _page_out_oldest_messages(self, num_messages: int = 5) -> None:
        """
        Move oldest messages from working memory to active memory
        Implements the memory paging concept from MemGPT
        """
        messages = self.working_memory.get_messages()
        
        if len(messages) <= num_messages:
            return
            
        # Get oldest messages to page out
        oldest_messages = messages[:num_messages]
        
        # Create a page in active memory
        page_content = {
            "messages": [{"role": msg.type, "content": msg.content} for msg in oldest_messages],
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.active_memory.add_page(page_content, "conversation")
        
        # Create new working memory with remaining messages
        new_memory = WorkingMemory(max_tokens=self.working_memory.max_tokens)
        for msg in messages[num_messages:]:
            new_memory.add_message(msg.type, msg.content)
            
        # Replace working memory
        self.working_memory = new_memory
    
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
        page_id = self.active_memory.add_page(page_content, "conversation_complete")
        
        # Also store in archival memory for long-term retrieval
        conversation_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in self.current_conversation])
        self.archival_memory.store(
            text=conversation_text,
            metadata={
                "type": "conversation",
                "timestamp": datetime.datetime.now().isoformat(),
                "message_count": len(self.current_conversation),
                "summary": summary,
                "active_memory_page_id": page_id
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
    
    def get_context_for_query(self, query: str, max_items: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant context from all memory tiers to support the current query
        """
        context_items = []
        query_embedding = self.embedding.get_text_embedding(query, prompt_name='query')
        
        # 1. Search working memory
        working_messages = self.working_memory.get_messages()
        working_context = []
        for msg in working_messages:
            # Embed each message
            msg_embedding = self.embedding.get_text_embedding(msg.content)
            
            # Calculate cosine similarity between query and message
            similarity = self._cosine_similarity(query_embedding, msg_embedding)
            
            if similarity > 0.5:  # Adjust threshold as needed
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
            
            # Calculate similarity
            similarity = self._cosine_similarity(query_embedding, page_embedding)
            
            if similarity > 0.5:  # Adjust threshold as needed
                context_items.append({
                    "source": "active_memory",
                "content": page.content,
                "page_id": page.id,
                "relevance": similarity
            })
        
        # 3. Search archival memory
        archival_results = self.archival_memory.search(query, limit=max_items)
        for result in archival_results:
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

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """
        Calculate cosine similarity between two embedding vectors
        
        Args:
            vec_a: First embedding vector
            vec_b: Second embedding vector
            
        Returns:
            Cosine similarity score between 0 and 1
        """
        # Ensure vectors are of the same length
        if len(vec_a) != len(vec_b):
            return 0.0
        
        # Calculate dot product
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        
        # Calculate magnitudes
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))
        
        # Prevent division by zero
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        # Calculate and return cosine similarity
        return dot_product / (magnitude_a * magnitude_b)

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
