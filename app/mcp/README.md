# MoJoAssistant MCP Service

The Memory Communication Protocol (MCP) service provides a REST API interface to MoJoAssistant's memory system, enabling other applications and LLMs to interact with the memory tiers programmatically.

## Quick Start

### 1. Install Dependencies

```bash
# Install MCP service requirements
pip install -r requirements-mcp.txt
```

### 2. Start the Service

```bash
# Basic startup (accessible from all networks)
python3 start_mcp_service.py

# With custom configuration
python3 start_mcp_service.py --host 0.0.0.0 --port 8080 --api-key your-secret-key

# Localhost only (for development)
python3 start_mcp_service.py --host localhost
```

**⚠️ Security Note**: By default, the service binds to `0.0.0.0` (all network interfaces) to enable external LLM access. Use `--api-key` for production deployments.

### 3. Test the Service

```bash
# Run the client example
python3 app/mcp/client_example.py

# Or check health manually
curl http://localhost:8000/health
```

## Network Access & Remote Connections

### Default Network Binding
The MCP service binds to `0.0.0.0:8000` by default, making it accessible from:
- **Local machine**: `http://localhost:8000`
- **Local network**: `http://192.168.1.X:8000`
- **Public internet**: `http://your-public-ip:8000` (if firewall allows)

### Connection Examples

```python
# Local connection
client = MCPClient("http://localhost:8000")

# Remote LAN connection
client = MCPClient("http://192.168.1.100:8000")

# Public domain connection
client = MCPClient("https://mojo-api.example.com")

# Secure connection with API key
client = MCPClient("https://mojo-api.example.com", api_key="your-secret-key")
```

### Network Configuration

**Firewall Settings:**
```bash
# Allow inbound connections on port 8000
sudo ufw allow 8000
# Or for specific networks only
sudo ufw allow from 192.168.1.0/24 to any port 8000
```

**Router Configuration:**
- Port forward external port 8000 → internal IP:8000
- Enable UPnP if using dynamic port forwarding

**Security Recommendations:**
- Use `--api-key` for any network-accessible deployment
- Consider using `--host localhost` for development only
- Use HTTPS reverse proxy (nginx) for production
- Restrict CORS origins: `--cors-origins "https://trusted-domain.com"`

## API Documentation

Once the service is running, visit:
- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

