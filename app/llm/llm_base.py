

class BaseLLMInterface(ABC):
    """
    Abstract base class for LLM interfaces
    """
    @abstractmethod
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """Generate a response from the LLM"""
        pass
    
    def format_context(self, context: List[Dict[str, Any]]) -> str:
        """
        Format context information for inclusion in prompts
        
        Args:
            context: List of context items
            
        Returns:
            str: Formatted context text
        """
        if not context:
            return "No previous context available."
        
        context_items = []
        for item in context:
            source = item.get('source', 'unknown')
            
            # Handle different types of content
            content = item.get('content', '')
            if not isinstance(content, str):
                # Try to convert to string or extract text
                try:
                    if hasattr(content, 'content'):
                        # Handle message objects
                        content = content.content
                    elif hasattr(content, 'text'):
                        content = content.text
                    else:
                        content = str(content)
                except:
                    content = "Complex content object"
            
            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
                
            context_items.append(f"- From {source}: {content}")
        
        return "\n".join(context_items)
