from typing import Dict, List, Any, Optional
from app.memory.memory_page import MemoryPage

class ActiveMemory:
    """
    Mid-term memory with pagination
    Implements MemGPT-inspired memory paging system
    """
    def __init__(self, max_pages: int = 20):
        self.pages: List[MemoryPage] = []
        self.max_pages = max_pages
    
    def add_page(self, content: Dict[str, Any], page_type: str = "conversation") -> str:
        """Add a new memory page and return its ID"""
        page = MemoryPage(content, page_type)
        self.pages.append(page)
        
        # If we exceed the maximum pages, archive the least recently accessed page
        if len(self.pages) > self.max_pages:
            self._archive_least_accessed_page()
            
        return page.id
    
    def get_page(self, page_id: str) -> Optional[MemoryPage]:
        """Retrieve a page by ID and update its access metadata"""
        for page in self.pages:
            if page.id == page_id:
                page.access()
                return page
        return None
    
    def get_recent_pages(self, limit: int = 5) -> List[MemoryPage]:
        """Get the most recently accessed pages"""
        sorted_pages = sorted(
            self.pages, 
            key=lambda p: p.last_accessed, 
            reverse=True
        )
        return sorted_pages[:limit]
    
    def search_pages(self, query: str) -> List[MemoryPage]:
        """
        Basic search through pages (to be enhanced with embeddings)
        This is a simplified implementation - in practice, use embeddings
        """
        results = []
        query_lower = query.lower()
        
        for page in self.pages:
            # Simple text search in content values
            content_text = ""
            
            # Handle different content formats
            if isinstance(page.content, dict):
                # For dictionaries, concatenate all string values
                for key, value in page.content.items():
                    if key == "messages" and isinstance(value, list):
                        # Special handling for message lists
                        for msg in value:
                            if isinstance(msg, dict) and "content" in msg:
                                content_text += " " + str(msg["content"])
                    elif isinstance(value, str):
                        content_text += " " + value
            else:
                # For non-dict content, convert to string
                content_text = str(page.content)
                
            # Perform the search
            if query_lower in content_text.lower():
                page.access()
                results.append(page)
                
        return results
    
    def _archive_least_accessed_page(self) -> Optional[MemoryPage]:
        """
        Find the least recently accessed page and mark it for archival
        In a full implementation, this would move the page to archival memory
        """
        if not self.pages:
            return None
            
        least_accessed = min(
            self.pages, 
            key=lambda p: (p.last_accessed, -p.access_count)
        )
        
        # In full implementation: send to archival memory before removing
        self.pages.remove(least_accessed)
        
        return least_accessed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "pages": [page.to_dict() for page in self.pages],
            "max_pages": self.max_pages
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActiveMemory':
        """Create an ActiveMemory instance from a dictionary"""
        memory = cls(max_pages=data.get("max_pages", 20))
        
        for page_data in data.get("pages", []):
            memory.pages.append(MemoryPage.from_dict(page_data))
            
        return memory
