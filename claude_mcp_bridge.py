#!/usr/bin/env python3
"""
MCP Bridge for Claude Desktop Integration
Bridges between Claude Desktop MCP protocol and MoJoAssistant MCP service
"""

import asyncio
import json
import subprocess
import sys
from typing import Any, Dict, List

class ClaudeMCPBridge:
    def __init__(self):
        self.mcp_process = None
        
    async def start_mcp_service(self) -> None:
        """Start MoJoAssistant MCP service"""
        try:
            # Start the MCP service process
            self.mcp_process = await asyncio.create_subprocess_exec(
                sys.executable, "/home/alex/Development/Personal/MoJoAssistant/unified_mcp_server.py",
                "--mode", "stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except Exception as e:
            print(f"Failed to start MCP service: {e}", file=sys.stderr)
            sys.exit(1)
    
    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request"""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "MoJoAssistant",
                "version": "1.0.0",
                "description": "MoJoAssistant Memory Communication Protocol service"
            }
        }
    
    async def handle_list_tools(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools listing request"""
        # Forward to MCP service
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": params
        }
        
        response = await self.send_request(request)
        if response and "result" in response:
            return response["result"]
        return {"tools": []}
    
    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool call request"""
        # Forward to MCP service
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        
        response = await self.send_request(request)
        if response and "result" in response:
            return response["result"]
        return {"error": "Failed to call tool"}
    
    async def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to MCP service and get response"""
        if not self.mcp_process:
            return {}
            
        try:
            # Send request
            request_data = json.dumps(request) + "\n"
            self.mcp_process.stdin.write(request_data.encode())
            await self.mcp_process.stdin.drain()
            
            # Read response
            response_line = await self.mcp_process.stdout.readline()
            if response_line:
                response_data = response_line.decode().strip()
                return json.loads(response_data)
                
        except Exception as e:
            print(f"Error communicating with MCP service: {e}", file=sys.stderr)
            
        return {}
    
    async def handle_claude_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle requests from Claude Desktop"""
        method = request.get("method")
        params = request.get("params", {})
        
        if method == "initialize":
            return await self.handle_initialize(params)
        elif method == "tools/list":
            return await self.handle_list_tools(params)
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            return await self.handle_tool_call(tool_name, tool_args)
        else:
            return {"error": f"Unknown method: {method}"}
    
    async def run(self) -> None:
        """Main bridge loop"""
        await self.start_mcp_service()
        
        try:
            while True:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                
                if not line:
                    break
                    
                try:
                    request = json.loads(line.strip())
                    response = await self.handle_claude_request(request)
                    
                    # Send response back
                    response_data = json.dumps(response) + "\n"
                    print(response_data, end="")
                    sys.stdout.flush()
                    
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error processing request: {e}", file=sys.stderr)
                    
        except KeyboardInterrupt:
            pass
        finally:
            if self.mcp_process:
                self.mcp_process.terminate()
                await self.mcp_process.wait()

async def main():
    bridge = ClaudeMCPBridge()
    await bridge.run()

if __name__ == "__main__":
    asyncio.run(main())