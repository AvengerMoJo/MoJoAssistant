from typing import Dict, Any
import datetime
import uuid

class MemoryPage:
    """
    A single page of memory in the Active Memory tier
    Inspired by MemGPT's paging system
    """
    def __init__(self, content: Dict[str, Any], page_type: str = "conversation"):
        self.id = str(uuid.uuid4())
        self.content = content
        self.page_type = page_type  # conversation, summary, etc.
        self.created_at = datetime.datetime.now().isoformat()
        self.last_accessed = self.created_at
        self.access_count = 0
    
    def access(self) -> None:
        """Update page access metadata"""
        self.last_accessed = datetime.datetime.now().isoformat()
        self.access_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert page to dictionary for serialization"""
        return {
            "id": self.id,
            "content": self.content,
            "page_type": self.page_type,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryPage':
        """Create a MemoryPage instance from a dictionary"""
        page = cls(
            content=data.get("content", {}),
            page_type=data.get("page_type", "unknown")
        )
        page.id = data.get("id", str(uuid.uuid4()))
        page.created_at = data.get("created_at", page.created_at)
        page.last_accessed = data.get("last_accessed", page.last_accessed)
        page.access_count = data.get("access_count", 0)
        return page
