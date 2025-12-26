# MCP MoJoAssistant Git Base Document Feature

## 🎯 **Overview**

The MCP (Memory Communication Protocol) integration for MoJoAssistant now includes enhanced git-aware document functionality, enabling repository-based knowledge management through both REST API and MCP tool interfaces.

## 🔧 **MCP Tool Enhancement: add_documents**

### **Enhanced Schema (Backward Compatible)**
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
            "content": {
              "type": "string",
              "description": "Document content (supports Chinese and English text)"
            },
            "metadata": {
              "type": "object",
              "description": "Optional metadata for organization"
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

## 💼 **Usage Examples**

### **Traditional Chat Usage (Backward Compatible)**
```json
{
  "documents": [{
    "content": "Python best practices for web development",
    "metadata": {"source": "python.org", "category": "best-practices"}
  }]
}
```

### **Development CLI Usage (New Git-Aware Feature)**
```json
{
  "documents": [{
    "content": "class DatabaseManager:\n    def connect(self):\n        return self.connection",
    "metadata": {"tags": ["database", "connection"]},
    "source_type": "code",
    "repo_url": "https://github.com/myusername/myproject",
    "file_path": "src/database/manager.py",
    "commit_hash": "abc123def456",
    "branch": "feature/database-refactor",
    "version": "v2.1.0"
  }]
}
```

## 🗂️ **Repository-Based Storage Integration**

### **MCP Processing Flow**
1. **Document Reception**: MCP receives documents with git context
2. **Context Extraction**: System extracts repository, branch, commit, and file path
3. **Deterministic ID Generation**: Creates repository-based document IDs
4. **Storage Organization**: Documents organized by repository structure
5. **Metadata Enhancement**: Git context added to document metadata

### **Storage Structure**
```
knowledge_base/
└── github.com/
    └── myusername/
        └── myproject/
            └── main/
                └── abc123def456/
                    └── src/
                        └── database/
                            └── manager.py
                                └── Document ID: repo_file_commit_based
```

## 🧠 **AI Intelligence Features**

### **Repository-Aware Querying**
MCP clients can now leverage repository context for smarter queries:

```python
# Query by source type
results = query_by_source_type("authentication patterns", source_type="code")

# Query by repository
repo_docs = get_repository_documents("https://github.com/myusername/myproject")

# Query by branch
branch_docs = query_by_branch("feature/auth-refactor")
```

### **Context-Aware Responses**
AI can now provide responses with full repository context:

```
Question: "How do I handle database connections?"

AI Response: "Based on your myproject repository:
- Main branch, commit abc123def456
- src/database/manager.py (lines 15-23):
  
  class DatabaseManager:
      def connect(self):
          return self.connection
          
This was added in the 'feature/database-refactor' branch 
and represents the latest connection pattern in your codebase."
```

## 🔄 **Development Workflow Integration**

### **For Development CLI Users (Crush + MiniMax-M2.1)**
1. **File Addition**: `mojo-assistant add-file src/database/manager.py`
2. **Git Context**: System automatically extracts repository context
3. **Intelligent Storage**: Documents organized by repository structure
4. **Context Preservation**: Full git history and file path preserved

### **For Chat Clients**
1. **Manual Addition**: Users manually specify document content
2. **Source Classification**: Documents categorized by source_type
3. **Metadata Enhancement**: Additional context can be provided
4. **Traditional Search**: Standard semantic search across all documents

## 🚀 **Benefits for MCP Integration**

### **1. Feature Parity**
- REST API and MCP tool now have identical capabilities
- No functionality gap between interfaces
- Consistent user experience across all access methods

### **2. Enhanced Intelligence**
- MCP clients can leverage repository context
- More accurate and relevant document retrieval
- Better understanding of document provenance

### **3. Developer Experience**
- Natural integration with existing git workflows
- Repository-aware documentation management
- Time-travel capability through git history

### **4. Scalability**
- Efficient storage and retrieval through repository organization
- Multi-repository support for developers working on multiple projects
- Intelligent filtering and scoping for large codebases

## 🔧 **Implementation Details**

### **Enhanced MCP Service**
- Updated `/api/v1/knowledge/documents` endpoint
- Support for git context fields in DocumentInput model
- Deterministic ID generation for repository-based documents
- Source-aware processing and storage

### **MCP Tool Schema**
- Enhanced add_documents tool with git-aware fields
- Backward compatibility maintained
- Comprehensive documentation and examples

### **Knowledge Manager Updates**
- Repository-based document ID generation
- Source-type aware indexing and querying
- Git context extraction and storage
- Enhanced search capabilities

## 🎯 **Next Steps**

### **Phase 2: Advanced Repository Integration**
- Automatic repository synchronization
- Real-time commit tracking
- Branch-aware documentation workflows
- Repository change detection and updates

### **Phase 3: Advanced AI Features**
- Cross-repository pattern analysis
- Code evolution tracking
- Repository similarity analysis
- Intelligent document recommendations

This MCP integration establishes the foundation for a repository-aware AI knowledge system that understands code context like a human developer.