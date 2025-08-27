import os
import sys
import json
import httpx
from mcp.server.fastmcp import FastMCP

# --- MCPClient Class for Backend Integration ---
class MCPClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.client = httpx.AsyncClient(headers={"X-API-Key": api_key})

    async def get_memory_context(self, query: str, max_items: int = 10) -> dict:
        url = f"{self.base_url}/api/v1/memory/context"
        try:
            response = await self.client.post(url, json={"query": query, "max_items": max_items}, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def add_documents(self, documents: list) -> dict:
        url = f"{self.base_url}/api/v1/knowledge/documents"
        try:
            response = await self.client.post(url, json={"documents": documents}, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def close(self):
        await self.client.aclose()

# --- Initialize FastMCP Server ---
api_key = os.getenv("MCP_API_KEY")
if not api_key:
    raise ValueError("MCP_API_KEY environment variable not set")

base_url = "https://ai.avengergear.com"
client = MCPClient(base_url=base_url, api_key=api_key)
mcp = FastMCP("mojo-assistant")

# --- Define Tools ---
@mcp.tool()
async def get_memory_context(query: str, max_items: int = 10) -> str:
    """Retrieve memory context for a given query."""
    result = await client.get_memory_context(query=query, max_items=max_items)
    return json.dumps(result)

@mcp.tool()
async def add_documents(documents: list) -> str:
    """Add documents to the knowledge base."""
    result = await client.add_documents(documents=documents)
    return json.dumps(result)

# --- Run the Server ---
if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.stderr.flush()
        raise
    finally:
        import anyio
        anyio.run(client.close)
