# MCP Service API Design

## Overview

The Memory Communication Protocol (MCP) service provides a REST API interface to MoJoAssistant's memory system, enabling other applications and LLMs to interact with the memory tiers programmatically.

## Base URL
```
http://localhost:8000/api/v1
```

## Authentication
- API Key based authentication (optional)
- Header: `X-API-Key: your-api-key`

## Core Endpoints

### 1. Memory Context Retrieval

**GET /memory/context**
- **Purpose**: Retrieve relevant context for a query
- **Parameters**:
  - `query` (string, required): The query to search for
  - `max_items` (int, optional, default=10): Maximum number of context items
  - `include_sources` (bool, optional, default=true): Include source information
- **Response**: Array of context items with relevance scores

```json
{
  "query": "What is machine learning?",
  "context_items": [
    {
      "content": "Machine learning is a subset of AI...",
      "source": "knowledge_base",
      "relevance_score": 0.95,
      "timestamp": "2025-07-06T17:00:00Z",
      "metadata": {
        "source_file": "ml_basics.txt",
        "memory_tier": "knowledge"
      }
    }
  ],
  "total_items": 5,
  "processing_time_ms": 45
}
```

### 2. Knowledge Base Management

**POST /knowledge/documents**
- **Purpose**: Add documents to the knowledge base
- **Body**:
```json
{
  "documents": [
    {
      "content": "Document content here...",
      "metadata": {
        "title": "Document Title",
        "source": "file.txt",
        "tags": ["tag1", "tag2"]
      }
    }
  ]
}
```
- **Response**: Document IDs and processing status

**GET /knowledge/documents**
- **Purpose**: List documents in knowledge base
- **Parameters**:
  - `limit` (int, optional, default=50)
  - `offset` (int, optional, default=0)
  - `search` (string, optional): Search query
- **Response**: Paginated list of documents

**DELETE /knowledge/documents/{document_id}**
- **Purpose**: Remove a document from knowledge base

### 3. Memory Statistics

**GET /memory/stats**
- **Purpose**: Get comprehensive memory system statistics
- **Response**:
```json
{
  "working_memory": {
    "messages": 5,
    "tokens": 1250,
    "max_tokens": 4000
  },
  "active_memory": {
    "pages": 3,
    "max_pages": 20
  },
  "archival_memory": {
    "items": 150
  },
  "knowledge_base": {
    "documents": 25,
    "total_chunks": 500
  },
  "embedding": {
    "model_name": "nomic-ai/nomic-embed-text-v2-moe",
    "backend": "huggingface",
    "cache_size": 1000
  },
  "system": {
    "uptime_seconds": 3600,
    "memory_usage_mb": 512
  }
}
```

### 4. Conversation Management

**POST /conversation/message**
- **Purpose**: Add a message to the conversation
- **Body**:
```json
{
  "type": "user|assistant",
  "content": "Message content",
  "context_query": "Optional query for context retrieval"
}
```
- **Response**: Message ID and any retrieved context

**POST /conversation/end**
- **Purpose**: End current conversation and archive to memory
- **Response**: Conversation summary and archive status

**GET /conversation/current**
- **Purpose**: Get current conversation state
- **Response**: Current working memory messages

### 5. Embedding Operations

**POST /embeddings/embed**
- **Purpose**: Generate embeddings for text
- **Body**:
```json
{
  "texts": ["Text to embed", "Another text"],
  "model": "default"
}
```
- **Response**: Array of embedding vectors

**GET /embeddings/models**
- **Purpose**: List available embedding models
- **Response**: Available models and their configurations

**POST /embeddings/switch**
- **Purpose**: Switch embedding model
- **Body**:
```json
{
  "model_name": "fast",
  "backend": "huggingface"
}
```

### 6. Memory State Management

**GET /memory/export**
- **Purpose**: Export memory state
- **Parameters**:
  - `format` (string, optional, default="json"): Export format
  - `include_embeddings` (bool, optional, default=false)
- **Response**: Memory state data

**POST /memory/import**
- **Purpose**: Import memory state
- **Body**: Memory state data (multipart/form-data or JSON)

### 7. Health and Status

**GET /health**
- **Purpose**: Health check endpoint
- **Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-07-06T17:00:00Z",
  "components": {
    "memory_service": "healthy",
    "embedding_service": "healthy",
    "database": "healthy"
  }
}
```

**GET /info**
- **Purpose**: Service information
- **Response**: Service metadata, version, capabilities

## Error Responses

All endpoints return consistent error responses:

```json
{
  "error": {
    "code": "INVALID_QUERY",
    "message": "Query parameter is required",
    "details": {
      "parameter": "query",
      "provided": null
    }
  },
  "timestamp": "2025-07-06T17:00:00Z",
  "request_id": "req_123456"
}
```

## Rate Limiting

- Default: 100 requests per minute per API key
- Configurable via environment variables
- Headers included in response:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

## WebSocket Support (Future)

Real-time endpoints for streaming:
- `/ws/conversation` - Real-time conversation updates
- `/ws/memory` - Memory operation notifications

## SDK Support

Planned client libraries:
- Python SDK
- JavaScript/Node.js SDK
- cURL examples for all endpoints

## Configuration

Service configuration via environment variables:
- `MCP_HOST` (default: localhost)
- `MCP_PORT` (default: 8000)
- `MCP_API_KEY` (optional)
- `MCP_CORS_ORIGINS` (default: *)
- `MCP_RATE_LIMIT` (default: 100/minute)
