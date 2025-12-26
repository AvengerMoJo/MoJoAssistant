"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""
from typing import Dict, Any, List, Optional
import time
from datetime import datetime


class ToolRegistry:
    """Registry of available tools and their execution"""
    
    def __init__(self, memory_service, config: Dict[str, Any] | None = None):
        self.memory_service = memory_service
        # Load Google API config from environment if not provided
        if config is None:
            config = {}
        
        # Ensure Google API config is loaded
        if 'google_api_key' not in config:
            from app.config.mcp_config import load_mcp_config
            mcp_config = load_mcp_config()
            config.update(mcp_config)
        
        self.config = config
        self.tools = self._define_tools()
        # Re-enable the working placeholder tools
        self.placeholder_tools = {
            "get_current_time",  # Redundant with get_current_day
            "get_memory_stats"  # Internal stats not useful for LLMs
        }
        
        # Enable web_search tool as implementation is complete
        if "web_search" in self.placeholder_tools:
            self.placeholder_tools.remove("web_search")
        
        # Enable web_search tool as implementation is complete
        if "web_search" in self.placeholder_tools:
            self.placeholder_tools.remove("web_search")
        
        # Enable web_search tool as implementation is complete
        self.enable_placeholder_tool("web_search")
        
        # Standardized user prompt templates for LLM usability
        self.user_prompt_templates = {
            "get_memory_context": {
                "template": "Search my memory for information about: {query}",
                "examples": [
                    "Search my memory for information about Python programming",
                    "Find information about our previous discussion about machine learning",
                    "Look up what I know about climate change"
                ],
                "usage_tip": "Use this tool to retrieve relevant context from the user's memory before answering questions or providing information."
            },
            "add_documents": {
                "template": "Add these documents to my knowledge base: {content}",
                "examples": [
                    "Add this document to my knowledge base: Python best practices for web development",
                    "Store this reference material: Machine learning algorithms explained",
                    "Save this information: Climate change impacts and solutions"
                ],
                "usage_tip": "Use this tool to permanently store reference material, documentation, or any information that should be available for future conversations."
            },
            "add_conversation": {
                "template": "Remember this conversation: User asked '{user_message}' and I responded '{assistant_message}'",
                "examples": [
                    "Remember this conversation: User asked 'What is Python?' and I responded 'Python is a high-level programming language...'",
                    "Store this exchange: User asked 'How do I install packages?' and I responded 'You can use pip to install Python packages...'"
                ],
                "usage_tip": "Call this tool IMMEDIATELY after every user question and your response to maintain conversation context."
            },
            "end_conversation": {
                "template": "Archive our current conversation topic",
                "examples": [
                    "Archive our current conversation topic",
                    "End this discussion and save it to memory"
                ],
                "usage_tip": "Use when switching to a completely different topic or when the current discussion is complete."
            },
            "toggle_multi_model": {
                "template": "Toggle multi-model embeddings: {enabled}",
                "examples": [
                    "Enable multi-model embeddings for better search accuracy",
                    "Disable multi-model embeddings to save resources"
                ],
                "usage_tip": "Enable when you need better search accuracy across diverse content types, disable to reduce resource usage."
            },
            "list_recent_conversations": {
                "template": "Show me my recent conversation history",
                "examples": [
                    "Show me my recent conversation history",
                    "List my last 5 conversations",
                    "What have we discussed recently?"
                ],
                "usage_tip": "Use this to review conversation history or identify conversations that need cleanup."
            },
            "remove_conversation_message": {
                "template": "Remove conversation message with ID: {message_id}",
                "examples": [
                    "Remove conversation message with ID: conv_12345",
                    "Delete this bad conversation: conv_67890"
                ],
                "usage_tip": "Use to remove specific problematic conversation messages that are cluttering memory."
            },
            "remove_recent_conversations": {
                "template": "Remove my last {count} conversations",
                "examples": [
                    "Remove my last 3 conversations",
                    "Clean up the last 10 conversations"
                ],
                "usage_tip": "Use for bulk cleanup of multiple recent problematic conversations."
            },
            "list_recent_documents": {
                "template": "Show me my recent documents in the knowledge base",
                "examples": [
                    "Show me my recent documents in the knowledge base",
                    "List my last 5 added documents",
                    "What reference materials do I have?"
                ],
                "usage_tip": "Use this to review what documents are stored in the knowledge base."
            },
            "remove_document": {
                "template": "Remove document with ID: {document_id}",
                "examples": [
                    "Remove document with ID: doc_12345",
                    "Delete this outdated document: doc_67890"
                ],
                "usage_tip": "Use to remove specific documents that are outdated, incorrect, or no longer relevant."
            },
            "web_search": {
                "template": "Search the web for: {query}",
                "examples": [
                    "Search the web for latest AI news",
                    "Find information about quantum computing advancements",
                    "Look up current weather in Tokyo"
                ],
                "usage_tip": "Use when you need up-to-date information, news, or data not available in local memory."
            },
            "get_current_day": {
                "template": "What is today's date and day?",
                "examples": [
                    "What is today's date and day?",
                    "Tell me the current date and time",
                    "What day of the week is it today?"
                ],
                "usage_tip": "Use for questions about today's date, current day, time, or year information."
            }
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
                "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base with source context awareness for future retrieval. When to use: Use this when you want to permanently store reference material, documentation, code snippets, or any information that should be available for future conversations. How it works: Documents are embedded and stored in the knowledge base with optional metadata and git context. Why useful: Builds a personal knowledge repository with source-aware categorization that can be searched later using get_memory_context.",
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
                                    },
                                    "source_type": {
                                        "type": "string",
                                        "enum": ["chat", "code", "web", "manual"],
                                        "default": "chat",
                                        "description": "Source type for context-aware handling"
                                    },
                                    "repo_url": {
                                        "type": "string",
                                        "description": "Git repository URL (for code documents)"
                                    },
                                    "file_path": {
                                        "type": "string",
                                        "description": "Relative file path in repository (for code documents)"
                                    },
                                    "commit_hash": {
                                        "type": "string",
                                        "description": "Git commit hash for version tracking"
                                    },
                                    "branch": {
                                        "type": "string",
                                        "description": "Git branch name"
                                    },
                                    "version": {
                                        "type": "string",
                                        "description": "Document version identifier"
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
                "description": "PRESERVE CONVERSATION CONTEXT: Add this Q&A exchange to memory so I remember our conversation. Use IMMEDIATELY after every user question and my response to maintain context across our interaction. This ensures I can reference previous parts of our conversation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_message": {
                            "type": "string",
                            "description": "The exact user question/message that was just asked",
                            "minLength": 1
                        },
                        "assistant_message": {
                            "type": "string", 
                            "description": "My complete response to that user question",
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
                "description": "ARCHIVE CURRENT TOPIC: End this conversation topic and archive it for long-term memory. Use when switching to a completely different topic or when the current discussion is complete. This moves our conversation from short-term working memory to long-term storage.",
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
                "description": "REVIEW CONVERSATION HISTORY: Show me recent conversation exchanges that are stored in memory. Use this when I need to see what we've discussed before, or when I want to clean up unwanted conversations. This helps me understand our conversation history and manage stored content.",
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
                "description": "CLEAN UP BAD CONVERSATIONS: Remove a specific problematic conversation message by its ID. Use when other AI models generated bad responses that are cluttering our memory. This helps keep our conversation history clean and relevant.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "ID of the bad message to remove (get this from list_recent_conversations first)"
                        }
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "remove_recent_conversations",
                "description": "BULK CLEANUP: Remove multiple recent bad conversations at once. Use when several recent interactions were problematic and need to be cleared. This is faster than removing conversations one by one.",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of most recent conversations to remove (1-100)",
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["count"]
                }
            },
            {
                "name": "list_recent_documents",
                "description": "REVIEW KNOWLEDGE BASE: Show me recently added documents in the knowledge base. Use this to see what reference materials are available, or to identify documents that need cleanup. This helps me understand what information is stored for future reference.",
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
                "description": "CLEAN UP KNOWLEDGE BASE: Remove a specific document by its ID. Use when a document is outdated, incorrect, or no longer relevant. This keeps the knowledge base focused on useful reference material.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to remove (get this from list_recent_documents first)"
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
        # Special case: web_search is implemented and should be available
        available_tools = [tool for tool in self.tools if tool["name"] not in self.placeholder_tools]
        
        # Add web_search if it's not already included (implementation is complete)
        web_search_tool = next((tool for tool in self.tools if tool["name"] == "web_search"), None)
        if web_search_tool and web_search_tool not in available_tools:
            available_tools.append(web_search_tool)
            
        return available_tools
    
    def get_user_prompt_template(self, tool_name: str) -> Dict[str, Any] | None:
        """Get user prompt template for a specific tool"""
        return self.user_prompt_templates.get(tool_name)
    
    def get_all_user_prompt_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get all user prompt templates"""
        return self.user_prompt_templates
    
    def get_tools_with_templates(self) -> List[Dict[str, Any]]:
        """Get list of available tools with their user prompt templates"""
        tools = self.get_tools()
        result = []
        
        for tool in tools:
            tool_name = tool["name"]
            template = self.get_user_prompt_template(tool_name)
            
            if template:
                tool_with_template = tool.copy()
                tool_with_template["user_prompt_template"] = template
                result.append(tool_with_template)
            else:
                result.append(tool)
        
        return result
    
    def get_tools_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get tools organized by category for better LLM usability"""
        categories = {
            "memory": [],
            "conversation": [],
            "knowledge": [],
            "utilities": []
        }
        
        tools = self.get_tools()
        
        for tool in tools:
            tool_name = tool["name"]
            
            # Categorize tools
            if tool_name in ["get_memory_context", "get_memory_stats"]:
                categories["memory"].append(tool)
            elif tool_name in ["add_conversation", "end_conversation", "list_recent_conversations", 
                             "remove_conversation_message", "remove_recent_conversations"]:
                categories["conversation"].append(tool)
            elif tool_name in ["add_documents", "list_recent_documents", "remove_document"]:
                categories["knowledge"].append(tool)
            elif tool_name in ["toggle_multi_model", "web_search", "get_current_day", "get_current_time"]:
                categories["utilities"].append(tool)
        
        return categories
    
    def get_tools_by_priority(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get tools organized by priority level"""
        priority_levels = {
            "high": [],
            "medium": [],
            "low": []
        }
        
        tools = self.get_tools()
        
        # Define priority mapping
        priority_mapping = {
            "get_memory_context": "high",
            "add_conversation": "high",
            "add_documents": "high",
            "end_conversation": "medium",
            "toggle_multi_model": "medium",
            "list_recent_conversations": "medium",
            "web_search": "medium",
            "get_current_day": "medium",
            "remove_conversation_message": "low",
            "remove_recent_conversations": "low",
            "list_recent_documents": "low",
            "remove_document": "low",
            "get_current_time": "low"
        }
        
        for tool in tools:
            tool_name = tool["name"]
            priority = priority_mapping.get(tool_name, "medium")
            priority_levels[priority].append(tool)
        
        return priority_levels
    
    def get_essential_tools(self) -> List[Dict[str, Any]]:
        """Get essential tools that should always be available to LLMs"""
        essential_tool_names = [
            "get_memory_context",      # Core memory functionality
            "add_conversation",        # Conversation context preservation
            "add_documents",           # Knowledge base management
            "end_conversation",        # Conversation management
            "web_search"               # Current information access
        ]
        
        tools = self.get_tools()
        return [tool for tool in tools if tool["name"] in essential_tool_names]
    
    def get_category_description(self, category: str) -> str:
        """Get description for a category"""
        descriptions = {
            "memory": "Memory and context retrieval tools for accessing user's stored information",
            "conversation": "Conversation management tools for preserving and organizing dialogue history",
            "knowledge": "Knowledge base tools for managing reference materials and documents",
            "utilities": "Utility tools for web search, time information, and system configuration"
        }
        return descriptions.get(category, "General tools")
    
    def get_tools_usage_guide(self) -> str:
        """Generate a comprehensive usage guide for LLMs"""
        categories = self.get_tools_by_category()
        
        guide = "## MCP Tools Usage Guide\n\n"
        guide += "### Tool Categories and Usage Patterns\n\n"
        
        for category, tools in categories.items():
            if tools:
                guide += f"#### {category.title()} Tools\n"
                guide += f"*{self.get_category_description(category)}*\n\n"
                
                for tool in tools:
                    tool_name = tool["name"]
                    template = self.get_user_prompt_template(tool_name)
                    
                    guide += f"**{tool_name}**\n"
                    guide += f"- *Description*: {tool['description']}\n"
                    
                    if template:
                        guide += f"- *User Prompt Template*: {template['template']}\n"
                        guide += f"- *Usage Tip*: {template['usage_tip']}\n"
                    
                    guide += "\n"
        
        guide += "### Priority Guidelines\n"
        guide += "- **High Priority**: Core memory and conversation tools (use frequently)\n"
        guide += "- **Medium Priority**: Supporting tools for enhanced functionality\n"
        guide += "- **Low Priority**: Cleanup and management tools (use as needed)\n\n"
        
        guide += "### Best Practices\n"
        guide += "1. Always use `add_conversation` after each exchange to maintain context\n"
        guide += "2. Use `get_memory_context` before answering questions to retrieve relevant information\n"
        guide += "3. Use `web_search` for current information not available in local memory\n"
        guide += "4. Use `end_conversation` when switching to completely different topics\n"
        guide += "5. Regularly clean up old conversations and documents to maintain system performance\n"
        
        return guide
    
    def get_copy_paste_prompt_list(self) -> str:
        """Generate a copy-paste friendly prompt list for users"""
        categories = self.get_tools_by_category()
        
        prompt_list = "# MCP Tools Prompt List\n\n"
        prompt_list += "Copy and paste these prompts into your MCP client:\n\n"
        
        for category, tools in categories.items():
            if tools:
                prompt_list += f"## {category.title()} Tools\n\n"
                
                for tool in tools:
                    tool_name = tool["name"]
                    template = self.get_user_prompt_template(tool_name)
                    
                    prompt_list += f"### {tool_name}\n"
                    prompt_list += f"**Description**: {tool['description']}\n\n"
                    
                    if template:
                        prompt_list += f"**Prompt Template**:\n```\n{template['template']}\n```\n\n"
                        
                        prompt_list += "**Examples**:\n"
                        for i, example in enumerate(template['examples'], 1):
                            prompt_list += f"{i}. {example}\n"
                        prompt_list += "\n"
                        
                        prompt_list += f"**Usage Tip**: {template['usage_tip']}\n\n"
                    
                    prompt_list += "---\n\n"
        
        prompt_list += "## Quick Reference\n\n"
        prompt_list += "### High Priority (Use Frequently)\n"
        high_priority = [tool for tool in self.get_tools_by_priority()["high"]]
        for tool in high_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"
        
        prompt_list += "\n### Medium Priority (Supporting Tools)\n"
        medium_priority = [tool for tool in self.get_tools_by_priority()["medium"]]
        for tool in medium_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"
        
        prompt_list += "\n### Low Priority (Cleanup/Management)\n"
        low_priority = [tool for tool in self.get_tools_by_priority()["low"]]
        for tool in low_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"
        
        return prompt_list
    
    def get_json_prompt_list(self) -> Dict[str, Any]:
        """Generate JSON format prompt list for programmatic access"""
        categories = self.get_tools_by_category()
        
        json_data = {
            "title": "MCP Tools Prompt List",
            "description": "Copy and paste prompts for MCP tools",
            "generated_at": datetime.now().isoformat(),
            "categories": {},
            "quick_reference": {
                "high_priority": [],
                "medium_priority": [],
                "low_priority": []
            }
        }
        
        # Add categories
        for category, tools in categories.items():
            category_data = {
                "description": self.get_category_description(category),
                "tools": []
            }
            
            for tool in tools:
                tool_name = tool["name"]
                template = self.get_user_prompt_template(tool_name)
                
                tool_data = {
                    "name": tool_name,
                    "description": tool["description"],
                    "input_schema": tool["inputSchema"]
                }
                
                if template:
                    tool_data.update({
                        "prompt_template": template["template"],
                        "examples": template["examples"],
                        "usage_tip": template["usage_tip"]
                    })
                
                category_data["tools"].append(tool_data)
            
            json_data["categories"][category] = category_data
        
        # Add quick reference
        for priority, tools in self.get_tools_by_priority().items():
            for tool in tools:
                json_data["quick_reference"][f"{priority}_priority"].append({
                    "name": tool["name"],
                    "description": tool["description"]
                })
        
        json_data["total_tools"] = len(self.get_tools())
        return json_data
    
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
        
        # Validate message_id
        if not message_id or not message_id.strip():
            return {
                "success": False,
                "message": "No conversation message ID was provided"
            }
        
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
        
        # Validate document_id
        if not document_id or not document_id.strip():
            return {
                "success": False,
                "message": "No document ID was provided"
            }
        
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
