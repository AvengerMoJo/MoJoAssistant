from typing import Dict, List, Any, Optional, Union
import datetime
import json
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from app.memory.working_memory import WorkingMemory
from app.memory.active_memory import ActiveMemory
from app.memory.archival_memory import ArchivalMemory
from app.memory.knowledge_manager import KnowledgeManager

class MemoryManager:
    """
    Unified memory management system integrating all memory tiers
    """
    def __init__(self):
        shared_embedding = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")
        self.working_memory = WorkingMemory()
        self.active_memory = ActiveMemory()
        self.archival_memory = ArchivalMemory(embedding=shared_embedding)
        self.knowledge_manager = KnowledgeManager(embedding=shared_embedding)
        
        # Track the current conversation
        self.current_conversation = []
        self.current_context = []
    
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
            
        # Store full conversation in active memory
        page_content = {
            "messages": self.current_conversation,
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": self._generate_conversation_summary()
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
                "summary": page_content["summary"],
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
        In a full implementation, this would use an LLM to summarize
        """
        # Simplified placeholder - in production, use an LLM for this
        if len(self.current_conversation) <= 2:
            return "Brief conversation with insufficient content for summarization"
            
        user_messages = [msg["content"] for msg in self.current_conversation if msg["role"] == "user"]
        
        if not user_messages:
            return "No user messages found in conversation"
            
        # Very basic summary approach
        topics = []
        for msg in user_messages:
            words = msg.split()
            # Get most frequent non-stopwords as topics
            # This is an oversimplification - use proper NLP in production
            for word in words:
                if len(word) > 4 and word.isalpha():
                    topics.append(word.lower())
        
        # Count occurrences
        from collections import Counter
        topic_counter = Counter(topics)
        main_topics = [topic for topic, count in topic_counter.most_common(3)]
        
        return f"Conversation about {', '.join(main_topics)}" if main_topics else "General conversation"
    
    def get_context_for_query(self, query: str, max_items: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant context from all memory tiers to support the current query
        """
        context_items = []
        
        # First, check working memory (current conversation context)
        working_context = self.working_memory.get_messages()
        if working_context:
            context_items.append({
                "source": "working_memory",
                "content": working_context,
                "relevance": 1.0  # Current conversation is highly relevant
            })
        
        # Search active memory for relevant pages
        active_pages = self.active_memory.search_pages(query)
        for page in active_pages[:max_items//2]:
            context_items.append({
                "source": "active_memory",
                "content": page.content,
                "page_id": page.id,
                "relevance": 0.8  # Active memory is fairly relevant
            })
        
        # Search archival memory for relevant memories
        archival_results = self.archival_memory.search(query, limit=max_items//2)
        for result in archival_results:
            context_items.append({
                "source": "archival_memory",
                "content": result["text"],
                "metadata": result["metadata"],
                "relevance": result["relevance_score"]
            })
        
        # Search knowledge base if we have one
        knowledge_results = self.knowledge_manager.query(query, similarity_top_k=max_items//2)
        for text, score in knowledge_results:
            context_items.append({
                "source": "knowledge_base",
                "content": text,
                "relevance": score
            })
        
        # Sort by relevance
        sorted_context = sorted(context_items, key=lambda x: x["relevance"], reverse=True)
        
        # Keep track of the context used for this query
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
            
            return True
        except Exception as e:
            print(f"Error loading memory state: {e}")
            return False

