# Document Enhancement Proposal: Git-Aware Document System

## Current Limitation
The current `add_documents` endpoint treats all documents the same way, using random UUIDs and basic metadata. This doesn't distinguish between:

1. **Chat-style documentation** (public sources, search results, online docs)
2. **Code-style documentation** (private git repos, versioned files)

## Proposed Enhancement

### Option A: Repository URL as Base Key

**Enhanced Document Structure:**
```python
class EnhancedDocumentInput(BaseModel):
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # NEW: Git repository context
    repo_url: Optional[str] = Field(None, description="Git repository URL")
    file_path: Optional[str] = Field(None, description="Relative file path in repo")
    commit_hash: Optional[str] = Field(None, description="Git commit hash")
    branch: Optional[str] = Field(None, description="Git branch name")
    
    # NEW: Source type classification
    source_type: Literal["chat", "code", "web", "manual"] = "chat"
    
    # NEW: Version tracking
    version: Optional[str] = Field(None, description="Document version")
    is_latest: bool = True
```

**Enhanced Document Storage:**
```python
class GitAwareKnowledgeManager:
    def add_documents(self, documents: List[EnhancedDocumentInput]):
        for doc in documents:
            # Generate repository-based ID if git context exists
            if doc.repo_url and doc.file_path:
                doc_id = self._generate_repo_based_id(
                    repo_url=doc.repo_url,
                    file_path=doc.file_path,
                    commit_hash=doc.commit_hash
                )
            else:
                doc_id = str(uuid.uuid4())
            
            # Store with enhanced metadata
            document = {
                "id": doc_id,
                "content": doc.content,
                "source_type": doc.source_type,
                "git_context": {
                    "repo_url": doc.repo_url,
                    "file_path": doc.file_path,
                    "commit_hash": doc.commit_hash,
                    "branch": doc.branch
                } if doc.repo_url else None,
                "version": doc.version,
                "is_latest": doc.is_latest,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            # Handle version conflicts
            if doc.source_type == "code" and not doc.is_latest:
                self._handle_version_conflict(document)
```

### Option B: Git-Based Document Repository Backend

**Backend Structure:**
```
.mojo_docs/
├── repositories/
│   ├── github.com_user_project/
│   │   ├── main/
│   │   │   ├── src/
│   │   │   │   ├── main.py (hash: abc123...)
│   │   │   │   └── utils.py (hash: def456...)
│   │   │   └── README.md
│   │   └── develop/
│   │       └── src/
│   └── gitlab.com_team_api/
│       └── v2.0/
├── chat_docs/
│   ├── web_sources/
│   ├── search_results/
│   └── manual_uploads/
└── index/
    ├── git_documents.duckdb
    ├── chat_documents.duckdb
    └── search_index/
```

**Implementation:**
```python
class GitBasedDocumentManager:
    def __init__(self, base_path=".mojo_docs"):
        self.base_path = Path(base_path)
        self.git_docs_path = self.base_path / "repositories"
        self.chat_docs_path = self.base_path / "chat_docs"
        
    async def sync_repository(self, repo_url: str, branch: str = "main"):
        """Clone/sync repository to local storage"""
        repo_name = self._sanitize_repo_name(repo_url)
        local_path = self.git_docs_path / repo_name / branch
        
        if local_path.exists():
            # Update existing repo
            await self._git_pull(local_path)
        else:
            # Clone new repo
            await self._git_clone(repo_url, local_path)
            
        return local_path
    
    def add_git_document(self, repo_url: str, file_path: str, content: str):
        """Add document with direct git repo linkage"""
        repo_path = Path(repo_url.replace("https://", "").replace("http://", ""))
        local_repo = self.git_docs_path / repo_path
        
        # Write to synced repository
        doc_file = local_repo / file_path
        doc_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Get git info
        git_info = self._get_git_info(local_repo, file_path)
        
        # Store in index
        document_id = self._generate_git_id(git_info)
        self._index_document(document_id, content, git_info)
        
        return document_id
```

## Usage Examples

### Chat Client Usage (Current)
```python
# Adding public documentation
await add_documents([{
    "content": "Python best practices guide from official docs",
    "metadata": {"source": "python.org", "category": "documentation"},
    "source_type": "chat"  # or "web"
}])
```

### Programming CLI Usage (New)
```python
# Adding code files from git repo
await add_documents([{
    "content": "# Main application logic\nclass App:\n    def run(self):\n        ...",
    "metadata": {"language": "python", "framework": "fastapi"},
    "source_type": "code",
    "repo_url": "https://github.com/user/private-project",
    "file_path": "src/main.py",
    "commit_hash": "abc123def456",
    "branch": "feature/new-endpoint"
}])
```

## Benefits

### For Chat Clients
- **Public source tracking**: Know where documentation came from
- **Search optimization**: Separate indexes for different source types
- **Content freshness**: Track when web sources were last updated

### For Code Clients  
- **Repository context**: Full git history and versioning
- **Seamless sync**: Automatically track code changes
- **Private repo support**: No need for public access
- **Version management**: Handle conflicts and updates intelligently

### For Both
- **Source-aware retrieval**: "Find chat docs about X" vs "Find code docs about X"
- **Conflict resolution**: Different strategies for different source types
- **Performance optimization**: Index differently based on source type

## Implementation Priority

1. **Phase 1**: Add `source_type` and basic git metadata to existing system
2. **Phase 2**: Implement repository URL-based document IDs
3. **Phase 3**: Build git-based backend for full repository sync
4. **Phase 4**: Add source-aware search and retrieval

## Migration Strategy

- **Backward compatible**: Existing documents get `source_type: "chat"`
- **Gradual rollout**: Start with enhanced metadata, then full git integration
- **User choice**: Allow opt-in to git-based system

This enhancement would transform MoJoAssistant from a generic document store into a context-aware knowledge system that understands the difference between chat-generated content and code-generated content.