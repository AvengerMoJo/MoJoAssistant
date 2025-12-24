# Enhanced add_documents Implementation

## Current MCP Tool Schema (Before Enhancement)
```json
{
  "name": "add_documents",
  "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base",
  "inputSchema": {
    "type": "object",
    "properties": {
      "documents": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "content": {"type": "string"},
            "metadata": {"type": "object"}
          },
          "required": ["content"]
        }
      }
    }
  }
}
```

## Enhanced MCP Tool Schema (After Enhancement)
```json
{
  "name": "add_documents",
  "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base with source context awareness",
  "inputSchema": {
    "type": "object",
    "properties": {
      "documents": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "content": {"type": "string", "description": "Document content"},
            "metadata": {
              "type": "object", 
              "description": "Optional metadata for organization",
              "additionalProperties": true
            },
            "source_type": {
              "type": "string",
              "enum": ["chat", "code", "web", "manual"],
              "default": "chat",
              "description": "Source type for context-aware handling"
            },
            "repo_url": {
              "type": "string", 
              "description": "Git repository URL (for code documents)"
            },
            "file_path": {
              "type": "string",
              "description": "Relative file path in repository (for code documents)"
            },
            "commit_hash": {
              "type": "string",
              "description": "Git commit hash for version tracking"
            },
            "branch": {
              "type": "string", 
              "description": "Git branch name"
            },
            "version": {
              "type": "string",
              "description": "Document version identifier"
            }
          },
          "required": ["content"]
        }
      }
    }
  }
}
```

## Enhanced Python Implementation

### 1. Update Data Models
```python
# In app/mcp/mcp_service.py

class DocumentInput(BaseModel):
    content: str = Field(..., description="Document content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    
    # NEW: Source type and git context
    source_type: Literal["chat", "code", "web", "manual"] = Field(default="chat", description="Source type")
    repo_url: Optional[str] = Field(None, description="Git repository URL")
    file_path: Optional[str] = Field(None, description="File path in repository")
    commit_hash: Optional[str] = Field(None, description="Git commit hash")
    branch: Optional[str] = Field(None, description="Git branch name")
    version: Optional[str] = Field(None, description="Document version")

class DocumentsInput(BaseModel):
    documents: List[DocumentInput] = Field(..., description="List of documents to add")
```

### 2. Enhanced Knowledge Manager
```python
# In app/memory/knowledge_manager.py

class GitAwareKnowledgeManager:
    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]] | None = None, 
                     source_types: List[str] | None = None,
                     git_contexts: List[Dict[str, Any]] | None = None):
        """Enhanced document addition with source awareness"""
        
        if metadatas is None:
            metadatas = [{}] * len(documents)
        if source_types is None:
            source_types = ["chat"] * len(documents)
        if git_contexts is None:
            git_contexts = [{}] * len(documents)
            
        for i, (doc, metadata, source_type, git_context) in enumerate(
            zip(documents, metadatas, source_types, git_contexts)):
            
            # Generate appropriate document ID
            if source_type == "code" and git_context.get("repo_url") and git_context.get("file_path"):
                doc_id = self._generate_repo_based_id(
                    repo_url=git_context["repo_url"],
                    file_path=git_context["file_path"],
                    commit_hash=git_context.get("commit_hash")
                )
            else:
                doc_id = str(uuid.uuid4())
            
            # Enhanced document structure
            document = {
                "id": doc_id,
                "text": doc,
                "chunks": self._chunk_text(doc),
                "metadata": metadata,
                "source_type": source_type,
                "git_context": git_context if git_context else None,
                "created_at": datetime.datetime.now().isoformat(),
                "last_updated": datetime.datetime.now().isoformat()
            }
            
            self.documents.append(document)
            
            # Generate and store embeddings
            embeddings = self.embedding.get_batch_embeddings(document["chunks"])
            for j, embedding in enumerate(embeddings):
                self.chunk_embeddings.append({
                    "doc_id": doc_id,
                    "chunk_index": j,
                    "embedding": embedding,
                    "source_type": source_type  # Index by source type for faster filtering
                })
    
    def _generate_repo_based_id(self, repo_url: str, file_path: str, commit_hash: str | None = None) -> str:
        """Generate deterministic ID based on repository context"""
        # Create a hash from repo URL + file path + (optional) commit
        content = f"{repo_url}:{file_path}"
        if commit_hash:
            content += f":{commit_hash}"
        
        # Use SHA256 for deterministic but secure ID
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def query_by_source_type(self, query_text: str, source_type: str = None, 
                           similarity_top_k: int = 3) -> List[Tuple[str, float]]:
        """Query documents filtered by source type"""
        if not self.chunk_embeddings:
            return []
        
        query_embedding = self.embedding.get_embedding(query_text)
        
        # Filter by source type if specified
        relevant_chunks = []
        for chunk_data in self.chunk_embeddings:
            if source_type is None or chunk_data.get("source_type") == source_type:
                relevant_chunks.append(chunk_data)
        
        # Calculate similarities
        similarities = []
        for chunk_data in relevant_chunks:
            similarity = self._cosine_similarity(query_embedding, chunk_data["embedding"])
            doc = next((d for d in self.documents if d["id"] == chunk_data["doc_id"]), None)
            if doc:
                similarities.append((doc["text"], similarity))
        
        # Return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:similarity_top_k]
```

