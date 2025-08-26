import sys
import json
import os
import requests

# --- MCPClient Class ---
# This is the same client we've used before to communicate with the FastAPI service
class MCPClient:
    def __init__(self, base_url: str, api_key: str = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def _make_request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"HTTP Request failed: {e}", file=sys.stderr)
            raise

    def get_memory_context(self, query: str, max_items: int = 10):
        data = {"query": query, "max_items": max_items}
        return self._make_request("POST", "/api/v1/memory/context", json=data)

    def add_documents(self, documents: list):
        data = {"documents": documents}
        return self._make_request("POST", "/api/v1/knowledge/documents", json=data)

# --- Main Stdio Handling Logic ---
def main():
    # Get config from environment variables
    api_key = os.getenv("MCP_API_KEY")
    base_url = "https://ai.avengergear.com" # Assuming this is constant

    if not api_key:
        print(json.dumps({"error": "MCP_API_KEY environment variable not set"}), file=sys.stderr)
        return

    client = MCPClient(base_url=base_url, api_key=api_key)

    # Read the API description from the file
    try:
        # IMPORTANT: The path to this file is relative to where the script is run from
        with open("config/mcp_api_description.json", "r") as f:
            api_description = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": "mcp_api_description.json not found in config/ directory"}), file=sys.stderr)
        return

    # Process requests from stdin in a loop
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON input"}), file=sys.stderr)
            continue

        response = None
        request_id = request.get("id")

        if request.get("method") == "ListTools":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": api_description}
            }

        elif request.get("method") == "CallTool":
            tool_name = request["params"]["name"]
            tool_args = request["params"]["arguments"]

            try:
                if tool_name == "get_memory_context":
                    result = client.get_memory_context(**tool_args)
                elif tool_name == "add_documents":
                    result = client.add_documents(**tool_args)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")
                
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result)}]}
                }

            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(e)}
                }

        if response:
            # Write the response to stdout
            print(json.dumps(response))
            sys.stdout.flush()

if __name__ == "__main__":
    main()