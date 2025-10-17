# MCP Prompt Endpoints

This document describes the new REST API endpoints that provide MCP tools prompt suggestions for easy copy-paste into your MCP client.

## Available Endpoints

### 1. Get Copy-Paste Prompt List
**Endpoint:** `GET /api/v1/prompts`  
**Format:** Markdown  
**Description:** Returns a formatted list of all MCP tools with their prompt templates, examples, and usage tips.

**Response:**
```json
{
  "status": "success",
  "format": "markdown",
  "content": "# MCP Tools Prompt List\n\nCopy and paste these prompts...",
  "total_tools": 12,
  "generated_at": "2025-10-17T09:20:50Z"
}
```

### 2. Get JSON Prompt List
**Endpoint:** `GET /api/v1/prompts/json`  
**Format:** JSON  
**Description:** Returns structured data with all tool information, templates, and categorization.

**Response:**
```json
{
  "status": "success",
  "format": "json",
  "data": {
    "title": "MCP Tools Prompt List",
    "categories": {
      "memory": {
        "description": "Memory and context retrieval tools...",
        "tools": [...]
      }
    },
    "quick_reference": {
      "high_priority": [...],
      "medium_priority": [...],
      "low_priority": [...]
    }
  },
  "total_tools": 12,
  "generated_at": "2025-10-17T09:20:50Z"
}
```

### 3. Get Organized Categories
**Endpoint:** `GET /api/v1/prompts/categories`  
**Format:** JSON  
**Description:** Returns tools organized by category and priority level.

**Response:**
```json
{
  "status": "success",
  "categories": {
    "memory": {
      "description": "Memory and context retrieval tools...",
      "tools_count": 1,
      "tools": [...]
    },
    "conversation": {...},
    "knowledge": {...},
    "utilities": {...}
  },
  "priority_levels": {
    "high": {...},
    "medium": {...},
    "low": {...}
  },
  "total_tools": 12,
  "generated_at": "2025-10-17T09:20:50Z"
}
```

### 4. Get Usage Guide
**Endpoint:** `GET /api/v1/prompts/usage-guide`  
**Format:** Markdown  
**Description:** Returns a comprehensive usage guide with best practices and tool categories.

**Response:**
```json
{
  "status": "success",
  "format": "markdown",
  "content": "## MCP Tools Usage Guide\n\n### Tool Categories...",
  "generated_at": "2025-10-17T09:20:50Z"
}
```

## Usage Examples

### curl Commands
```bash
# Get copy-pable prompt list
curl -X GET "http://localhost:8000/api/v1/prompts" \
  -H "MCP-API-Key: your-api-key"

# Get JSON format
curl -X GET "http://localhost:8000/api/v1/prompts/json" \
  -H "MCP-API-Key: your-api-key"

# Get organized categories
curl -X GET "http://localhost:8000/api/v1/prompts/categories" \
  -H "MCP-API-Key: your-api-key"

# Get usage guide
curl -X GET "http://localhost:8000/api/v1/prompts/usage-guide" \
  -H "MCP-API-Key: your-api-key"
```

### Python Example
```python
import requests

# Get prompt list
response = requests.get("http://localhost:8000/api/v1/prompts", 
                       headers={"MCP-API-Key": "your-api-key"})

if response.status_code == 200:
    data = response.json()
    if data["status"] == "success":
        print("Copy-paste this into your MCP client:")
        print(data["content"])
```

### JavaScript Example
```javascript
// Get prompt list
fetch("http://localhost:8000/api/v1/prompts", {
  method: "GET",
  headers: {
    "MCP-API-Key": "your-api-key",
    "Content-Type": "application/json"
  }
})
.then(response => response.json())
.then(data => {
  if (data.status === "success") {
    console.log("Prompt list:", data.content);
  }
});
```

## Authentication

All endpoints require authentication using the `MCP-API-Key` header.

## Response Format

All endpoints return JSON with the following structure:
- `status`: "success" or "error"
- `format`: Response format ("markdown" or "json")
- `content`/`data`: The actual response content
- `total_tools`: Number of available tools
- `generated_at`: ISO timestamp of when the response was generated

## Tool Categories

1. **Memory** (1 tool): Context retrieval and memory search
2. **Conversation** (5 tools): Conversation management and preservation
3. **Knowledge** (3 tools): Document and knowledge base management
4. **Utilities** (3 tools): Web search, time info, and system configuration

## Priority Levels

- **High Priority**: Core tools for frequent use
- **Medium Priority**: Supporting tools for enhanced functionality
- **Low Priority**: Cleanup and management tools

## Error Handling

- `400 Bad Request`: Invalid request parameters
- `401 Unauthorized`: Missing or invalid API key
- `500 Internal Server Error`: Server error generating response

## Integration with MCP Clients

These endpoints are designed to work with any MCP client. Simply copy the prompts from the response and use them in your client's tool calling interface.

For Claude Desktop integration, use the prompts as examples of how to structure your tool calls.