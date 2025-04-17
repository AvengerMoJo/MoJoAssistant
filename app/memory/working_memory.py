from typing import Dict, List
from langchain.memory import ConversationBufferMemory

class WorkingMemory:
    """
    Short-term memory for current conversation context
    Implemented using LangChain's ConversationBufferMemory
    """
    def __init__(self, max_tokens: int = 4000):
        self.memory = ConversationBufferMemory(
            return_messages=True,
            memory_key="chat_history"
        )
        self.max_tokens = max_tokens
        self.token_count = 0
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to working memory"""
        # Simple token estimation (can be replaced with a proper tokenizer)
        estimated_tokens = len(content.split())
        self.token_count += estimated_tokens
        
        if role.lower() == "user" or role.lower() == "human":
            self.memory.chat_memory.add_user_message(content)
        else:
            self.memory.chat_memory.add_ai_message(content)
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get all messages in working memory"""
        return self.memory.chat_memory.messages
    
    def clear(self) -> None:
        """Clear working memory"""
        self.memory.chat_memory.clear()
        self.token_count = 0
    
    def is_full(self) -> bool:
        """Check if working memory is approaching capacity"""
        return self.token_count >= self.max_tokens * 0.8

