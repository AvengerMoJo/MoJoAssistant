#!/usr/bin/env python3
"""
Fixed MCP Server for MoJoAssistant
Proper JSON-RPC 2.0 implementation that passes Claude Desktop validation
"""
import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Any, Dict, List, Optional

class MoJoMCPServer:
    """Fixed MCP Server for MoJoAssistant integration"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.tools = [
            {
                "name": "search_memory",
                "description": "Search MoJoAssistant's memory for relevant context and information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant information"
                        },
                        "max_items": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "add_knowledge",
                "description": "Add new knowledge or information to MoJoAssistant's memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The content/knowledge to add to memory"
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional title or topic for the knowledge",
                            "default": "User Input"
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "get_memory_stats",
                "description": "Get statistics about MoJoAssistant's memory usage and status",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    
    def make_http_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make HTTP request using only standard library"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == "GET":
                with urllib.request.urlopen(url, timeout=10) as response:
                    return json.loads(response.read().decode())
            
            elif method == "POST":
                json_data = json.dumps(data or {}).encode('utf-8')
                req = urllib.request.Request(
                    url,
                    data=json_data,
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())
                    
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e}"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response: {e}"}
        except Exception as e:
            return {"error": f"Request failed: {e}"}
    
    def search_memory(self, query: str, max_items: int = 5) -> str:
        """Search MoJoAssistant memory"""
        response = self.make_http_request(
            "POST", 
            "/api/v1/memory/context",
            {"query": query, "max_items": max_items, "include_sources": True}
        )
        
        if "error" in response:
            return f"Error searching memory: {response['error']}"
        
        context_items = response.get("context_items", [])
        if not context_items:
            return "No relevant information found in memory."
        
        results = []
        for item in context_items:
            content = item.get("content", "")
            score = item.get("relevance_score", 0)
            source = item.get("source", "unknown")
            results.append(f"• {content[:200]}{'...' if len(content) > 200 else ''} (relevance: {score:.2f}, source: {source})")
        
        return f"Found {len(results)} relevant items:\n\n" + "\n\n".join(results)
    
    def add_knowledge(self, content: str, title: str = "User Input") -> str:
        """Add knowledge to MoJoAssistant"""
        response = self.make_http_request(
            "POST",
            "/api/v1/knowledge/documents",
            {
                "documents": [{
                    "content": content,
                    "metadata": {
                        "title": title,
                        "source": "claude_desktop",
                        "added_via": "mcp_server"
                    }
                }]
            }
        )
        
        if "error" in response:
            return f"Error adding knowledge: {response['error']}"
        
        results = response.get("results", [])
        if results and results[0].get("status") == "success":
            return f"✅ Successfully added knowledge: '{title}' to MoJoAssistant memory"
        else:
            return "❌ Failed to add knowledge to memory"
    
    def get_memory_stats(self) -> str:
        """Get memory statistics"""
        response = self.make_http_request("GET", "/api/v1/memory/stats")
        
        if "error" in response:
            return f"Error getting stats: {response['error']}"
        
        working_memory = response.get("working_memory", {})
        knowledge_base = response.get("knowledge_base", {})
        embedding = response.get("embedding", {})
        system = response.get("system", {})
        
        stats_text = f"""📊 MoJoAssistant Memory Statistics:

🧠 Working Memory: {working_memory.get('messages', 0)} messages
📚 Knowledge Base: {knowledge_base.get('items', 0)} items
🔧 Embedding Model: {embedding.get('model_name', 'unknown')}
⚡ System Uptime: {system.get('uptime_seconds', 0)} seconds

Memory is {'healthy' if knowledge_base.get('items', 0) > 0 else 'empty - consider adding some knowledge!'}"""
        
        return stats_text
    
    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> str:
        """Handle tool calls"""
        try:
            if name == "search_memory":
                query = arguments.get("query", "")
                max_items = arguments.get("max_items", 5)
                return self.search_memory(query, max_items)
            
            elif name == "add_knowledge":
                content = arguments.get("content", "")
                title = arguments.get("title", "User Input")
                return self.add_knowledge(content, title)
            
            elif name == "get_memory_stats":
                return self.get_memory_stats()
            
            else:
                return f"Unknown tool: {name}"
                
        except Exception as e:
            return f"Error executing tool {name}: {e}"
    
    def create_response(self, request_id: Any, result: Any = None, error: Any = None) -> Dict[str, Any]:
        """Create properly formatted JSON-RPC 2.0 response"""
        response = {
            "jsonrpc": "2.0",
            "id": request_id
        }
        
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result
            
        return response
    
    def create_error(self, code: int, message: str, data: Any = None) -> Dict[str, Any]:
        """Create JSON-RPC 2.0 error object"""
        error = {
            "code": code,
            "message": message
        }
        if data is not None:
            error["data"] = data
        return error
    
    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP requests with proper JSON-RPC 2.0 format"""
        # Validate basic JSON-RPC structure
        if not isinstance(request, dict):
            return self.create_response(
                None, 
                error=self.create_error(-32600, "Invalid Request", "Request must be a JSON object")
            )
        
        jsonrpc = request.get("jsonrpc")
        if jsonrpc != "2.0":
            return self.create_response(
                request.get("id"),
                error=self.create_error(-32600, "Invalid Request", "jsonrpc must be '2.0'")
            )
        
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        if not method:
            return self.create_response(
                request_id,
                error=self.create_error(-32600, "Invalid Request", "method is required")
            )
        
        try:
            if method == "initialize":
                return self.create_response(request_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "mojo-assistant-mcp",
                        "version": "1.0.0"
                    }
                })
            
            elif method == "tools/list":
                return self.create_response(request_id, {
                    "tools": self.tools
                })
            
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                
                if not tool_name:
                    return self.create_response(
                        request_id,
                        error=self.create_error(-32602, "Invalid params", "tool name is required")
                    )
                
                result_text = self.handle_tool_call(tool_name, arguments)
                
                return self.create_response(request_id, {
                    "content": [
                        {
                            "type": "text",
                            "text": result_text
                        }
                    ]
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
    
    def run(self):
        """Run the MCP server"""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                print(json.dumps(response))
                sys.stdout.flush()
                
            except json.JSONDecodeError as e:
                error_response = self.create_response(
                    None,
                    error=self.create_error(-32700, "Parse error", str(e))
                )
                print(json.dumps(error_response))
                sys.stdout.flush()
            except Exception as e:
                error_response = self.create_response(
                    None,
                    error=self.create_error(-32603, "Internal error", str(e))
                )
                print(json.dumps(error_response))
                sys.stdout.flush()

def main():
    """Main entry point"""
    server = MoJoMCPServer()
    server.run()

if __name__ == "__main__":
    main()
