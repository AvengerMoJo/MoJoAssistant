# MCP Integration Guide: How External LLMs Use MoJoAssistant

## Overview

The MCP (Memory Communication Protocol) service provides a **standalone REST API** that enables external LLMs and applications to access MoJoAssistant's memory system. This guide explains how the service gets triggered and used in real-world scenarios.

## Architecture Understanding

```
┌─────────────────────┐    ┌─────────────────────┐
│   Interactive CLI   │    │    MCP Service      │
│                     │    │   (REST API)        │
│  Human User ←→ LLM  │    │  External LLM ←→    │
│         ↓           │    │         ↓           │
│   Memory Service    │    │   Memory Service    │
│   (Direct Access)   │    │   (HTTP Access)     │
└─────────────────────┘    └─────────────────────┘
           ↓                           ↓
    ┌─────────────────────────────────────────────┐
    │        Shared Memory System                 │
    │  • Working Memory  • Active Memory          │
    │  • Archival Memory • Knowledge Base         │
    └─────────────────────────────────────────────┘
```

**Key Points:**
- **Two Access Methods**: CLI (direct) and MCP (HTTP API)
- **Same Backend**: Both use the identical MemoryService
- **Shared Memory**: All data is shared between access methods
- **Independent Operation**: MCP service runs separately from CLI

## How External LLMs Discover and Use MCP

### 1. Service Discovery

External LLMs discover the MCP service through:

**Network Scanning:**
```python
# LLM scans network for MCP services
import ipaddress
import requests

def discover_mcp_services(network="192.168.1.0/24", port=8000):
    """Scan network for MCP services"""
    services = []
    for ip in ipaddress.IPv4Network(network):
        try:
            response = requests.get(f"http://{ip}:{port}/health", timeout=2)
            if response.status_code == 200:
                info = requests.get(f"http://{ip}:{port}/info", timeout=2)
                if "MoJoAssistant" in info.json().get("name", ""):
                    services.append(f"http://{ip}:{port}")
        except:
            continue
    return services

# Discover services on local network
mcp_services = discover_mcp_services()
```

**Port Scanning:**
```python
# LLM scans common ports for services
def scan_for_mcp(host="localhost"):
    ports_to_check = [8000, 8080, 3000, 5000]
    for port in ports_to_check:
        try:
            response = requests.get(f"http://{host}:{port}/health", timeout=2)
            if response.status_code == 200:
                info = requests.get(f"http://{host}:{port}/info", timeout=2)
                if "MoJoAssistant" in info.json().get("name", ""):
                    return f"http://{host}:{port}"
        except:
            continue
    return None
```

**DNS/Service Discovery:**
```python
# LLM uses DNS or service registry
mcp_services = [
    "http://mojo-1.local:8000",
    "http://mojo-2.local:8000", 
    "https://mojo-api.company.com"
]
```

**Manual Configuration:**
```python
# LLM is configured with MCP service URLs
mcp_service_url = "http://192.168.1.100:8000"  # Remote server
client = MCPClient(mcp_service_url)
```

### 2. Capability Discovery

Once discovered, LLMs query service capabilities:

```python
# Get service information
info = requests.get("http://localhost:8000/info").json()

capabilities = info["capabilities"]
# ['memory_context_retrieval', 'knowledge_base_management', 
#  'conversation_management', 'embedding_operations']

endpoints = info["endpoints"]
# {'memory': '/api/v1/memory/*', 'knowledge': '/api/v1/knowledge/*', ...}
```

### 3. Integration Patterns

#### Pattern 1: Context Enhancement
```python
def enhanced_llm_response(user_query):
    # 1. Query MoJoAssistant for relevant context
    context_response = requests.post(
        "http://localhost:8000/api/v1/memory/context",
        json={"query": user_query, "max_items": 5}
    )
    context = context_response.json()
    
    # 2. Enhance prompt with retrieved context
    enhanced_prompt = f"""
    Relevant context from memory:
    {format_context(context['context_items'])}
    
    User question: {user_query}
    
    Please answer using the context above and your knowledge.
    """
    
    # 3. Generate response with enhanced context
    return generate_response(enhanced_prompt)
```

#### Pattern 2: Knowledge Contribution
```python
def contribute_knowledge_to_mojo(new_information):
    # External LLM adds knowledge to MoJoAssistant
    documents = [{
        "content": new_information,
        "metadata": {
            "source": "external_llm_gpt4",
            "confidence": 0.9,
            "timestamp": datetime.now().isoformat()
        }
    }]
    
    response = requests.post(
        "http://localhost:8000/api/v1/knowledge/documents",
        json={"documents": documents}
    )
    
    return response.json()
```

