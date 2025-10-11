"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""
from typing import Dict, Any, List
import time


class ToolRegistry:
    """Registry of available tools and their execution"""
    
    def __init__(self, memory_service):
        self.memory_service = memory_service
        self.tools = self._define_tools()
    
    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define all available tools"""
        return [
            {
                "name": "get_memory_context",
                "description": "Search all memory tiers for relevant context",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "add_conversation",
                "description": "Add conversation messages to memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["user", "assistant"]},
                                    "content": {"type": "string"}
                                },
                                "required": ["type", "content"]
                            }
                        }
                    },
                    "required": ["messages"]
                }
            },
            {
                "name": "get_memory_stats",
                "description": "Get comprehensive memory system statistics",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools"""
        return self.tools
    
    async def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""
        
        if name == "get_memory_context":
            return await self._execute_get_memory_context(args)
        elif name == "add_conversation":
            return await self._execute_add_conversation(args)
        elif name == "get_memory_stats":
            return await self._execute_get_memory_stats(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def _execute_get_memory_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory context search"""
        query = args.get("query", "")
        max_results = args.get("max_results", 10)
        
        results = self.memory_service.get_context_for_query(query, max_results=max_results)
        
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": time.time()
        }
    
    async def _execute_add_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add conversation"""
        messages = args.get("messages", [])
        
        for msg in messages:
            if msg["type"] == "user":
                self.memory_service.add_user_message(msg["content"])
            else:
                self.memory_service.add_assistant_message(msg["content"])
        
        return {
            "status": "success",
            "messages_added": len(messages),
            "timestamp": time.time()
        }
    
    async def _execute_get_memory_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get memory statistics"""
        stats = self.memory_service.get_statistics()
        return stats
