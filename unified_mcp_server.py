#!/usr/bin/env python3
"""
Unified MCP Server for MoJoAssistant
Supports both STDIO (for Claude Desktop) and HTTP (for Android/Web)
"""
import os
import sys
import json
import time
import uuid
import argparse
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "app"))

# Load environment variables from .env file
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment variables from {env_path}")
else:
    print(f"Warning: .env file not found at {env_path}")

# Import MoJoAssistant components
from app.services.hybrid_memory_service import HybridMemoryService
from app.config.logging_config import setup_logging, get_logger
from app.config.config_loader import load_embedding_config

# MCP config integration will be added later



class UnifiedMCPServer:
    """Unified MCP Server supporting both STDIO and HTTP protocols"""
    
    def __init__(self):
        self.memory_service = None
        self.logger = None
        self.start_time = time.time()
        
        # Load MCP configuration using centralized config module
        try:
            # Import the centralized configuration module
            from app.config.mcp_config import load_mcp_config
            self.mcp_config = load_mcp_config()
            if self.logger:
                self.logger.info("Using centralized MCP configuration module")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Could not import centralized config module ({e}), using fallback")
            # Fallback to direct environment variable access
            self.mcp_config = {
                'google_api_key': os.getenv("GOOGLE_API_KEY"),
                'google_search_engine_id': os.getenv("GOOGLE_SEARCH_ENGINE_ID"),
                'mcp_require_auth': os.getenv("MCP_REQUIRE_AUTH", "true").lower() == "true",
                'mcp_api_key': os.getenv("MCP_API_KEY"),
                'log_level': os.getenv("LOG_LEVEL", "INFO")
            }
        self.tools = [
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
                "name": "system_info",
                "description": "Get system information including server status, uptime, and configuration details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "system_health",
                "description": "Check system health and performance metrics including memory usage, response times, and error rates.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
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
    
    def _format_uptime(self, uptime_seconds: float) -> str:
        """Format uptime in human readable format"""
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    async def initialize_memory_service(self):
        """Initialize the memory service"""
        try:
            setup_logging()
            self.logger = get_logger(__name__)
            
            embedding_config = load_embedding_config()
            embed_config = embedding_config["embedding_models"]["default"]
            
            self.memory_service = HybridMemoryService(
                data_dir=embedding_config.get("memory_settings", {}).get("data_directory", ".memory"),
                embedding_model=embed_config.get("model_name", "BAAI/bge-m3"),
                embedding_backend=embed_config.get("backend", "huggingface"),
                embedding_device=embed_config.get("device"),
                config=embedding_config,  # Pass full config for multi-model access
                multi_model_enabled=True  # Start with multi-model enabled for testing
            )
            
            self.logger.info("Memory service initialized successfully")
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize memory service: {e}")
            raise
    
    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool calls with proper error handling"""
        import time
        """Handle tool calls and return structured response"""
        try:
            if self.logger:
                self.logger.info(f"Handling tool call: {name} with args: {arguments}")
            
            if not self.memory_service:
                raise Exception("Memory service not initialized")
            
            if name == "get_memory_context":
                query = arguments.get("query", "")
                max_items = arguments.get("max_items", 10)
                
                context_items = self.memory_service.get_context_for_query(query, max_items=max_items)
                
                return {
                    "query": query,
                    "context_items": context_items,
                    "total_items": len(context_items)
                }
            
            
            elif name == "add_conversation":
                user_message = arguments.get("user_message", "")
                assistant_message = arguments.get("assistant_message", "")
                
                if self.logger:
                    self.logger.info(f"Adding conversation: user={len(user_message)} chars, assistant={len(assistant_message)} chars")
                
                # Add both messages to working memory
                self.memory_service.add_user_message(user_message)
                self.memory_service.add_assistant_message(assistant_message)
                
                if self.logger:
                    self.logger.info("Conversation messages added successfully")
                
                return {
                    "status": "success", 
                    "message": "Conversation exchange added to working memory",
                    "user_message_length": len(user_message),
                    "assistant_message_length": len(assistant_message)
                }
            
            elif name == "add_documents":
                documents = arguments.get("documents", [])
                results = []
                
                if self.logger:
                    self.logger.info(f"Adding {len(documents)} documents")
                
                for i, doc in enumerate(documents):
                    try:
                        content = doc.get("content", "") if isinstance(doc, dict) else str(doc)
                        metadata = doc.get("metadata", {}) if isinstance(doc, dict) else {}
                        
                        if self.logger:
                            self.logger.info(f"Adding document {i+1}: content={len(content)} chars")
                        
                        self.memory_service.add_to_knowledge_base(content, metadata)
                        results.append({"status": "success", "message": "Document added"})
                        
                        if self.logger:
                            self.logger.info(f"Document {i+1} added successfully")
                            
                    except Exception as e:
                        if self.logger:
                            self.logger.error(f"Failed to add document {i+1}: {e}")
                        results.append({"status": "error", "message": str(e)})
                
                return {"results": results, "total_processed": len(documents)}
            
            elif name == "get_memory_stats":
                # Use multi-model stats if available
                if hasattr(self.memory_service, 'get_multi_model_stats'):
                    return self.memory_service.get_multi_model_stats()
                else:
                    return self.memory_service.get_memory_stats()
            
            elif name == "end_conversation":
                self.memory_service.end_conversation()
                return {"status": "success", "message": "Conversation ended and archived"}
            
            elif name == "toggle_multi_model":
                enabled = arguments.get("enabled", False)
                
                if enabled:
                    try:
                        success = self.memory_service.enable_multi_model()
                        status = "enabled" if success else "failed_to_enable"
                        message = "Multi-model embedding enabled" if success else "Failed to enable multi-model"
                    except Exception as e:
                        if self.logger:
                            self.logger.error(f"Failed to enable multi-model: {e}")
                        success = False
                        status = "failed_to_enable"
                        message = f"Failed to enable multi-model: {str(e)}"
                else:
                    try:
                        success = self.memory_service.disable_multi_model()
                        status = "disabled" if success else "failed_to_disable" 
                        message = "Multi-model embedding disabled" if success else "Failed to disable multi-model"
                    except Exception as e:
                        if self.logger:
                            self.logger.error(f"Failed to disable multi-model: {e}")
                        success = False
                        status = "failed_to_disable"
                        message = f"Failed to disable multi-model: {str(e)}"
                
                return {
                    "status": status,
                    "message": message,
                    "multi_model_enabled": enabled if success else not enabled,
                    "available_models": list(getattr(self.memory_service, 'embedding_models', {}).keys())
                }
            
            elif name == "list_recent_conversations":
                limit = arguments.get("limit", 10)
                conversations = self.memory_service.list_recent_conversations(limit)
                return {
                    "conversations": conversations,
                    "total": len(conversations),
                    "message": f"Retrieved {len(conversations)} recent conversations"
                }
            
            elif name == "remove_conversation_message":
                message_id = arguments.get("message_id", "")
                success = self.memory_service.remove_conversation_message(message_id)
                return {
                    "success": success,
                    "message": f"Conversation message {message_id} {'removed' if success else 'not found'}"
                }
            
            elif name == "remove_recent_conversations":
                count = arguments.get("count", 1)
                removed_count = self.memory_service.remove_recent_conversations(count)
                return {
                    "removed_count": removed_count,
                    "message": f"Removed {removed_count} recent conversations"
                }
            
            elif name == "list_recent_documents":
                limit = arguments.get("limit", 10)
                documents = self.memory_service.list_recent_documents(limit)
                return {
                    "documents": documents,
                    "total": len(documents),
                    "message": f"Retrieved {len(documents)} recent documents"
                }
            
            elif name == "remove_document":
                document_id = arguments.get("document_id", "")
                success = self.memory_service.remove_document(document_id)
                return {
                    "success": success,
                    "message": f"Document {document_id} {'removed' if success else 'not found'}"
                }
            
            elif name == "web_search":
                query = arguments.get("query", "")
                max_results = arguments.get("limit", 10)
                
                try:
                    # Import here to avoid dependency issues if not available
                    import urllib.request
                    import urllib.parse
                    import json
                    import time
                    
                    # Try Google Custom Search API first (if API key is available)
                    google_api_key = self.mcp_config['google_api_key']
                    search_engine_id = self.mcp_config['google_search_engine_id']
                    
                    if self.logger:
                        self.logger.info(f"Google API Key: {'***' if google_api_key else 'Not set'}")
                        self.logger.info(f"Search Engine ID: {'***' if search_engine_id else 'Not set'}")
                    
                    if google_api_key and search_engine_id:
                        try:
                            # Use Google Custom Search API
                            encoded_query = urllib.parse.quote(query)
                            url = f"https://www.googleapis.com/customsearch/v1?key={google_api_key}&cx={search_engine_id}&q={encoded_query}&num={min(max_results, 10)}"
                            
                            if self.logger:
                                self.logger.info(f"Performing Google search for: {query}")
                            
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
                            
                            if self.logger:
                                self.logger.info(f"Google search returned {len(results)} results")
                            
                            return {
                                "query": query,
                                "results": results,
                                "total_results": search_result.get('searchInformation', {}).get('totalResults', len(results)),
                                "source": "google"
                            }
                        except Exception as google_e:
                            if self.logger:
                                self.logger.error(f"Google API failed ({google_e})")
                            return {
                                "error": f"Google API failed: {str(google_e)}",
                                "query": query,
                                "results": [],
                                "total_results": 0
                            }
                    
                    # No Google credentials available
                    if self.logger:
                        self.logger.error("Google API credentials not available. Please configure GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID.")
                    return {
                        "error": "Google API credentials not available. Please configure GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID.",
                        "query": query,
                        "results": [],
                        "total_results": 0
                    }
                    
                    if self.logger:
                        self.logger.info(f"Performing DuckDuckGo search for: {query}")
                    
                    # DuckDuckGo fallback removed - Google API is now required
                    
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Web search failed: {e}")
                    return {
                        "error": f"Web search failed: {str(e)}",
                        "query": query,
                        "results": [],
                        "total_results": 0
                    }
            
            elif name == "get_current_day":
                from datetime import datetime
                
                now = datetime.now()
                
                # Format date information
                date_info = {
                    "current_date": now.strftime("%Y-%m-%d"),
                    "year": now.year,
                    "day_of_week": now.strftime("%A"),
                    "day_of_year": now.timetuple().tm_yday,
                    "week_of_year": now.isocalendar()[1],
                    "time": now.strftime("%H:%M:%S"),
                    "timezone": "Local",
                    "timestamp": int(now.timestamp())
                }
                
                if self.logger:
                    self.logger.info(f"Current day: {date_info['day_of_week']}, {date_info['current_date']}")
                
                return date_info
            
            elif name == "get_current_time":
                from datetime import datetime
                
                now = datetime.now()
                
                # Format time information
                time_info = {
                    "current_time": now.strftime("%H:%M:%S"),
                    "current_date": now.strftime("%Y-%m-%d"),
                    "day_of_week": now.strftime("%A"),
                    "iso_format": now.isoformat(),
                    "timezone": "Local",
                    "timestamp": int(now.timestamp()),
                    "hour": now.hour,
                    "minute": now.minute,
                    "second": now.second,
                    "am_pm": "AM" if now.hour < 12 else "PM",
                    "hour_12": now.hour % 12 or 12
                }
                
                if self.logger:
                    self.logger.info(f"Current time: {time_info['current_time']} ({time_info['timezone']})")
                
                return time_info
            
            elif name == "system_info":
                import time
                uptime = time.time() - self.start_time
                return {
                    "server_name": "mojo-assistant",
                    "version": "1.0.0",
                    "uptime_seconds": uptime,
                    "uptime_formatted": self._format_uptime(uptime),
                    "mode": "stdio" if hasattr(self, 'stdio_mode') else "http",
                    "memory_service": "initialized" if self.memory_service else "not_initialized",
                    "multi_model_enabled": getattr(self.memory_service, 'multi_model_enabled', False) if self.memory_service else False,
                    "google_api_configured": bool(self.mcp_config.get('google_api_key')),
                    "google_search_engine_configured": bool(self.mcp_config.get('google_search_engine_id')),
                    "mcp_auth_required": self.mcp_config.get('mcp_require_auth', False),
                    "log_level": self.mcp_config.get('log_level', 'INFO')
                }
            
            elif name == "system_health":
                # Get system metrics
                try:
                    import psutil
                    memory_info = psutil.virtual_memory()
                    disk_info = psutil.disk_usage('/')
                    cpu_percent = psutil.cpu_percent(interval=0.1)
                except ImportError:
                    # Fallback if psutil is not available
                    cpu_percent = 0
                    memory_info = None
                    disk_info = None
                
                # Get memory service metrics if available
                memory_metrics = {}
                if self.memory_service:
                    try:
                        stats = self.memory_service.get_memory_stats()
                        memory_metrics = stats
                    except Exception as e:
                        memory_metrics = {"error": str(e)}
                
                return {
                    "system_metrics": {
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_info.percent if memory_info else 0,
                        "memory_available_gb": round(memory_info.available / (1024**3), 2) if memory_info else 0,
                        "disk_percent": disk_info.percent if disk_info else 0,
                        "disk_free_gb": round(disk_info.free / (1024**3), 2) if disk_info else 0
                    },
                    "memory_service_metrics": memory_metrics,
                    "server_health": "healthy" if cpu_percent < 90 and (memory_info.percent < 90 if memory_info else True) else "degraded",
                    "timestamp": time.time()
                }
            
            else:
                raise Exception(f"Unknown tool: {name}")
                
        except Exception as e:
            return {"error": str(e)}
    
    # === STDIO Protocol (for Claude Desktop) ===
    
    def create_response(self, request_id: Any, result: Any = None, error: Any = None) -> Dict[str, Any]:
        """Create JSON-RPC 2.0 response"""
        response = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result
        return response
    
    def create_error(self, code: int, message: str, data: Any = None) -> Dict[str, Any]:
        """Create JSON-RPC 2.0 error object"""
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return error
    
    async def handle_stdio_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle STDIO MCP requests"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            if method == "initialize":
                return self.create_response(request_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mojo-assistant", "version": "1.0.0"}
                })
            
            elif method == "tools/list":
                return self.create_response(request_id, {"tools": self.tools})
            
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                
                result = await self.handle_tool_call(tool_name, arguments)
                
                if "error" in result:
                    return self.create_response(
                        request_id,
                        error=self.create_error(-32603, "Tool execution failed", result["error"])
                    )
                
                return self.create_response(request_id, {
                    "content": [{"type": "text", "text": json.dumps(result)}]
                })
            
            else:
                return self.create_response(
                    request_id,
                    error=self.create_error(-32601, "Method not found", f"Unknown method: {method}")
                )
                
        except Exception as e:
            return self.create_response(
                request_id,
                error=self.create_error(-32603, "Internal error", str(e))
            )
    
    async def run_stdio(self):
        """Run STDIO protocol server"""
        await self.initialize_memory_service()
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                request = json.loads(line)
                response = await self.handle_stdio_request(request)
                print(json.dumps(response))
                sys.stdout.flush()
                
            except json.JSONDecodeError as e:
                error_response = self.create_response(
                    None,
                    error=self.create_error(-32700, "Parse error", str(e))
                )
                print(json.dumps(error_response))
                sys.stdout.flush()
    
    # === HTTP Protocol (for Android/Web) ===
    
    def create_fastapi_app(self):
        """Create FastAPI app for HTTP protocol"""
        from fastapi import FastAPI, HTTPException, Header, Depends, Request
        from fastapi.middleware.cors import CORSMiddleware
        
        app = FastAPI(title="MoJoAssistant MCP Service", version="1.0.0")
        
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        async def verify_api_key(
            mcp_api_key: Optional[str] = Header(None, alias="MCP-API-Key"),
            x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
            authorization: Optional[str] = Header(None)
        ):
            """Verify API key from client (multiple header formats supported)"""
            # Try different header formats
            api_key = mcp_api_key or x_api_key
            
            # Try Authorization header (Bearer token)
            if not api_key and authorization and authorization.startswith("Bearer "):
                api_key = authorization[7:]  # Remove "Bearer " prefix
            
            # For development, allow requests without API key if MCP_REQUIRE_AUTH is false
            if not api_key and not self.mcp_config['mcp_require_auth']:
                return None
                
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required in MCP-API-Key, X-API-Key, or Authorization header")
            
            return api_key
        
        @app.on_event("startup")
        async def startup():
            await self.initialize_memory_service()
        
        @app.api_route("/", methods=["GET", "POST"])
        async def mcp_endpoint(raw_request: Request, api_key: Optional[str] = Depends(verify_api_key)):
            """Handle all MCP requests"""
            from fastapi.responses import Response
            
            # Get raw request body for debugging
            try:
                body = await raw_request.body()
                content_type = raw_request.headers.get("content-type", "")
                
                print(f"DEBUG: Method: {raw_request.method}", file=sys.stderr)
                print(f"DEBUG: Content-Type: {content_type}", file=sys.stderr)
                print(f"DEBUG: Headers: {dict(raw_request.headers)}", file=sys.stderr)
                print(f"DEBUG: Raw body: {body}", file=sys.stderr)
                
                # Parse JSON if present
                if body:
                    request = json.loads(body.decode('utf-8'))
                else:
                    request = {"method": "initialize", "id": 1}
                    
                print(f"DEBUG: Parsed request: {request}", file=sys.stderr)
                
            except Exception as e:
                print(f"DEBUG: Error parsing request: {e}", file=sys.stderr)
                request = {"method": "initialize", "id": 1}
            
            # Handle JSON-RPC request
            method = request.get("method", "initialize")
            request_id = request.get("id", 1)
            params = request.get("params", {})
            
            # Handle notifications/initialized (return 202 with empty body)
            if method == "notifications/initialized":
                return Response(status_code=202)
            
            if method == "initialize":
                response_data = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "mojo-assistant", "version": "1.0.0"}
                    }
                }
            elif method == "tools/list":
                response_data = {
                    "jsonrpc": "2.0", 
                    "id": request_id,
                    "result": {"tools": self.tools}
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                
                result = await self.handle_tool_call(tool_name, arguments)
                
                if "error" in result:
                    response_data = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": result["error"]}
                    }
                else:
                    response_data = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": json.dumps(result)}]}
                    }
            else:
                response_data = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
            
            # Return as SSE format like Context7
            sse_content = f"event: message\ndata: {json.dumps(response_data)}\n\n"
            return Response(
                content=sse_content,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive"
                }
            )
        
        # Legacy REST endpoints for direct HTTP access
        @app.post("/api/v1/memory/context")
        async def get_memory_context_rest(query_data: Dict[str, Any], api_key: Optional[str] = Depends(verify_api_key)):
            result = await self.handle_tool_call("get_memory_context", query_data)
            if "error" in result:
                raise HTTPException(status_code=500, detail=result["error"])
            return result
        
        @app.get("/api/v1/memory/stats")
        async def get_memory_stats_rest(api_key: Optional[str] = Depends(verify_api_key)):
            result = await self.handle_tool_call("get_memory_stats", {})
            if "error" in result:
                raise HTTPException(status_code=500, detail=result["error"])
            return result
        
        # System endpoints
        @app.get("/system/info")
        async def system_info_rest(api_key: Optional[str] = Depends(verify_api_key)):
            result = await self.handle_tool_call("system_info", {})
            if "error" in result:
                raise HTTPException(status_code=500, detail=result["error"])
            return result
        
        @app.get("/system/health")
        async def system_health_rest(api_key: Optional[str] = Depends(verify_api_key)):
            result = await self.handle_tool_call("system_health", {})
            if "error" in result:
                raise HTTPException(status_code=500, detail=result["error"])
            return result
        
        return app
    
    async def run_http(self, host: str = "0.0.0.0", port: int = 8000):
        """Run HTTP protocol server"""
        import uvicorn
        app = self.create_fastapi_app()
        
        config = uvicorn.Config(
            app, 
            host=host, 
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Unified MCP Server")
    parser.add_argument("--mode", choices=["stdio", "http"], default="stdio",
                       help="Protocol mode: stdio for Claude Desktop, http for Android/Web")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (http mode only)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (http mode only)")
    
    args = parser.parse_args()
    
    server = UnifiedMCPServer()
    
    if args.mode == "stdio":
        print("Starting STDIO MCP server for Claude Desktop...", file=sys.stderr)
        asyncio.run(server.run_stdio())
    else:
        print(f"Starting HTTP MCP server on {args.host}:{args.port}...", file=sys.stderr)
        asyncio.run(server.run_http(args.host, args.port))

if __name__ == "__main__":
    main()
