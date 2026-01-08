# MoJoAssistant System Documentation

## Overview

MoJoAssistant is an advanced AI memory and code understanding system that bridges the gap between Chat AI clients (which can't see codebases directly) and Coding AI assistants (which can see code but lack persistent memory). The system provides semantic memory storage, git-aware codebase access, and intelligent document retrieval through a Model Context Protocol (MCP) server.

## Core Architecture

### Memory System Tiers
- **Working Memory**: Active conversation context and immediate tasks
- **Active Memory**: Recent interactions and frequently accessed information
- **Archival Memory**: Long-term storage of conversations and insights
- **Knowledge Base**: Structured information, code metadata, and git-aware documents

### Git-Aware Code Understanding
The system can access private repositories with SSH authentication and stores code metadata with semantic embeddings, enabling Chat AI to understand codebases without direct file access.

## Key Capabilities

### 1. Semantic Memory Storage
- Document storage with embedding-based search
- Automatic metadata extraction and categorization
- Hierarchical memory organization (repo → document → file)
- Support for code metadata and git-aware documents

### 2. Private Repository Access
- SSH key-based authentication for private repos
- Secure repository cloning and file retrieval
- Support for specific commit hash lookups
- Automatic repository updates and synchronization

### 3. MCP Server Integration
- RESTful API with OAuth 2.1 authentication support
- Real-time memory search and retrieval
- Git repository management endpoints
- Cross-platform compatibility (Windows, macOS, Linux)

## API Endpoints

### Memory Management
- `POST /add_documents` - Store documents with optional code metadata
- `POST /search_memory` - Semantic search across all memory tiers
- `GET /conversation_history` - Retrieve conversation context
- `POST /remove_conversation_message` - Remove specific messages

### Git Repository Management
- `POST /add_git_repository` - Register private repository with SSH key
- `GET /get_git_file_content` - Retrieve file content from registered repo
- `GET /list_git_repositories` - List all registered repositories

### System Management
- `GET /list_tools` - Available MCP tools and capabilities
- `GET /health` - System health and status check

## Workflow Examples

### Chat AI Understanding Private Codebase
1. Chat AI searches memory for code-related information
2. System returns code metadata stored by previous Coding AI sessions
3. If actual files needed, system retrieves from registered git repositories
4. Chat AI gains understanding without direct codebase access

### Coding AI Storing Insights
1. Coding AI analyzes codebase and identifies key patterns
2. Creates code metadata documents with semantic descriptions
3. Stores in knowledge base with git repository links
4. Future Chat AI sessions can discover these insights

## Security Features

### SSH Key Management
- Local SSH key storage with secure permissions (600)
- Environment-based git authentication
- Temporary SSH configuration for operations
- No plaintext credential storage

### Authentication
- Optional API key authentication for MCP endpoints
- OAuth 2.1 support for client authentication
- CORS configuration for web client access
- Secure memory isolation between sessions

## Configuration

### Environment Variables
- `MCP_HOST` - Server bind address (default: 0.0.0.0)
- `MCP_PORT` - Server port (default: 8000)
- `MCP_API_KEY` - Optional API authentication key
- `MCP_CORS_ORIGINS` - CORS allowed origins (default: *)

### Repository Setup
```bash
# Register a private repository
# IMPORTANT: SSH key must NOT have a passphrase
# Remove passphrase with: ssh-keygen -p -f ~/.ssh/id_rsa
curl -X POST "http://localhost:8000/add_git_repository" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_name": "my-project",
    "repo_url": "git@github.com:user/repo.git",
    "ssh_key_path": "~/.ssh/id_rsa",
    "branch": "main"
  }'
```

### File Retrieval
```bash
# Get file content from registered repository
curl -X GET "http://localhost:8000/get_git_file_content" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_name": "my-project",
    "file_path": "src/main.py",
    "git_hash": "abc123def",
    "update_repo": false
  }'
```

## Memory Search Capabilities

### Semantic Search
The system uses embedding-based semantic search to find relevant information across:
- Stored documents and conversations
- Code metadata and descriptions
- Git repository insights and patterns
- Cross-reference between repos and files

### Code-Aware Search
- Language detection and syntax awareness
- Function and class-level metadata storage
- Dependency and import relationship tracking
- Architectural pattern recognition

## Use Cases

### For Chat AI Clients
- **Code Understanding**: Ask questions about private codebases without file access
- **Architecture Discovery**: Find patterns and structures through stored metadata
- **Historical Context**: Access previous code analysis and insights
- **Cross-Repository Search**: Find related code across multiple projects

### For Coding AI Assistants
- **Knowledge Persistence**: Store insights for future Chat AI reference
- **Code Documentation**: Create searchable descriptions of complex systems
- **Pattern Libraries**: Build reusable architectural knowledge
- **Team Knowledge Sharing**: Enable cross-session code understanding

### For Development Teams
- **Onboarding**: Help new team members understand codebases
- **Code Review**: Access historical context and patterns
- **Refactoring**: Find all related code across repositories
- **Documentation**: Maintain living code documentation

## Technical Stack

### Core Dependencies
- **FastAPI**: Web framework for MCP server
- **GitPython**: Git repository access and management
- **Sentence Transformers**: Semantic embedding generation
- **Uvicorn**: ASGI server for production deployment
- **Pydantic**: Data validation and serialization

### Supported Languages
Auto-detection for: Python, JavaScript, TypeScript, Java, C++, Go, Rust, PHP, Ruby, Swift, Kotlin, and 15+ additional languages with appropriate metadata extraction.

## Deployment

### Local Development
```bash
# Start MCP service with development settings
python start_mcp_service.py --host localhost --port 8000 --reload --log-level DEBUG

# Production deployment
python start_mcp_service.py --host 0.0.0.0 --port 8000 --api-key "your-secure-key"
```

### Server Deployment
The system is designed for cloud deployment with:
- Containerization support (Docker ready)
- Environment-based configuration
- Scalable memory storage backends
- Health monitoring and logging

## Integration Examples

### Claude Desktop Integration
```json
{
  "mcpServers": {
    "mojoassistant": {
      "command": "python",
      "args": ["/path/to/start_mcp_service.py", "--port", "8000"],
      "env": {
        "MCP_API_KEY": "your-api-key"
      }
    }
  }
}
```

### VS Code Integration
The system can be integrated with VS Code through MCP protocol for:
- Real-time code understanding
- Contextual memory search
- Cross-repository insights
- Automated documentation generation

## Best Practices

### Memory Organization
- Use descriptive metadata when storing code insights
- Include repository context in all code-related documents
- Tag documents with relevant programming languages and frameworks
- Maintain clear separation between different project contexts

### Security
- Use separate SSH keys for different repository access levels
- Regularly rotate API keys and SSH credentials
- Configure CORS origins restrictively in production
- Monitor access logs for unusual patterns

### Performance
- Enable repository updates only when necessary
- Use specific commit hashes for historical code analysis
- Implement caching for frequently accessed files
- Monitor memory usage for large codebases

## Troubleshooting

### Common Issues
- **SSH Authentication Failed**: Verify SSH key permissions and git configuration
- **Repository Not Found**: Check repository URL format and SSH key access
- **Memory Search Empty**: Ensure documents are properly indexed with metadata
- **Port Conflicts**: Use different ports for multiple MCP server instances

### Debug Commands
```bash
# Test SSH key access
ssh -i ~/.ssh/your_key -T git@github.com

# Check git configuration
git config --list | grep ssh

# Verify MCP server health
curl http://localhost:8000/health

# Test memory search
curl -X POST "http://localhost:8000/search_memory" \
  -H "Content-Type: application/json" \
  -d '{"query": "git integration", "max_results": 5}'
```

---

*This documentation provides comprehensive information about MoJoAssistant's git-aware memory system. For specific implementation details, refer to the source code in the app/ directory.*