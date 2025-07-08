"""
MCP (Memory Communication Protocol) Service
FastAPI-based REST API for MoJoAssistant memory system
"""
import os
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

# Import MoJoAssistant components
import sys
sys.path.append('.')
from app.services.memory_service import MemoryService
from app.config.logging_config import setup_logging, get_logger
from app.config.config_loader import load_embedding_config


# Pydantic Models for API
class ContextQuery(BaseModel):
    query: str = Field(..., description="Query to search for relevant context")
    max_items: int = Field(10, ge=1, le=100, description="Maximum number of context items")
    include_sources: bool = Field(True, description="Include source information")

class ContextItem(BaseModel):
    content: str
    source: str
    relevance_score: float
    timestamp: str
    metadata: Dict[str, Any] = {}

class ContextResponse(BaseModel):
    query: str
    context_items: List[ContextItem]
    total_items: int
    processing_time_ms: float

class DocumentInput(BaseModel):
    content: str = Field(..., description="Document content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")

class DocumentsInput(BaseModel):
    documents: List[DocumentInput] = Field(..., description="List of documents to add")

class DocumentResponse(BaseModel):
    document_id: str
    status: str
    message: str

class DocumentsResponse(BaseModel):
    results: List[DocumentResponse]
    total_processed: int
    processing_time_ms: float

class ConversationMessage(BaseModel):
    type: str = Field(..., pattern="^(user|assistant)$", description="Message type")
    content: str = Field(..., description="Message content")
    context_query: Optional[str] = Field(None, description="Optional query for context retrieval")

class MessageResponse(BaseModel):
    message_id: str
    status: str
    context_items: Optional[List[ContextItem]] = None

class EmbeddingRequest(BaseModel):
    texts: List[str] = Field(..., description="Texts to embed")
    model: str = Field("default", description="Embedding model to use")

class EmbeddingResponse(BaseModel):
    embeddings: List[List[float]]
    model_used: str
    processing_time_ms: float

class ModelSwitchRequest(BaseModel):
    model_name: str = Field(..., description="Model name to switch to")
    backend: Optional[str] = Field(None, description="Backend type")

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    components: Dict[str, str]

class ErrorResponse(BaseModel):
    error: Dict[str, Any]
    timestamp: str
    request_id: str


# Global variables
memory_service: Optional[MemoryService] = None
logger = None
start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global memory_service, logger
    
    # Startup
    setup_logging()
    logger = get_logger(__name__)
    logger.info("Starting MCP Service...")
    
    try:
        # Load configuration
        embedding_config = load_embedding_config()
        
        # Initialize memory service
        embed_config = embedding_config["embedding_models"]["default"]
        memory_service = MemoryService(
            data_dir=embedding_config.get("memory_settings", {}).get("data_directory", ".memory"),
            embedding_model=embed_config.get("model_name", "nomic-ai/nomic-embed-text-v2-moe"),
            embedding_backend=embed_config.get("backend", "huggingface"),
            embedding_device=embed_config.get("device"),
            config=embedding_config.get("memory_settings", {})
        )
        
        logger.info("MCP Service initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize MCP Service: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down MCP Service...")


