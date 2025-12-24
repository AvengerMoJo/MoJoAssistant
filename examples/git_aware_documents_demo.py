#!/usr/bin/env python3
"""
Minimal Git-Aware Document Enhancement
Demonstrates the core concept without breaking existing functionality
"""

import uuid
import hashlib
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime

class GitAwareDocumentManager:
    """Enhanced document manager with source type awareness"""
    
    def __init__(self):
        self.documents = []
        self.source_type_index = {
            "chat": [],
            "code": [], 
            "web": [],
            "manual": []
        }
    
    def add_document_enhanced(self, content: str, metadata: Dict[str, Any] = None,
                            source_type: Literal["chat", "code", "web", "manual"] = "chat",
                            repo_url: Optional[str] = None,
                            file_path: Optional[str] = None,
                            commit_hash: Optional[str] = None,
                            branch: Optional[str] = None) -> str:
        """Add document with enhanced source awareness"""
        
        # Generate appropriate ID
        if source_type == "code" and repo_url and file_path:
            doc_id = self._generate_repo_based_id(repo_url, file_path, commit_hash)
        else:
            doc_id = str(uuid.uuid4())
        
        # Create enhanced document
        document = {
            "id": doc_id,
            "content": content,
            "metadata": metadata or {},
            "source_type": source_type,
            "git_context": {
                "repo_url": repo_url,
                "file_path": file_path, 
                "commit_hash": commit_hash,
                "branch": branch
            } if repo_url else None,
            "created_at": datetime.now().isoformat()
        }
        
        # Store document
        self.documents.append(document)
        
        # Index by source type
        self.source_type_index[source_type].append(doc_id)
        
        return doc_id
    
    def _generate_repo_based_id(self, repo_url: str, file_path: str, commit_hash: Optional[str] = None) -> str:
        """Generate deterministic ID from git context"""
        content = f"{repo_url}:{file_path}"
        if commit_hash:
            content += f":{commit_hash}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def query_by_source_type(self, query: str, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query documents filtered by source type"""
        if source_type and source_type in self.source_type_index:
            relevant_ids = self.source_type_index[source_type]
            return [doc for doc in self.documents if doc["id"] in relevant_ids]
        return self.documents
    
    def get_repository_documents(self, repo_url: str) -> List[Dict[str, Any]]:
        """Get all documents from specific repository"""
        return [doc for doc in self.documents 
                if doc.get("git_context", {}).get("repo_url") == repo_url]
    
    def print_document_summary(self):
        """Print summary of all documents by source type"""
        print("\n=== Document Summary ===")
        for source_type, doc_ids in self.source_type_index.items():
            docs = [doc for doc in self.documents if doc["id"] in doc_ids]
            print(f"\n{source_type.upper()} Documents ({len(docs)}):")
            
            for doc in docs:
                if source_type == "code" and doc.get("git_context"):
                    ctx = doc["git_context"]
                    print(f"  - {ctx.get('file_path', 'Unknown')} ({ctx.get('repo_url', 'Unknown repo')})")
                    if ctx.get('commit_hash'):
                        print(f"    Commit: {ctx['commit_hash'][:8]}...")
                else:
                    print(f"  - {doc['content'][:50]}...")
                    if doc.get('metadata', {}).get('source'):
                        print(f"    Source: {doc['metadata']['source']}")

# Demonstration
if __name__ == "__main__":
    manager = GitAwareDocumentManager()
    
    # Add chat-style documents (current usage)
    manager.add_document_enhanced(
        content="Python best practices from official documentation",
        metadata={"source": "python.org", "category": "documentation"},
        source_type="chat"
    )
    
    manager.add_document_enhanced(
        content="FastAPI tutorial from web search results", 
        metadata={"source": "google_search", "rank": 1},
        source_type="web"
    )
    
    # Add code-style documents (new usage)
    manager.add_document_enhanced(
        content="class DatabaseManager:\n    def __init__(self, connection_string):\n        self.conn_str = connection_string",
        metadata={"language": "python", "framework": "fastapi"},
        source_type="code",
        repo_url="https://github.com/private-org/project-api",
        file_path="src/database/manager.py", 
        commit_hash="abc123def456789",
        branch="feature/database-refactor"
    )
    
    manager.add_document_enhanced(
        content="def authenticate_user(username, password):\n    # User authentication logic\n    pass",
        metadata={"language": "python", "security": "critical"},
        source_type="code",
        repo_url="https://github.com/private-org/project-api",
        file_path="src/auth/login.py",
        commit_hash="def456abc789012", 
        branch="feature/database-refactor"
    )
    
    # Demonstrate enhanced queries
    print("=== Enhanced Document Management Demo ===")
    manager.print_document_summary()
    
    print("\n=== Source-Type Specific Queries ===")
    
    # Query only code documents
    code_docs = manager.query_by_source_type("database", source_type="code")
    print(f"\nCode documents about 'database': {len(code_docs)} found")
    for doc in code_docs:
        print(f"  - {doc['git_context']['file_path']}")
    
    # Query only chat/web documents
    chat_docs = manager.query_by_source_type("python", source_type="chat")
    print(f"\nChat documents about 'python': {len(chat_docs)} found")
    for doc in chat_docs:
        print(f"  - {doc['content'][:30]}...")
    
    # Repository-specific query
    repo_docs = manager.get_repository_documents("https://github.com/private-org/project-api")
    print(f"\nAll documents from private repo: {len(repo_docs)} found")
    for doc in repo_docs:
        print(f"  - {doc['git_context']['file_path']}")
    
    print("\n=== Benefits Demonstrated ===")
    print("✓ Source type awareness (chat vs code vs web)")
    print("✓ Repository-based document IDs for code files")
    print("✓ Enhanced metadata and git context tracking")
    print("✓ Source-specific querying and filtering")
    print("✓ Backward compatibility with existing chat usage")