**Tip:** The `openapi.json` file can be used with tools like [OpenAPI Generator](https://openapi-generator.tech/) to automatically create client libraries in various programming languages.

## Core Endpoints

### Memory Operations
- `POST /api/v1/memory/context` - Retrieve relevant context for queries
- `GET /api/v1/memory/stats` - Get memory system statistics

### Knowledge Base
- `POST /api/v1/knowledge/documents` - Add documents to knowledge base
- `GET /api/v1/knowledge/documents` - List documents

### Conversation Management
- `POST /api/v1/conversation/message` - Add messages to conversation
- `POST /api/v1/conversation/end` - End and archive conversation
- `GET /api/v1/conversation/current` - Get current conversation state

### Embedding Operations
- `GET /api/v1/embeddings/models` - List available embedding models
- `POST /api/v1/embeddings/switch` - Switch embedding model

### System
- `GET /health` - Health check
- `GET /info` - Service information

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | localhost | Host to bind to |
| `MCP_PORT` | 8000 | Port to bind to |
| `MCP_API_KEY` | None | API key for authentication |
| `MCP_CORS_ORIGINS` | * | CORS allowed origins |

### Memory Configuration

The service uses the same configuration as the main MoJoAssistant:
- `config/embedding_config.json` - Embedding models
- Environment variables for API keys

## Usage Examples

### Python Client

```python
from app.mcp.client_example import MCPClient

# Initialize client
client = MCPClient("http://localhost:8000")

# Get memory context
context = client.get_memory_context("machine learning", max_items=5)
print(f"Found {context['total_items']} relevant items")

# Add a document
documents = [{
    "content": "Python is a programming language...",
    "metadata": {"title": "Python Basics", "source": "tutorial"}
}]
result = client.add_documents(documents)

# Manage conversation
client.add_message("user", "What is Python?")
client.add_message("assistant", "Python is a programming language...")
client.end_conversation()
```

### cURL Examples

```bash
# Health check
curl http://localhost:8000/health

# Get memory stats
curl http://localhost:8000/api/v1/memory/stats

# Search for context
curl -X POST http://localhost:8000/api/v1/memory/context \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "max_items": 5}'

# Add a document
curl -X POST http://localhost:8000/api/v1/knowledge/documents \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [{
      "content": "Machine learning is...",
      "metadata": {"title": "ML Intro"}
    }]
  }'
```

### With API Key Authentication

```bash
# Set API key
export MCP_API_KEY="your-secret-key"

# Start service with authentication
python3 start_mcp_service.py --api-key your-secret-key

# Make authenticated requests
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/memory/stats
```

## Integration Examples

### LangChain Integration

```python
import requests
from langchain.tools import Tool

def memory_search(query: str) -> str:
    """Search MoJoAssistant memory for relevant context"""
    response = requests.post(
        "http://localhost:8000/api/v1/memory/context",
        json={"query": query, "max_items": 3}
    )
    context = response.json()
    
    results = []
    for item in context["context_items"]:
        results.append(f"- {item['content']} (score: {item['relevance_score']:.2f})")
    
    return "\n".join(results)

# Create LangChain tool
memory_tool = Tool(
    name="memory_search",
    description="Search MoJoAssistant memory for relevant information",
    func=memory_search
)
```

### OpenAI Assistant Integration

```python
import openai
import requests

def get_memory_context(query):
    """Get context from MoJoAssistant memory"""
    response = requests.post(
        "http://localhost:8000/api/v1/memory/context",
        json={"query": query}
    )
    return response.json()

# Use in OpenAI Assistant
def enhanced_chat_completion(user_message):
    # Get relevant context
    context = get_memory_context(user_message)
    context_text = "\n".join([item["content"] for item in context["context_items"]])
    
    # Create enhanced prompt
    enhanced_prompt = f"""
    Context from memory:
    {context_text}
    
    User question: {user_message}
    
    Please answer based on the context and your knowledge.
    """
    
    return openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": enhanced_prompt}]
    )
```

## Development

### Running in Development Mode

```bash
# Start with auto-reload
python3 start_mcp_service.py --reload --log-level DEBUG

# Or directly with uvicorn
uvicorn app.mcp.mcp_service:app --reload --host localhost --port 8000
```

### Testing

```bash
# Run client examples
python3 app/mcp/client_example.py

# Test specific endpoints
python3 -c "
from app.mcp.client_example import MCPClient
client = MCPClient()
print(client.health_check())
"
```

### Adding New Endpoints

1. Add endpoint to `app/mcp/mcp_service.py`
2. Add corresponding method to `client_example.py`
3. Update API documentation
4. Add tests

## Deployment

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements-mcp.txt .
RUN pip install -r requirements-mcp.txt

COPY . .
EXPOSE 8000

CMD ["python3", "start_mcp_service.py", "--host", "0.0.0.0"]
```

### Production Configuration

```bash
# Use production ASGI server
pip install gunicorn

# Start with gunicorn
gunicorn app.mcp.mcp_service:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## Security Considerations

1. **API Key Authentication**: Use `MCP_API_KEY` for production
2. **CORS Configuration**: Restrict `MCP_CORS_ORIGINS` in production
3. **Rate Limiting**: Consider adding rate limiting middleware
4. **HTTPS**: Use reverse proxy (nginx) for HTTPS in production
5. **Input Validation**: All inputs are validated via Pydantic models

## Troubleshooting

### Common Issues

**Service won't start**
- Check if port 8000 is available
- Verify dependencies are installed
- Check logs for specific errors

**Memory service not available**
- Ensure embedding models are properly configured
- Check embedding configuration file exists
- Verify required dependencies (numpy, torch, etc.)

**API requests failing**
- Check service is running: `curl http://localhost:8000/health`
- Verify API key if authentication is enabled
- Check request format matches API documentation

### Logs

Service logs are written to `.memory/logs/mojo_assistant_YYYYMMDD.log`

```bash
# View recent logs
tail -f .memory/logs/mojo_assistant_*.log

# Check for errors
grep ERROR .memory/logs/mojo_assistant_*.log
```

## Contributing

1. Follow the existing code structure
2. Add comprehensive error handling
3. Include logging for all operations
4. Update documentation for new features
5. Add client examples for new endpoints