#### Pattern 3: Conversation Management
```python
def manage_conversation_with_mojo(user_message):
    # 1. Add user message to MoJoAssistant's memory
    requests.post(
        "http://localhost:8000/api/v1/conversation/message",
        json={
            "type": "user",
            "content": user_message,
            "context_query": user_message  # Get relevant context
        }
    )
    
    # 2. Generate response
    response = generate_llm_response(user_message)
    
    # 3. Add assistant response to memory
    requests.post(
        "http://localhost:8000/api/v1/conversation/message",
        json={
            "type": "assistant", 
            "content": response
        }
    )
    
    return response
```

## Real-World Usage Scenarios

### Scenario 1: LangChain Integration

```python
from langchain.tools import Tool
import requests

def mojo_memory_search(query: str) -> str:
    """Tool for searching MoJoAssistant memory"""
    response = requests.post(
        "http://localhost:8000/api/v1/memory/context",
        json={"query": query, "max_items": 3}
    )
    
    context = response.json()
    results = []
    for item in context["context_items"]:
        results.append(f"- {item['content']} (relevance: {item['relevance_score']:.2f})")
    
    return "\n".join(results)

# Create LangChain tool
memory_tool = Tool(
    name="mojo_memory_search",
    description="Search MoJoAssistant's memory for relevant information",
    func=mojo_memory_search
)

# Use in agent
from langchain.agents import initialize_agent
agent = initialize_agent([memory_tool], llm, agent="zero-shot-react-description")
```

### Scenario 2: OpenAI Assistant Integration

```python
import openai
import requests

class MoJoEnhancedAssistant:
    def __init__(self):
        self.mcp_url = "http://localhost:8000"
        
    def chat_completion(self, user_message):
        # Get context from MoJoAssistant
        context_response = requests.post(
            f"{self.mcp_url}/api/v1/memory/context",
            json={"query": user_message}
        )
        context = context_response.json()
        
        # Build enhanced prompt
        context_text = "\n".join([
            item["content"] for item in context["context_items"]
        ])
        
        enhanced_prompt = f"""
        Context from MoJoAssistant memory:
        {context_text}
        
        User: {user_message}
        
        Assistant: Based on the context above and my knowledge, I'll help you with that.
        """
        
        # Generate response
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": enhanced_prompt}]
        )
        
        # Add conversation to MoJoAssistant memory
        requests.post(f"{self.mcp_url}/api/v1/conversation/message", 
                     json={"type": "user", "content": user_message})
        requests.post(f"{self.mcp_url}/api/v1/conversation/message",
                     json={"type": "assistant", "content": response.choices[0].message.content})
        
        return response.choices[0].message.content
```

### Scenario 3: Multi-LLM Collaboration

```python
# System 1: Claude adds research knowledge
def claude_knowledge_contribution():
    research_data = extract_research_papers()
    for paper in research_data:
        requests.post(
            "http://localhost:8000/api/v1/knowledge/documents",
            json={
                "documents": [{
                    "content": paper["abstract"],
                    "metadata": {
                        "title": paper["title"],
                        "source": "claude_research",
                        "authors": paper["authors"],
                        "year": paper["year"]
                    }
                }]
            }
        )

# System 2: GPT-4 retrieves context for responses
def gpt4_enhanced_response(query):
    context = requests.post(
        "http://localhost:8000/api/v1/memory/context",
        json={"query": query}
    ).json()
    
    return generate_response_with_context(query, context)

# System 3: Gemini manages long-term conversations
def gemini_conversation_manager(user_id, message):
    # Get conversation history
    history = requests.get(
        "http://localhost:8000/api/v1/conversation/current"
    ).json()
    
    # Continue conversation with context
    response = generate_contextual_response(message, history)
    
    # Update conversation
    requests.post(
        "http://localhost:8000/api/v1/conversation/message",
        json={"type": "assistant", "content": response}
    )
    
    return response
```

## Service Triggering Methods

### 1. Automatic Service Discovery
- LLMs scan common ports (8000, 8080, 3000)
- Check `/health` endpoint for service availability
- Query `/info` endpoint for capabilities
- Register service for future use

### 2. Configuration-Based
- LLMs are pre-configured with MCP service URLs
- Environment variables: `MOJO_MCP_URL=http://localhost:8000`
- Configuration files specify MCP endpoints