### 3. Enhanced MCP Service Handler
```python
# In app/mcp/mcp_service.py

@app.post("/api/v1/knowledge/documents", response_model=DocumentsResponse)
async def add_documents(
    documents_data: DocumentsInput,
    background_tasks: BackgroundTasks,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Enhanced document addition with source awareness"""
    start_time_ms = time.time() * 1000
    
    try:
        if not memory_service:
            raise HTTPException(status_code=503, detail="Memory service not available")
        
        results = []
        
        # Extract enhanced data
        documents = []
        metadatas = []
        source_types = []
        git_contexts = []
        
        for doc_input in documents_data.documents:
            documents.append(doc_input.content)
            metadatas.append(doc_input.metadata)
            source_types.append(doc_input.source_type)
            
            # Extract git context
            git_context = {}
            if doc_input.repo_url:
                git_context["repo_url"] = doc_input.repo_url
            if doc_input.file_path:
                git_context["file_path"] = doc_input.file_path
            if doc_input.commit_hash:
                git_context["commit_hash"] = doc_input.commit_hash
            if doc_input.branch:
                git_context["branch"] = doc_input.branch
            if doc_input.version:
                git_context["version"] = doc_input.version
                
            git_contexts.append(git_context)
        
        # Process documents with enhanced manager
        memory_service.knowledge_manager.add_documents(
            documents, metadatas, source_types, git_contexts
        )
        
        # Generate responses
        for i, doc_input in enumerate(documents_data.documents):
            results.append(DocumentResponse(
                document_id=git_contexts[i].get("repo_url", "") + ":" + git_contexts[i].get("file_path", "") 
                           if source_types[i] == "code" else str(uuid.uuid4()),
                status="success",
                message=f"Document added with source type: {doc_input.source_type}"
            ))
        
        processing_time_ms = (time.time() * 1000) - start_time_ms
        
        return DocumentsResponse(
            results=results,
            total_processed=len(documents_data.documents),
            processing_time_ms=processing_time_ms
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document processing failed: {str(e)}")
```

## Usage Examples

### Chat Client (Current Usage - Still Works)
```json
{
  "documents": [
    {
      "content": "Python best practices guide from official documentation",
      "metadata": {"source": "python.org", "category": "documentation"},
      "source_type": "chat"
    }
  ]
}
```

### Programming CLI (New Enhanced Usage)
```json
{
  "documents": [
    {
      "content": "class DatabaseManager:\n    def __init__(self, connection_string):\n        self.connection_string = connection_string",
      "metadata": {"language": "python", "framework": "fastapi"},
      "source_type": "code",
      "repo_url": "https://github.com/private-org/project-api",
      "file_path": "src/database/manager.py",
      "commit_hash": "abc123def456",
      "branch": "feature/database-refactor",
      "version": "2.1.0"
    }
  ]
}
```

## New Query Capabilities

### Source-Aware Search
```python
# Search only code-related documents
context = memory_service.knowledge_manager.query_by_source_type(
    "database connection patterns", 
    source_type="code"
)

# Search only chat/web documents  
context = memory_service.knowledge_manager.query_by_source_type(
    "python best practices",
    source_type="chat"
)
```

### Repository-Specific Search
```python
# Search documents from specific repository
context = memory_service.knowledge_manager.query_by_repo(
    "authentication implementation",
    repo_url="https://github.com/private-org/project-api"
)
```

This enhancement would transform MoJoAssistant from a generic document store into a context-aware system that understands and optimizes for different types of content sources.