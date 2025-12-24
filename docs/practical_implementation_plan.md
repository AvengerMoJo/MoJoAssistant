# Practical Implementation: Enhanced MCP add_documents Tool

## Quick Test: Current vs Enhanced Usage

### Current Usage (Still Works)
```python
# This will continue to work exactly as before
await mcp_MoJoAssistant_add_documents([{
    "content": "Python best practices guide",
    "metadata": {"source": "python.org"}
}])
```

### Enhanced Usage (New Feature)
```python  
# New git-aware usage for programming CLI
await mcp_MoJoAssistant_add_documents([{
    "content": "class DatabaseManager:\n    def connect(self): pass",
    "metadata": {"language": "python"},
    "source_type": "code",  # NEW FIELD
    "repo_url": "https://github.com/private-org/project",  # NEW FIELD
    "file_path": "src/db/manager.py",  # NEW FIELD
    "commit_hash": "abc123",  # NEW FIELD
    "branch": "main"  # NEW FIELD
}])
```

## Integration Strategy

### Phase 1: Backward Compatible Enhancement (No Breaking Changes)

1. **Update the MCP tool schema** to include new optional fields
2. **Modify the document storage** to handle both old and new formats
3. **Add source-type indexing** for faster filtering
4. **Maintain existing API** - all current calls work unchanged

### Phase 2: Enhanced Querying

1. **Add source-type filtering** to search queries
2. **Implement repository-specific queries**
3. **Add version conflict detection**
4. **Create source-aware recommendations**

### Phase 3: Git Integration (Optional)

1. **Repository sync capability** (Option B from proposal)
2. **Automatic commit tracking**
3. **Branch-aware documentation**
4. **Conflict resolution workflows**

## Immediate Implementation Steps

### Step 1: Update Document Schema (Non-Breaking)

```python
# Update app/mcp/mcp_service.py
class DocumentInput(BaseModel):
    content: str = Field(..., description="Document content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    
    # NEW FIELDS (all optional - maintain backward compatibility)
    source_type: Literal["chat", "code", "web", "manual"] = Field(default="chat", description="Source type")
    repo_url: Optional[str] = Field(None, description="Git repository URL")
    file_path: Optional[str] = Field(None, description="File path in repository")
    commit_hash: Optional[str] = Field(None, description="Git commit hash")
    branch: Optional[str] = Field(None, description="Git branch name")
    version: Optional[str] = Field(None, description="Document version")
```

### Step 2: Enhanced Storage (Non-Breaking)

```python
# Update app/memory/knowledge_manager.py
def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]] | None = None,
                 source_types: List[str] | None = None,
                 git_contexts: List[Dict[str, Any]] | None = None):
    
    # Set defaults for backward compatibility
    if metadatas is None:
        metadatas = [{}] * len(documents)
    if source_types is None:
        source_types = ["chat"] * len(documents)  # Default to "chat" for existing documents
    if git_contexts is None:
        git_contexts = [{}] * len(documents)
    
    for i, (doc, metadata, source_type, git_context) in enumerate(zip(documents, metadatas, source_types, git_contexts)):
        
        # Generate enhanced document ID
        if source_type == "code" and git_context.get("repo_url") and git_context.get("file_path"):
            doc_id = self._generate_repo_based_id(
                repo_url=git_context["repo_url"],
                file_path=git_context["file_path"],
                commit_hash=git_context.get("commit_hash")
            )
        else:
            doc_id = str(uuid.uuid4())
        
        # Enhanced document with source awareness
        document = {
            "id": doc_id,
            "text": doc,
            "chunks": self._chunk_text(doc),
            "metadata": metadata,
            "source_type": source_type,  # NEW
            "git_context": git_context if git_context else None,  # NEW
            "created_at": datetime.datetime.now().isoformat(),
            "last_updated": datetime.datetime.now().isoformat()
        }
        
        self.documents.append(document)
        
        # Store embeddings with source type for filtering
        chunk_embeddings = self.embedding.get_batch_embeddings(document["chunks"])
        for j, embedding in enumerate(chunk_embeddings):
            self.chunk_embeddings.append({
                "doc_id": doc_id,
                "chunk_index": j,
                "embedding": embedding,
                "source_type": source_type  # NEW: Index by source type
            })
```

### Step 3: Enhanced Query Methods

```python
def query_by_source_type(self, query_text: str, source_type: str = None, 
                        similarity_top_k: int = 3) -> List[Tuple[str, float]]:
    """Query documents filtered by source type"""
    if not self.chunk_embeddings:
        return []
    
    query_embedding = self.embedding.get_embedding(query_text)
    
    # Filter embeddings by source type if specified
    filtered_embeddings = []
    for chunk_data in self.chunk_embeddings:
        if source_type is None or chunk_data.get("source_type") == source_type:
            filtered_embeddings.append(chunk_data)
    
    # Calculate similarities and return results
    similarities = []
    for chunk_data in filtered_embeddings:
        similarity = self._cosine_similarity(query_embedding, chunk_data["embedding"])
        doc = next((d for d in self.documents if d["id"] == chunk_data["doc_id"]), None)
        if doc:
            similarities.append((doc["text"], similarity))
    
    return sorted(similarities, key=lambda x: x[1], reverse=True)[:similarity_top_k]
```

## Testing the Enhancement

### Test 1: Backward Compatibility
```python
# This should work exactly as before
result = await add_documents([{
    "content": "Old document",
    "metadata": {"source": "existing"}
}])
# Should work without any changes
```

### Test 2: Enhanced Usage
```python
# This should work with new fields
result = await add_documents([{
    "content": "class NewFeature:\n    pass",
    "source_type": "code",
    "repo_url": "https://github.com/private/repo",
    "file_path": "src/feature.py",
    "commit_hash": "abc123"
}])
```

### Test 3: Source-Aware Querying
```python
# Query only code documents
code_context = get_memory_context("authentication patterns", source_type="code")

# Query only chat documents  
chat_context = get_memory_context("python tutorials", source_type="chat")
```

## Benefits of This Approach

1. **Zero Breaking Changes**: All existing code continues to work
2. **Gradual Adoption**: Can start using enhanced features immediately
3. **Source Optimization**: Different handling for different content types
4. **Future-Proof**: Ready for full git integration when needed
5. **Performance**: Source-type indexing for faster queries

## Next Steps

1. **Implement Phase 1** (enhanced schema + storage)
2. **Test backward compatibility** thoroughly
3. **Add source-aware querying** capabilities
4. **Consider Phase 2** (git sync) if needed
5. **Document new usage patterns** for different client types

This enhancement would solve your core requirement: distinguishing between chat-generated documentation and code-generated documentation, while maintaining full backward compatibility with existing usage.