# Create FastAPI app
app = FastAPI(
    title="MoJoAssistant MCP Service",
    description="Memory Communication Protocol API for MoJoAssistant",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("MCP_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency for API key authentication (optional)
async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key if authentication is enabled"""
    required_key = os.getenv("MCP_API_KEY")
    if required_key and x_api_key != required_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# Utility functions
def generate_request_id() -> str:
    """Generate unique request ID"""
    return f"req_{uuid.uuid4().hex[:8]}"

def create_error_response(code: str, message: str, details: Dict[str, Any] = None) -> JSONResponse:
    """Create standardized error response"""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {}
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "request_id": generate_request_id()
        }
    )


# API Endpoints

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
        components={
            "memory_service": "healthy" if memory_service else "unhealthy",
            "embedding_service": "healthy",
            "api": "healthy"
        }
    )

@app.get("/info")
async def service_info():
    """Service information endpoint"""
    return {
        "name": "MoJoAssistant MCP Service",
        "version": "1.0.0",
        "description": "Memory Communication Protocol API",
        "uptime_seconds": int(time.time() - start_time),
        "capabilities": [
            "memory_context_retrieval",
            "knowledge_base_management", 
            "conversation_management",
            "embedding_operations",
            "memory_statistics"
        ],
        "endpoints": {
            "memory": "/api/v1/memory/*",
            "knowledge": "/api/v1/knowledge/*",
            "conversation": "/api/v1/conversation/*",
            "embeddings": "/api/v1/embeddings/*"
        }
    }

@app.post("/api/v1/memory/context", response_model=ContextResponse)
async def get_memory_context(
    query_data: ContextQuery,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Retrieve relevant context for a query"""
    start_time_ms = time.time() * 1000
    
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        # Get context from memory service
        context_items = memory_service.get_context_for_query(
            query_data.query, 
            max_items=query_data.max_items
        )
        
        # Convert to response format
        response_items = []
        for item in context_items:
            response_items.append(ContextItem(
                content=item.get("content", ""),
                source=item.get("source", "unknown"),
                relevance_score=item.get("relevance_score", 0.0),
                timestamp=item.get("timestamp", datetime.utcnow().isoformat() + "Z"),
                metadata=item.get("metadata", {})
            ))
        
        processing_time = (time.time() * 1000) - start_time_ms
        
        logger.info(f"Context retrieval: query='{query_data.query[:50]}...', items={len(response_items)}, time={processing_time:.2f}ms")
        
        return ContextResponse(
            query=query_data.query,
            context_items=response_items,
            total_items=len(response_items),
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        logger.error(f"Error retrieving context: {e}")
        raise HTTPException(status_code=500, detail=f"Context retrieval failed: {str(e)}")

@app.get("/api/v1/memory/stats")
async def get_memory_stats(api_key: Optional[str] = Depends(verify_api_key)):
    """Get comprehensive memory system statistics"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        stats = memory_service.get_memory_stats()
        
        # Add system stats
        stats["system"] = {
            "uptime_seconds": int(time.time() - start_time),
            "memory_usage_mb": 0,  # Could add psutil for actual memory usage
            "api_version": "1.0.0"
        }
        
        logger.debug("Memory statistics retrieved")
        return stats
        
    except Exception as e:
        logger.error(f"Error retrieving memory stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats retrieval failed: {str(e)}")

@app.post("/api/v1/knowledge/documents", response_model=DocumentsResponse)
async def add_documents(
    documents_data: DocumentsInput,
    background_tasks: BackgroundTasks,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Add documents to the knowledge base"""
    start_time_ms = time.time() * 1000
    
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        results = []
        
        for i, doc in enumerate(documents_data.documents):
            try:
                # Add document to knowledge base
                memory_service.add_to_knowledge_base(doc.content, doc.metadata)
                
                doc_id = f"doc_{uuid.uuid4().hex[:8]}"
                results.append(DocumentResponse(
                    document_id=doc_id,
                    status="success",
                    message="Document added successfully"
                ))
                
            except Exception as e:
                logger.error(f"Error adding document {i}: {e}")
                results.append(DocumentResponse(
                    document_id=f"doc_error_{i}",
                    status="error", 
                    message=f"Failed to add document: {str(e)}"
                ))
        
        processing_time = (time.time() * 1000) - start_time_ms
        
        logger.info(f"Documents processed: total={len(documents_data.documents)}, time={processing_time:.2f}ms")
        
        return DocumentsResponse(
            results=results,
            total_processed=len(documents_data.documents),
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        logger.error(f"Error processing documents: {e}")
        raise HTTPException(status_code=500, detail=f"Document processing failed: {str(e)}")

@app.get("/api/v1/knowledge/documents")
async def list_documents(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    api_key: Optional[str] = Depends(verify_api_key)
):
    """List documents in knowledge base"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        # Get knowledge base stats (simplified for now)
        stats = memory_service.get_memory_stats()
        kb_stats = stats.get("knowledge_base", {})
        
        # For now, return summary info
        # In a full implementation, you'd query the actual documents
        return {
            "documents": [],  # Would contain actual document list
            "total": kb_stats.get("items", 0),
            "limit": limit,
            "offset": offset,
            "search_query": search
        }
        
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=f"Document listing failed: {str(e)}")

@app.post("/api/v1/conversation/message", response_model=MessageResponse)
async def add_conversation_message(
    message_data: ConversationMessage,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Add a message to the conversation"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        message_id = f"msg_{uuid.uuid4().hex[:8]}"
        context_items = None
        
        # Add message to memory
        if message_data.type == "user":
            memory_service.add_user_message(message_data.content)
            
            # Get context if requested
            if message_data.context_query:
                context_raw = memory_service.get_context_for_query(message_data.context_query)
                context_items = [
                    ContextItem(
                        content=item.get("content", ""),
                        source=item.get("source", "unknown"),
                        relevance_score=item.get("relevance_score", 0.0),
                        timestamp=item.get("timestamp", datetime.utcnow().isoformat() + "Z"),
                        metadata=item.get("metadata", {})
                    ) for item in context_raw
                ]
                
        elif message_data.type == "assistant":
            memory_service.add_assistant_message(message_data.content)
        
        logger.info(f"Message added: type={message_data.type}, id={message_id}")
        
        return MessageResponse(
            message_id=message_id,
            status="success",
            context_items=context_items
        )
        
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        raise HTTPException(status_code=500, detail=f"Message processing failed: {str(e)}")

@app.post("/api/v1/conversation/end")
async def end_conversation(api_key: Optional[str] = Depends(verify_api_key)):
    """End current conversation and archive to memory"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        # End conversation
        memory_service.end_conversation()
        
        logger.info("Conversation ended and archived")
        
        return {
            "status": "success",
            "message": "Conversation ended and archived to memory",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Error ending conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Conversation end failed: {str(e)}")

@app.get("/api/v1/conversation/current")
async def get_current_conversation(api_key: Optional[str] = Depends(verify_api_key)):
    """Get current conversation state"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        # Get working memory messages
        messages = memory_service.working_memory.get_messages()
        
        return {
            "messages": [
                {
                    "type": msg.type,
                    "content": msg.content,
                    "timestamp": msg.timestamp
                } for msg in messages
            ],
            "total_messages": len(messages),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Error getting current conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Conversation retrieval failed: {str(e)}")

@app.get("/api/v1/embeddings/models")
async def list_embedding_models(api_key: Optional[str] = Depends(verify_api_key)):
    """List available embedding models"""
    try:
        # Load embedding config
        embedding_config = load_embedding_config()
        
        models = []
        for name, config in embedding_config.get("embedding_models", {}).items():
            models.append({
                "name": name,
                "model_name": config.get("model_name", name),
                "backend": config.get("backend", "unknown"),
                "embedding_dim": config.get("embedding_dim", 0),
                "device": config.get("device", "auto")
            })
        
        return {
            "models": models,
            "current_model": memory_service.get_embedding_info() if memory_service else None
        }
        
    except Exception as e:
        logger.error(f"Error listing embedding models: {e}")
        raise HTTPException(status_code=500, detail=f"Model listing failed: {str(e)}")

@app.post("/api/v1/embeddings/switch")
async def switch_embedding_model(
    switch_data: ModelSwitchRequest,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Switch embedding model"""
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        success = memory_service.set_embedding_model(
            model_name=switch_data.model_name,
            backend=switch_data.backend
        )
        
        if success:
            logger.info(f"Embedding model switched to: {switch_data.model_name}")
            return {
                "status": "success",
                "message": f"Switched to embedding model: {switch_data.model_name}",
                "current_model": memory_service.get_embedding_info()
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to switch embedding model")
            
    except Exception as e:
        logger.error(f"Error switching embedding model: {e}")
        raise HTTPException(status_code=500, detail=f"Model switch failed: {str(e)}")


if __name__ == "__main__":
    # Run the service
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    
    uvicorn.run(
        "mcp_service:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
