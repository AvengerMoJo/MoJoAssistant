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

    async def search_knowledge_base(self, query: str) -> dict:
        # This endpoint does not exist yet, so we will simulate it by calling the existing one.
        # In a real implementation, you would have a dedicated endpoint for this.
        return await self.get_memory_context(query=query)

    async def search_conversations(self, query: str) -> dict:
        # This endpoint does not exist yet, so we will simulate it by calling the existing one.
        return await self.get_memory_context(query=query)

    async def add_documents(self, documents: list) -> dict:
        url = f"{self.base_url}/api/v1/knowledge/documents"
        try:
            response = await self.client.post(url, json={"documents": documents}, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def get_current_conversation(self) -> dict:
        url = f"{self.base_url}/api/v1/conversation/current"
        try:
            response = await self.client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def end_conversation(self) -> dict:
        url = f"{self.base_url}/api/v1/conversation/end"
        try:
            response = await self.client.post(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def get_memory_stats(self) -> dict:
        url = f"{self.base_url}/api/v1/memory/stats"
        try:
            response = await self.client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def list_embedding_models(self) -> dict:
        url = f"{self.base_url}/api/v1/embeddings/models"
        try:
            response = await self.client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise Exception(f"HTTP Request failed: {e}")

    async def switch_embedding_model(self, model_name: str) -> dict:
        url = f"{self.base_url}/api/v1/embeddings/switch"
        try:
            response = await self.client.post(url, json={"model_name": model_name}, timeout=30.0)
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
    """Search all memory tiers for relevant context."""
    result = await client.get_memory_context(query=query, max_items=max_items)
    return json.dumps(result)

@mcp.tool()
async def search_knowledge_base(query: str) -> str:
    """Search for information exclusively within the knowledge base."""
    result = await client.search_knowledge_base(query=query)
    return json.dumps(result)

@mcp.tool()
async def search_conversations(query: str) -> str:
    """Search for past conversations in the archival memory."""
    result = await client.search_conversations(query=query)
    return json.dumps(result)

@mcp.tool()
async def add_documents(documents: list) -> str:
    """Add documents to the knowledge base."""
    result = await client.add_documents(documents=documents)
    return json.dumps(result)

@mcp.tool()
async def get_current_conversation() -> str:
    """Get the messages from the current working memory."""
    result = await client.get_current_conversation()
    return json.dumps(result)

@mcp.tool()
async def end_conversation() -> str:
    """End the current conversation and archive it to memory."""
    result = await client.end_conversation()
    return json.dumps(result)

@mcp.tool()
async def get_memory_stats() -> str:
    """Get comprehensive statistics about the memory system."""
    result = await client.get_memory_stats()
    return json.dumps(result)

@mcp.tool()
async def list_embedding_models() -> str:
    """List the available embedding models."""
    result = await client.list_embedding_models()
    return json.dumps(result)

@mcp.tool()
async def switch_embedding_model(model_name: str) -> str:
    """Switch to a different embedding model."""
    result = await client.switch_embedding_model(model_name=model_name)
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
