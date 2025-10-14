"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""
from typing import Dict, Any, List
import time
from datetime import datetime


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
                "description": "Search all memory tiers (working, active, archival, knowledge base) for relevant context. Supports both English and Chinese queries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query in English or Chinese",
                            "minLength": 1
                        },
                        "max_items": {
                            "type": "integer", 
                            "description": "Maximum number of context items to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "add_documents",
                "description": "Add reference documents to the knowledge base for permanent storage. Use for documentation, code examples, or reference material.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "documents": {
                            "type": "array",
                            "description": "Array of documents to add",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "Document content (supports Chinese and English)",
                                        "minLength": 1
                                    },
                                    "metadata": {
                                        "type": "object",
                                        "description": "Optional metadata (title, topic, tags, etc.)",
                                        "additionalProperties": True
                                    }
                                },
                                "required": ["content"]
                            },
                            "minItems": 1
                        }
                    },
                    "required": ["documents"]
                }
            },
            {
                "name": "add_conversation",
                "description": "Add a complete conversation exchange (user question + assistant reply) to working memory. Call this after each Q&A interaction to build conversation context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_message": {
                            "type": "string",
                            "description": "The user's question or message (supports Chinese and English)",
                            "minLength": 1
                        },
                        "assistant_message": {
                            "type": "string", 
                            "description": "The assistant's response or reply (supports Chinese and English)",
                            "minLength": 1
                        }
                    },
                    "required": ["user_message", "assistant_message"]
                }
            },
            {
                "name": "get_memory_stats",
                "description": "Get comprehensive statistics about the memory system.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "end_conversation",
                "description": "End the current conversation and archive it to memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "toggle_multi_model",
                "description": "Enable or disable multi-model embedding support at runtime.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "True to enable multi-model, False to disable"
                        }
                    },
                    "required": ["enabled"]
                }
            },
            {
                "name": "list_recent_conversations",
                "description": "List recent conversation messages for management/cleanup. Shows message previews with IDs for removal.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent conversations to show",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "remove_conversation_message", 
                "description": "Remove a specific conversation message by its ID. Use this to clean up bad/useless conversations from other models.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "ID of the message to remove (from list_recent_conversations)"
                        }
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "remove_recent_conversations",
                "description": "Remove the most recent N conversation messages. Use when multiple recent conversations are bad.",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of recent conversations to remove",
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["count"]
                }
            },
            {
                "name": "list_recent_documents",
                "description": "List recent documents for management/cleanup. Shows document previews with IDs for removal.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer", 
                            "description": "Number of recent documents to show",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "remove_document",
                "description": "Remove a specific document by its ID. Use this to clean up unwanted documents.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to remove (from list_recent_documents)"
                        }
                    },
                    "required": ["document_id"]
                }
            },
            {
                "name": "web_search",
                "description": "Search the internet for current information using Google Custom Search API. Returns high-quality, relevant web search results with citations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for finding current information on the web",
                            "minLength": 1
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of search results to return (Google: max 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_current_day",
                "description": "Get the current date, day of week, time, and year information. Use this for questions about today's date, current day, time, current year, or any date/time related queries. Returns exact current date (including year), day name, time, timestamp, year, and other temporal details without needing web search.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_current_time",
                "description": "Get the current time with timezone information. Returns detailed time information including hours, minutes, seconds, and timezone.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
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
        elif name == "add_documents":
            return await self._execute_add_documents(args)
        elif name == "end_conversation":
            return await self._execute_end_conversation(args)
        elif name == "toggle_multi_model":
            return await self._execute_toggle_multi_model(args)
        elif name == "list_recent_conversations":
            return await self._execute_list_recent_conversations(args)
        elif name == "remove_conversation_message":
            return await self._execute_remove_conversation_message(args)
        elif name == "remove_recent_conversations":
            return await self._execute_remove_recent_conversations(args)
        elif name == "list_recent_documents":
            return await self._execute_list_recent_documents(args)
        elif name == "remove_document":
            return await self._execute_remove_document(args)
        elif name == "web_search":
            return await self._execute_web_search(args)
        elif name == "get_current_day":
            return await self._execute_get_current_day(args)
        elif name == "get_current_time":
            return await self._execute_get_current_time(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def _execute_get_memory_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory context search"""
        query = args.get("query", "")
        max_results = args.get("max_items", 10)
        
        results = self.memory_service.get_context_for_query(query, max_items=max_results)
        
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": time.time()
        }
    
    async def _execute_add_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add conversation"""
        user_message = args.get("user_message", "")
        assistant_message = args.get("assistant_message", "")
        
        self.memory_service.add_user_message(user_message)
        self.memory_service.add_assistant_message(assistant_message)
        
        return {
            "status": "success",
            "message": "Conversation exchange added to working memory",
            "user_message_length": len(user_message),
            "assistant_message_length": len(assistant_message)
        }
    
    async def _execute_get_memory_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get memory statistics"""
        stats = self.memory_service.get_memory_stats()
        return stats

    async def _execute_add_documents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add documents"""
        documents = args.get("documents", [])
        results = []
        for doc in documents:
            try:
                content = doc.get("content", "")
                metadata = doc.get("metadata", {})
                self.memory_service.add_to_knowledge_base(content, metadata)
                results.append({"status": "success", "message": "Document added"})
            except Exception as e:
                results.append({"status": "error", "message": str(e)})
        return {"results": results, "total_processed": len(documents)}

    async def _execute_end_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute end conversation"""
        self.memory_service.end_conversation()
        return {"status": "success", "message": "Conversation ended and archived"}

    async def _execute_toggle_multi_model(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute toggle multi model"""
        enabled = args.get("enabled", False)
        self.memory_service.multi_model_enabled = enabled
        return {"status": "success", "multi_model_enabled": enabled}

    async def _execute_list_recent_conversations(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list recent conversations"""
        limit = args.get("limit", 10)
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Listing last {limit} conversations is not implemented yet."}

    async def _execute_remove_conversation_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove conversation message"""
        message_id = args.get("message_id", "")
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Removing message {message_id} is not implemented yet."}

    async def _execute_remove_recent_conversations(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove recent conversations"""
        count = args.get("count", 0)
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Removing last {count} conversations is not implemented yet."}

    async def _execute_list_recent_documents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list recent documents"""
        limit = args.get("limit", 10)
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Listing last {limit} documents is not implemented yet."}

    async def _execute_remove_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove document"""
        document_id = args.get("document_id", "")
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Removing document {document_id} is not implemented yet."}

    async def _execute_web_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute web search"""
        query = args.get("query", "")
        # This is a placeholder. The actual implementation will depend on the memory service.
        return {"message": f"Web search for '{query}' is not implemented yet."}

    async def _execute_get_current_day(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get current day"""
        from datetime import datetime
        now = datetime.now()
        return {
            "date": now.strftime("%Y-%m-%d"),
            "day_of_week": now.strftime("%A"),
            "time": now.strftime("%H:%M:%S"),
            "year": now.year,
            "month": now.month,
            "day": now.day
        }

    async def _execute_get_current_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get current time"""
        from datetime import datetime
        now = datetime.now()
        return {
            "time": now.strftime("%H:%M:%S"),
            "timezone": now.astimezone().tzname()
        }
