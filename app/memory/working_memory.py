from typing import Dict, List, Any
import datetime

class Message:
    """Simple message class for memory storage"""
    def __init__(self, type: str, content: str, timestamp: str = None):
        self.type = type  # 'user' or 'assistant'
        self.content = content
        self.timestamp = timestamp or datetime.datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, str]:
        """Convert message to dictionary for serialization"""
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'Message':
        """Create a Message instance from a dictionary"""
        return cls(
            type=data.get("type", "unknown"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp")
        )

class WorkingMemory:
    """
    Short-term memory for current conversation context
    Simplified implementation without LangChain dependencies
    """
    def __init__(self, max_tokens: int = 4000):
        self.messages: List[Message] = []
        self.max_tokens = max_tokens
        self.token_count = 0
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to working memory"""
        # Simple token estimation (can be replaced with a proper tokenizer)
        estimated_tokens = len(content.split())
        self.token_count += estimated_tokens
        
        # Create and add message
        self.messages.append(Message(role, content))
        
        # If we exceed max tokens, remove oldest messages
        if self.token_count > self.max_tokens:
            self._trim_to_fit()
    
    def _trim_to_fit(self) -> None:
        """Remove oldest messages until we're under the token limit"""
        while self.token_count > self.max_tokens * 0.8 and self.messages:
            # Remove oldest message
            removed_msg = self.messages.pop(0)
            # Reduce token count estimate
            self.token_count -= len(removed_msg.content.split())
    
    def get_messages(self) -> List[Message]:
        """Get all messages in working memory"""
        return self.messages

    def remove_messages(self, count: int) -> List[Message]:
        """ Remove the oldest 'count' messages from working memory and update token count """
        if count <= 0 or not self.messages:
            return []
        # Cap count to the number of messages available
        count = min(count, len(self.messages))
        # Get messages to remove
        removed_messages = self.messages[:count]
        # Update message list
        self.messages = self.messages[count:]
        # Recalculate token count for removed messages
        removed_tokens = sum(len(msg.content.split()) for msg in removed_messages)
        self.token_count = max(0, self.token_count - removed_tokens)
        return removed_messages

    def clear(self) -> None:
        """Clear working memory"""
        self.messages = []
        self.token_count = 0
    
    def is_full(self) -> bool:
        """Check if working memory is approaching capacity"""
        return self.token_count >= self.max_tokens * 0.8
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "messages": [msg.to_dict() for msg in self.messages],
            "max_tokens": self.max_tokens,
            "token_count": self.token_count
        }
    
    def export_to_json(self) -> str:
        """Export conversation history to JSON format"""
        import json
        return json.dumps({
            'type': 'conversation',
            'version': '1.0',
            'messages': [msg.to_dict() for msg in self.messages],
            'timestamp': datetime.datetime.now().isoformat()
        }, indent=2)
        
    def export_to_markdown(self) -> str:
        """Export conversation history to markdown format"""
        lines = ["# Conversation History\n"]
        for message in self.messages:
            header = f"### {message.type.title()}"
            lines.extend([header, "", message.content, ""])
        return "\n".join(lines)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkingMemory':
        """Create a WorkingMemory instance from a dictionary"""
        memory = cls(max_tokens=data.get("max_tokens", 4000))
        memory.token_count = data.get("token_count", 0)
        
        for msg_data in data.get("messages", []):
            message = Message.from_dict(msg_data)
            memory.messages.append(message)
            
        return memory

        