### 3. Service Registry
- MCP service registers with service discovery systems
- LLMs query service registry for available services
- Dynamic service discovery and load balancing

### 4. Event-Driven
- MCP service publishes availability events
- LLMs subscribe to service availability notifications
- Automatic connection when service becomes available

## Deployment Patterns

### Development (Local Network)
```bash
# Start MCP service accessible on local network
python3 start_mcp_service.py --host 0.0.0.0 --port 8000

# External LLMs on same network connect to:
# http://192.168.1.X:8000 (where X is your machine's IP)
```

### Production (Public Access)
```bash
# Start MCP service with security
python3 start_mcp_service.py --host 0.0.0.0 --port 8000 --api-key secret-key

# External LLMs connect to:
# https://your-domain.com/api/v1/* (via reverse proxy)
```

### Cloud Deployment
```bash
# AWS/GCP/Azure deployment
python3 start_mcp_service.py --host 0.0.0.0 --port 8000 --api-key $API_KEY

# External LLMs connect to:
# https://mojo-service-123.cloud-provider.com/api/v1/*
```

### Docker (Network Accessible)
```yaml
# docker-compose.yml
services:
  mojo-mcp:
    build: .
    ports:
      - "8000:8000"  # Expose to host network
    environment:
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8000
      - MCP_API_KEY=secret-key
      - MCP_CORS_ORIGINS=https://llm-service.com
```

### Kubernetes (Load Balanced)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: mojo-mcp-service
spec:
  type: LoadBalancer  # External access
  ports:
  - port: 80
    targetPort: 8000
  selector:
    app: mojo-mcp
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mojo-mcp-deployment
spec:
  replicas: 3  # Multiple instances
  selector:
    matchLabels:
      app: mojo-mcp
  template:
    spec:
      containers:
      - name: mcp-service
        image: mojo-assistant:latest
        ports:
        - containerPort: 8000
        env:
        - name: MCP_HOST
          value: "0.0.0.0"
        - name: MCP_API_KEY
          valueFrom:
            secretKeyRef:
              name: mcp-secret
              key: api-key
```

### Reverse Proxy (Production)
```nginx
# nginx configuration for HTTPS and load balancing
upstream mojo_mcp {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;  # Multiple instances
    server 127.0.0.1:8002;
}

server {
    listen 443 ssl;
    server_name mojo-api.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location /api/v1/ {
        proxy_pass http://mojo_mcp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /health {
        proxy_pass http://mojo_mcp;
    }
    
    location /docs {
        proxy_pass http://mojo_mcp;
    }
}
```

## Security Considerations

### API Key Authentication
```python
# MCP service with API key
export MCP_API_KEY="your-secret-key"
python3 start_mcp_service.py --api-key your-secret-key

# External LLM with API key
headers = {"X-API-Key": "your-secret-key"}
response = requests.get("http://localhost:8000/api/v1/memory/stats", headers=headers)
```

### CORS Configuration
```python
# Restrict CORS origins
export MCP_CORS_ORIGINS="https://trusted-llm.com,https://another-service.com"
```

### Rate Limiting
```python
# Future enhancement: Rate limiting per API key
# 100 requests per minute per key
```

## Monitoring and Observability

### Health Monitoring
```python
# External systems monitor MCP health
health = requests.get("http://localhost:8000/health").json()
if health["status"] != "healthy":
    alert("MoJoAssistant MCP service is unhealthy")
```

### Usage Analytics
```python
# Get service statistics
stats = requests.get("http://localhost:8000/api/v1/memory/stats").json()
print(f"Memory usage: {stats['working_memory']['messages']} messages")
print(f"Knowledge base: {stats['knowledge_base']['items']} items")
print(f"Uptime: {stats['system']['uptime_seconds']} seconds")
```

### Logging Integration
- All MCP requests are logged with structured data
- External LLM interactions are tracked
- Performance metrics are recorded
- Error conditions are monitored

## Conclusion

The MCP service enables seamless integration between MoJoAssistant and external AI systems through:

1. **Automatic Discovery**: LLMs can find and connect to the service
2. **Standard REST API**: Universal HTTP-based interface
3. **Rich Capabilities**: Full access to memory, knowledge, and conversation management
4. **Production Ready**: Security, monitoring, and deployment features
5. **Multi-LLM Support**: Multiple AI systems can collaborate through shared memory

This architecture transforms MoJoAssistant from a standalone system into a **collaborative AI memory platform** that enhances the capabilities of any connected LLM or AI system.
