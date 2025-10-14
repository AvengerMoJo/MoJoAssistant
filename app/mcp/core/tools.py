"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""
from typing import Dict, Any, List
import time
from datetime import datetime


class ToolRegistry:
    """Registry of available tools and their execution"""
    
    def __init__(self, memory_service, config: Dict[str, Any] = None):
        self.memory_service = memory_service
        self.config = config or {}
        self.tools = self._define_tools()
        # Re-enable the working placeholder tools
        self.placeholder_tools = {
            "web_search"  # Only web_search needs re-implementation
        }
    
    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define all available tools"""
        return [
            {
                "name": "get_memory_context",
                "description": "Search all memory tiers (working, active, archival, knowledge base) for relevant context to enhance responses. Supports both English and Chinese queries. When to use: Call this tool whenever you need to retrieve relevant context from the user's memory during conversations, research, or problem-solving. How it works: Performs semantic search across multiple memory tiers using embeddings. Why useful: Provides personalized, context-aware responses based on user's history and knowledge.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query in English or Chinese to find relevant context",
                            "minLength": 1
                        },
                        "max_items": {
                            "type": "integer", 
                            "description": "Maximum number of context items to return (default: 10, max: 50)",
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
                "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base for future retrieval. When to use: Use this when you want to permanently store reference material, documentation, code snippets, or any information that should be available for future conversations. How it works: Documents are embedded and stored in the knowledge base with optional metadata. Why useful: Builds a personal knowledge repository that can be searched later using get_memory_context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "documents": {
                            "type": "array",
                            "description": "Array of documents to add to knowledge base",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "Document content (supports Chinese and English text)",
                                        "minLength": 1
                                    },
                                    "metadata": {
                                        "type": "object",
                                        "description": "Optional metadata (title, topic, tags, source, etc.) for better organization",
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
                "description": "Add a complete conversation exchange (user question + assistant reply) to working memory to maintain conversation continuity. When to use: Call this after each Q&A interaction or conversation exchange to build and maintain context. How it works: Stores both user and assistant messages in working memory for immediate retrieval. Why useful: Enables the assistant to remember recent conversations and maintain context across multiple interactions.",
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
                "description": "Get comprehensive statistics about the memory system including sizes of different memory tiers and performance metrics. When to use: Use to monitor memory usage, check system health, or understand how much information is stored. How it works: Returns detailed statistics from all memory tiers (working, active, archival, knowledge base). Why useful: Helps monitor system performance and memory utilization for optimization.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "end_conversation",
                "description": "End the current conversation and archive it to long-term memory for future reference. When to use: Call when a conversation topic is complete or when starting a new unrelated topic. How it works: Moves conversation from working memory to archival memory for long-term storage. Why useful: Keeps working memory focused on current topics while preserving conversation history.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "toggle_multi_model",
                "description": "Enable or disable multi-model embedding support at runtime for enhanced semantic search. When to use: Enable when you need better search accuracy across diverse content types, disable to reduce resource usage. How it works: Switches between single and multi-model embedding modes. Why useful: Multi-model mode provides better semantic understanding but uses more computational resources.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "True to enable multi-model embeddings, False to disable (uses single model)"
                        }
                    },
                    "required": ["enabled"]
                }
            },
            {
                "name": "list_recent_conversations",
                "description": "List recent conversation messages for management and cleanup purposes. When to use: Use to review recent conversations before cleanup or to identify messages for removal. How it works: Returns a list of recent conversation messages with their IDs. Why useful: Enables cleanup of unwanted or incorrect conversations from memory. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent conversations to show (default: 10, max: 50)",
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
                "description": "Remove a specific conversation message by its ID to clean up memory. When to use: Use to remove bad, incorrect, or unwanted conversation messages from other models. How it works: Deletes a specific message by its unique ID. Why useful: Allows cleanup of problematic conversations while preserving good ones. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "ID of the message to remove (obtain from list_recent_conversations)"
                        }
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "remove_recent_conversations",
                "description": "Remove the most recent N conversation messages for bulk cleanup. When to use: Use when multiple recent conversations are bad or unwanted. How it works: Deletes the specified number of most recent conversation exchanges. Why useful: Enables quick cleanup of recent problematic conversations. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of recent conversations to remove (1-100)",
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["count"]
                }
            },
            {
                "name": "list_recent_documents",
                "description": "List recent documents for management and cleanup purposes. When to use: Use to review recently added documents before cleanup. How it works: Returns a list of recent documents with their IDs and metadata. Why useful: Enables cleanup of unwanted documents from the knowledge base. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer", 
                            "description": "Number of recent documents to show (default: 10, max: 50)",
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
                "description": "Remove a specific document by its ID to clean up the knowledge base. When to use: Use to remove unwanted, outdated, or incorrect documents. How it works: Deletes a specific document by its unique ID. Why useful: Keeps the knowledge base clean and relevant. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to remove (obtain from list_recent_documents)"
                        }
                    },
                    "required": ["document_id"]
                }
            },
            {
                "name": "web_search",
                "description": "Search the internet for current information using Google Custom Search API. When to use: Use when you need up-to-date information, news, or data not available in local memory. How it works: Queries Google Custom Search API and returns relevant results with citations. Why useful: Provides access to current web information for comprehensive responses. [PLACEHOLDER - Not yet implemented]",
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
                            "description": "Maximum number of search results to return (max: 10)",
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
                "description": "Get the current date, day of week, time, and year information for temporal awareness. When to use: Call for questions about today's date, current day, time, current year, or any date/time related queries. How it works: Returns exact current date/time information without needing web search. Why useful: Provides accurate temporal context for scheduling, reminders, and time-sensitive responses.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_current_time",
                "description": "Get the current time with timezone information for precise timing. When to use: Use for questions about current time, scheduling, or time-sensitive operations. How it works: Returns detailed time information including hours, minutes, seconds, and timezone. Why useful: Ensures accurate time awareness for all responses.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools (excludes placeholders)"""
        return [tool for tool in self.tools if tool["name"] not in self.placeholder_tools]
    
    def enable_placeholder_tool(self, tool_name: str):
        """Enable a placeholder tool (make it available to MCP)"""
        if tool_name in self.placeholder_tools:
            self.placeholder_tools.remove(tool_name)

    def disable_placeholder_tool(self, tool_name: str):
        """Disable a tool (make it unavailable to MCP but keep definition)"""
        if tool_name not in self.placeholder_tools:
            self.placeholder_tools.add(tool_name)
    
    async def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""
        
        # Check if this is a placeholder tool
        if name in self.placeholder_tools:
            return {
                "status": "placeholder",
                "message": f"Tool '{name}' is not yet implemented. This is a placeholder for future development.",
                "tool_name": name,
                "timestamp": time.time()
            }
        
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
        
        # Use async version for better performance in async contexts
        results = await self.memory_service.get_context_for_query_async(query, max_items=max_results)
        
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
        conversations = self.memory_service.list_recent_conversations(limit)
        return {
            "conversations": conversations,
            "total": len(conversations),
            "message": f"Retrieved {len(conversations)} recent conversations"
        }

    async def _execute_remove_conversation_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove conversation message"""
        message_id = args.get("message_id", "")
        success = self.memory_service.remove_conversation_message(message_id)
        return {
            "success": success,
            "message": f"Conversation message {message_id} {'removed' if success else 'not found'}"
        }

    async def _execute_remove_recent_conversations(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove recent conversations"""
        count = args.get("count", 0)
        removed_count = self.memory_service.remove_recent_conversations(count)
        return {
            "removed_count": removed_count,
            "message": f"Removed {removed_count} recent conversations"
        }

    async def _execute_list_recent_documents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list recent documents"""
        limit = args.get("limit", 10)
        documents = self.memory_service.list_recent_documents(limit)
        return {
            "documents": documents,
            "total": len(documents),
            "message": f"Retrieved {len(documents)} recent documents"
        }

    async def _execute_remove_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove document"""
        document_id = args.get("document_id", "")
        success = self.memory_service.remove_document(document_id)
        return {
            "success": success,
            "message": f"Document {document_id} {'removed' if success else 'not found'}"
        }

    async def _execute_web_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute web search using Google Custom Search API"""
        query = args.get("query", "")
        max_results = args.get("limit", 10)

        try:
            # Import here to avoid dependency issues if not available
            import urllib.request
            import urllib.parse
            import json
            import time

            # Try Google Custom Search API first (if API key is available)
            google_api_key = self.config.get('google_api_key', '')
            search_engine_id = self.config.get('google_search_engine_id', '')

            if google_api_key and search_engine_id:
                try:
                    # Use Google Custom Search API
                    encoded_query = urllib.parse.quote(query)
                    url = f"https://www.googleapis.com/customsearch/v1?key={google_api_key}&cx={search_engine_id}&q={encoded_query}&num={min(max_results, 10)}"

                    req = urllib.request.Request(url)
                    req.add_header('User-Agent', 'MoJoAssistant/1.0')

                    with urllib.request.urlopen(req, timeout=15) as response:
                        data = response.read().decode('utf-8')
                        search_result = json.loads(data)

                    # Parse Google results
                    results = []
                    if 'items' in search_result:
                        for item in search_result['items'][:max_results]:
                            results.append({
                                "title": item.get('title', ''),
                                "content": item.get('snippet', ''),
                                "url": item.get('link', ''),
                                "source": "google"
                            })

                    return {
                        "query": query,
                        "results": results,
                        "total_results": len(results),
                        "source": "google_custom_search",
                        "timestamp": time.time()
                    }

                except Exception as e:
                    # Fallback if Google API fails
                    return {
                        "query": query,
                        "error": f"Google Custom Search API failed: {str(e)}",
                        "results": [],
                        "timestamp": time.time()
                    }
            else:
                return {
                    "query": query,
                    "error": "Google Custom Search API not configured",
                    "results": [],
                    "timestamp": time.time()
                }

        except Exception as e:
            return {
                "query": query,
                "error": f"Web search failed: {str(e)}",
                "results": [],
                "timestamp": time.time()
            }

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
