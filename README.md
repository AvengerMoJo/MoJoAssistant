# MoJoAssistant - Your Personal AI Memory Assistant

MoJoAssistant is your intelligent memory companion that learns from your conversations and helps you remember, search, and build upon your knowledge over time. It maintains a private, persistent memory system while serving as a bridge to enhance your interactions with AI assistants.

**🎉 v1.1.0-beta Released!** - Featuring OpenCode Manager for managing AI coding agent instances with N:1 architecture.

## What is MoJoAssistant?

MoJoAssistant helps you:
- **Remember everything**: Track conversations, projects, and ideas across sessions
- **Search naturally**: Find past conversations and documents using plain language
- **Enhance AI interactions**: Provide personal context to AI assistants for better responses
- **Build knowledge**: Add documents and create a personal knowledge base
- **Stay organized**: Maintain context across different projects and areas of interest

Perfect for students, researchers, developers, professionals, or anyone who wants to remember more and work smarter with AI.

## Vision

MoJoAssistant acts as your personal AI intermediary - it learns your preferences, context, and conversation history in a private memory system, then uses this understanding to interact with public AI agents more effectively and personally. Your data stays private while you benefit from enhanced, personalized AI interactions.

## Core Architecture

MoJoAssistant consists of several integrated components:

### 1. Personal Memory System
- **Working Memory**: Current conversation context and immediate context
- **Active Memory**: Recent conversations with semantic search capabilities  
- **Archival Memory**: Long-term storage with vector-based retrieval
- **Knowledge Manager**: Personal document storage and semantic search

### 2. Memory-Compute Protocol (MCP) Server
- **HTTP API**: RESTful endpoints for memory operations
- **MCP Protocol**: Native MCP integration for Claude Desktop and other AI clients
- **Real-time Updates**: Live memory state synchronization
- **Multi-model Support**: Various embedding and LLM backends

### 3. LLM Interface Layer
- **Local LLM Support**: Run models locally for privacy
- **API Integration**: Connect to OpenAI, Claude, and other public AI services
- **Hybrid Mode**: Combine local and cloud-based intelligence
- **Model Switching**: Runtime model selection based on needs

### 4. OpenCode Manager (NEW v1.1.0-beta)
- **Multi-Project Management**: Run multiple OpenCode AI coding agent instances
- **N:1 Architecture**: Single global MCP tool for all projects (port 3005)
- **Process Lifecycle**: Start, stop, restart OpenCode instances
- **SSH Key Management**: Per-project deploy keys for git operations
- **Global Configuration**: Unified password and credential management
- **State Persistence**: Projects survive system restarts
- **Health Monitoring**: Automatic health checks and recovery

**Architecture:**
```
N OpenCode Projects → 1 Global MCP Tool (port 3005) → AI Clients
```

### 4. Web Integration
- **Web Search**: Google Custom Search API with DuckDuckGo fallback
- **Document Processing**: Add documents to your knowledge base
- **Conversation Logging**: Persistent conversation history

## Key Features

### 🔒 Privacy-First Design
- All memory processing happens locally by default
- Personal data never leaves your environment unless explicitly sent
- Configurable privacy levels for different types of information
- Memory encryption and secure storage options

### 🧠 Persistent Personal Memory
- **Contextual Understanding**: Remembers your preferences, style, and context
- **Semantic Search**: Find past conversations and information naturally
- **Knowledge Integration**: Connect your documents and memories
- **Conversation Continuity**: Maintain context across sessions

### 🌐 AI Agent Bridge
- **Proxy Interface**: Communicate with public AI agents on your behalf
- **Personalized Context**: Provide relevant personal context to external AI
- **Response Enhancement**: Use your memory to improve AI responses
- **Multi-Agent Support**: Interface with various AI services simultaneously

### 🔧 Flexible Configuration
- **Multiple Backends**: HuggingFace, local servers, APIs, and fallback options
- **Hardware Optimization**: CPU/GPU support with automatic detection
- **Model Switching**: Runtime model changes without restart
- **Customizable Architecture**: Modular design for easy extension

### 🚀 OpenCode Manager (v1.1.0-beta)
- **Isolated Sandboxes**: Each project runs in isolated environment
- **Network Accessibility**: OpenCode servers bind to all interfaces (0.0.0.0)
- **Port Management**: Automatic port allocation and reuse on restart
- **Auto-Scale MCP Tool**: Global MCP tool starts/stops based on active projects
- **Secure Configuration**: Password-protected OpenCode instances
- **Development Hot Reload**: Automatic server restarts during development

## Try MoJoAssistant in 5 Minutes

### 🚀 Quick Start (No Setup Required)

**No setup required!** Get started immediately with our interactive demo:

```bash
# Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# Install dependencies
pip install -r requirements.txt

# Start interactive demo (works immediately - no setup required!)
python app/interactive-cli.py
```

**Try these commands in the CLI:**
```
> Hello, what can you help me with?
> /stats
> /help
> I'm working on a Python machine learning project
> What should I focus on next?
```

### 🎯 Choose Your Experience

| Use Case | Recommended Setup | Time Required |
|----------|------------------|---------------|
| **Quick Demo** | Interactive CLI | 2 minutes |
| **Claude Desktop** | MCP Server | 10 minutes |
| **OpenCode Manager** | Project Management | 15 minutes |
| **Web Integration** | HTTP API | 15 minutes |
| **Custom Development** | Web API | 20 minutes |

### Full Installation

For production use or advanced features:

```bash
# 1. Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment (optional for advanced features)
cp .env.example .env
# Edit .env with your API keys if using cloud services
```

## OpenCode Manager (v1.1.0-beta)

Manage multiple OpenCode AI coding agent instances with the new OpenCode Manager:

### 🚀 Quick Start

```bash
# 1. Create global configuration
cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env
chmod 600 ~/.memory/opencode-manager.env

# 2. Start a new OpenCode project
opencode_start my-project git@github.com:user/repo.git

# 3. Check project status
opencode_status my-project

# 4. Restart a project
opencode_restart my-project

# 5. Stop a project
opencode_stop my-project
```

### Available Tools

| Tool | Description |
|------|-------------|
| `opencode_start` | Bootstrap a new OpenCode project (clone repo, start server) |
| `opencode_stop` | Stop an OpenCode project |
| `opencode_restart` | Restart an OpenCode project |
| `opencode_status` | Get project status (OpenCode and MCP tool) |
| `opencode_mcp_restart` | Restart the global MCP tool |
| `opencode_mcp_status` | Get global MCP tool status |
| `opencode_llm_config` | Get/set LLM configuration |

### Configuration

**Global Configuration** (`~/.memory/opencode-manager.env`):
```env
# OpenCode Manager Configuration
OPENCODE_MCP_TOOL_PATH=/path/to/opencode-mcp-tool
OPENCODE_BIN=/path/to/opencode

# Passwords
OPENCODE_SERVER_PASSWORD=your-opencode-password
GLOBAL_MCP_BEARER_TOKEN=your-mcp-bearer-token

# Port Configuration (optional)
GLOBAL_MCP_TOOL_PORT=3005
```

For complete setup instructions, see `RELEASE_NOTES_v1.1.0-beta.md` and `app/mcp/opencode/README.md`.

---

## What's New in v1.1.0-beta

### 🎉 OpenCode Manager
- **Multi-Project Support**: Manage multiple OpenCode instances simultaneously
- **N:1 Architecture**: Single global MCP tool (port 3005) routes to all projects
- **Process Lifecycle**: Start, stop, restart OpenCode servers
- **SSH Key Management**: Per-project deploy keys with auto-generation
- **Global Configuration**: Unified `~/.memory/opencode-manager.env` for all projects
- **State Persistence**: Projects survive system restarts
- **Health Monitoring**: Automatic health checks and recovery
- **Network Accessibility**: OpenCode servers bind to all interfaces (0.0.0.0)

### 🔧 Bug Fixes
- Fixed `active_project_count` when restarting stopped projects
- Fixed `opencode_llm_config` to include built-in provider models
- Added proper LLM configuration management
- Fixed hot reload with watchfiles alternative

### 📚 Documentation
- Comprehensive OpenCode Manager documentation in `app/mcp/opencode/`
- Setup guides and architecture diagrams
- Security audit results and configuration examples

---

## What You Can Do With MoJoAssistant

### 📝 **Personal Knowledge Base**
Add your documents and search them conversationally:
```
> /add README.md
> What does my README say about installation?
> Find all documents related to machine learning
```

### 💼 **Work Assistant**
Maintain context across work sessions:
```
> We're designing a new API for our mobile app
> What were we discussing about the API design?
> Remind me of the decisions we made last week
```

### 📦 **OpenCode Manager (v1.1.0-beta NEW)**
Manage multiple AI coding agent projects with isolated environments:
```
> opencode_start blog-api git@github.com:user/blog-api.git
> opencode_status blog-api
> opencode_restart blog-api
```

### 🎓 **Learning Companion**
Track your learning progress:
```
> I'm studying Python data structures
> What concepts have I been studying recently?
> Help me understand this based on what I already know
```

### 🤖 **Enhanced AI Assistant**
Get better responses from AI by providing personal context:
```
> What should I focus on for my career growth?
> [MoJoAssistant provides your personal context about your goals and interests]
> AI response enhanced with your personal information
```

### Basic Usage

```python
from app.services.memory_service import MemoryService

# Initialize your personal memory system
memory_service = MemoryService(data_dir=".my_memory")

# Add a conversation
memory_service.add_user_message("Hello, I'm working on a project about AI ethics")
memory_service.add_assistant_message("That's interesting! What specific aspects are you exploring?")

# Get context for future conversations
context = memory_service.get_context_for_query("What was I working on?")
print(context)
```

## Starting MoJoAssistant

### 🚀 **Option 1: Interactive CLI (Recommended First)**
Perfect for trying MoJoAssistant immediately:
```bash
python app/interactive-cli.py
```
- No configuration required
- Try all features immediately
- Perfect for understanding what MoJoAssistant does

### 🔧 **Option 2: MCP Server (For Claude Desktop Integration)**
For integration with Claude Desktop:
```bash
# Method 1: Start with unified server
python start_mcp_service.py

# Method 2: Run directly
python unified_mcp_server.py --mode stdio

# Method 3: Run with specific configuration  
python unified_mcp_server.py --mode stdio --port 8000
```

### 🌐 **Option 3: Web API (For Developers)**
For HTTP API access and custom applications:
```bash
# Start HTTP server
python unified_mcp_server.py --mode http --port 8000

# Test the server
curl http://localhost:8000/system/health
```

The MCP server provides both HTTP API and native MCP protocol support for seamless integration with Claude Desktop and other AI clients.

## Memory System Architecture

MoJoAssistant implements a sophisticated multi-tier memory system:

### Memory Tiers

1. **Working Memory** (`app/memory/working_memory.py`)
   - Current conversation context
   - Short-term attention and focus
   - Real-time conversation state

2. **Active Memory** (`app/memory/active_memory.py`)
   - Recent conversations (last 50-100 messages)
   - Semantic search across recent interactions
   - Contextual relevance scoring

3. **Archival Memory** (`app/memory/archival_memory.py`)
   - Long-term storage of important memories
   - Vector-based semantic search
   - Persistent memory across sessions

4. **Knowledge Manager** (`app/memory/knowledge_manager.py`)
   - Personal document storage
   - Document chunking and embedding
   - Knowledge retrieval and integration

### Embedding System

The memory system uses high-quality bi-directional transformer models for semantic understanding:

- **Default Model**: `nomic-ai/nomic-embed-text-v2-moe` (768 dimensions)
- **Alternative Models**: BAAI/bge-small-en-v1.5, text-embedding-3-small, and more
- **Multiple Backends**: HuggingFace, local servers, APIs, and fallback random embeddings
- **Efficient Caching**: Automatic caching to improve performance
- **Hardware Optimization**: CPU/GPU support with automatic detection

## AI Agent Integration

MoJoAssistant serves as your personal proxy to interact with public AI agents:

### Supported AI Services

- **OpenAI GPT models**: ChatGPT, GPT-4, GPT-3.5
- **Anthropic Claude**: Claude 3, Claude 2.1
- **Google Gemini**: Gemini Pro, Gemini Ultra
- **Local LLMs**: Ollama, local HuggingFace models
- **API Services**: Cohere, other compatible AI services

### Proxy Functionality

```python
# Example: MoJoAssistant as AI proxy
from app.llm.api_llm_interface import APILLMInterface

# Configure your AI agent preferences
llm = APILLMInterface(
    model="gpt-4",  # or "claude-3", "gemini-pro", etc.
    api_key="your-api-key",
    base_url="https://api.openai.com/v1"
)

# MoJoAssistant provides personal context to the AI
response = llm.generate_response(
    user_message="What should I work on today?",
    context=memory_service.get_context_for_query("current projects")
)
```

### Privacy-Powered AI Interactions

- **Local Processing**: Memory operations happen locally before sending to AI
- **Context Filtering**: Only relevant personal context shared with external AI
- **Response Enhancement**: AI responses improved with your personal knowledge
- **Consent Control**: Choose what data to share with external services

## MCP Server Integration

The Memory-Compute Protocol (MCP) server enables seamless integration with AI clients:

### Starting the Server

```bash
# Method 1: Start with unified server
python start_mcp_service.py

# Method 2: Run directly
python unified_mcp_server.py

# Method 3: Run with specific configuration  
python unified_mcp_server.py --mode stdio
```

### Available Endpoints

The MCP server provides both HTTP API and native MCP protocol support:

#### Memory Operations
- `POST /memory/conversation` - Add conversation messages
- `GET /memory/conversation` - Get current conversation
- `POST /memory/knowledge` - Add documents to knowledge base
- `GET /memory/knowledge` - List knowledge documents
- `GET /memory/context` - Get memory context for query

#### System Operations
- `GET /system/health` - Health check
- `GET /system/info` - Service information
- `POST /embeddings/switch` - Switch embedding model

#### Configuration
- `GET /config/embeddings` - List available embedding models
- `POST /embeddings/switch` - Switch to different embedding model

### Claude Desktop Integration

Configure Claude Desktop to use MoJoAssistant as an MCP server:

1. Edit your Claude Desktop configuration:
```json
{
  "mcpServers": {
    "mojo-assistant": {
      "command": "python",
      "args": ["/path/to/MoJoAssistant/unified_mcp_server.py"],
      "env": {}
    }
  }
}
```

2. Restart Claude Desktop to load the MCP server

### Bruno Collection Integration

The project includes a Bruno collection for API testing:
- `bruno_collection/` - Contains pre-configured API requests
- Test all endpoints using Bruno or import into Postman

## Configuration

MoJoAssistant uses a flexible configuration system:

### Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
```

**Quick Start Configuration** (for development):
```env
# For quick start, leave MCP_REQUIRE_AUTH=false
MCP_REQUIRE_AUTH=false
MCP_API_KEY=demo_key_for_development

# Optional: Google Search (enhances web search)
# GOOGLE_API_KEY=your_google_api_key_here
# GOOGLE_SEARCH_ENGINE_ID=your_search_engine_id_here

# Logging
LOG_LEVEL=INFO
```

**Advanced Configuration** (for production):
```env
# LLM Configuration
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GOOGLE_API_KEY=your-google-key

# Search Configuration  
GOOGLE_SEARCH_ENGINE_ID=your-search-engine-id

# MCP Configuration
MCP_REQUIRE_AUTH=true
MCP_API_KEY=your_secure_api_key

# Optional: Local model paths
LOCAL_MODEL_PATH=/path/to/local/models
```

### Configuration Files

#### Embedding Configuration (`config/embedding_config.json`)
```json
{
  "embedding_models": {
    "default": {
      "backend": "huggingface",
      "model_name": "nomic-ai/nomic-embed-text-v2-moe",
      "embedding_dim": 768,
      "device": "auto"
    },
    "fast": {
      "backend": "huggingface", 
      "model_name": "BAAI/bge-small-en-v1.5",
      "embedding_dim": 384,
      "device": "cpu"
    }
  }
}
```

#### LLM Configuration (`config/llm_config.json`)
```json
{
  "llm_backends": {
    "openai": {
      "api_key": "${OPENAI_API_KEY}",
      "base_url": "https://api.openai.com/v1",
      "models": ["gpt-4", "gpt-3.5-turbo"]
    },
    "anthropic": {
      "api_key": "${ANTHROPIC_API_KEY}",
      "models": ["claude-3-opus", "claude-3-sonnet"]
    }
  }
}
```

#### MCP Configuration (`config/mcp_config.json`)
```json
{
  "server": {
    "host": "localhost",
    "port": 8000,
    "debug": false
  },
  "memory": {
    "data_dir": ".memory",
    "max_conversation_length": 100,
    "archive_threshold": 50
  }
}
```

## Usage Examples

### Basic Memory Operations

```python
from app.services.memory_service import MemoryService

# Initialize your personal memory system
memory_service = MemoryService(data_dir=".my_memory")

# Have a conversation
memory_service.add_user_message("I'm working on a machine learning project")
memory_service.add_assistant_message("That sounds exciting! What type of ML project?")

# Later, ask about your projects
context = memory_service.get_context_for_query("What projects am I working on?")
print(context)
# Returns relevant context about your ML project
```

### Document Knowledge Base

```python
# Add documents to your knowledge base
memory_service.add_to_knowledge_base(
    document="My research paper on neural networks",
    metadata={"type": "research", "project": "ml-project"}
)

# Search your knowledge base
results = memory_service.knowledge_manager.query("neural networks")
for doc, score in results:
    print(f"Document: {doc[:100]}... (Score: {score:.2f})")
```

### AI Agent Proxy Example

```python
from app.llm.api_llm_interface import APILLMInterface
from app.services.memory_service import MemoryService

# Set up your memory system
memory = MemoryService()

# Configure AI agent proxy
llm = APILLMInterface(
    model="gpt-4",
    api_key="your-api-key",
    base_url="https://api.openai.com/v1"
)

# User asks a question through your proxy
user_question = "What should I focus on for my career growth?"

# Get personal context from your memory
personal_context = memory.get_context_for_query("career goals and interests")

# Generate AI response with personal context
response = llm.generate_response(
    user_message=user_question,
    context=personal_context
)

print(response)
# AI response is enhanced with your personal context
```

### Interactive CLI Usage

```bash
# Start the interactive CLI
python app/interactive-cli.py

# Available commands:
/embed          # Show current embedding model
/embed fast     # Switch to fast embedding model  
/stats          # Show memory statistics
/knowledge add  # Add document to knowledge base
/memory save    # Save memory state
/memory load    # Load memory state
/help           # Show all commands
```

### MCP Server API Usage

```python
import requests

# Add conversation via HTTP API
response = requests.post(
    "http://localhost:8000/memory/conversation",
    json={
        "role": "user", 
        "content": "I need help with my coding project"
    }
)

# Get memory context for AI
context_response = requests.get(
    "http://localhost:8000/memory/context",
    params={"query": "coding project"}
)

context = context_response.json()
```

### Web Search Integration

```python
# The system automatically uses web search when enabled
# Set GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID in .env

# Search results are integrated with your personal memory
# for more relevant and personalized responses
```

## Installation & Setup

### Prerequisites

- Python 3.8+
- Git (for cloning)
- Optional: GPU with CUDA support for faster inference

### Quick Installation (5 Minutes)

```bash
# 1. Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start interactive demo (no configuration needed!)
python app/interactive-cli.py
```

### Full Installation (For Advanced Features)

```bash
# 1. Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment (optional for advanced features)
cp .env.example .env
# Edit .env with your API keys if using cloud services

# 5. Download embedding models (optional, will download on first use)
# The system will automatically download models when first accessed
```

### Optional Dependencies

For enhanced functionality:

```bash
# For GPU acceleration
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# For better performance with large models
pip install flash-attn --no-build-isolation

# For advanced web search
pip install google-api-python-client

# For monitoring and metrics
pip install psutil  # Optional system monitoring
```

## Performance & Optimization

### System Requirements

- **Minimum**: 4GB RAM, 2 CPU cores
- **Recommended**: 8GB+ RAM, 4+ CPU cores, GPU optional
- **High Performance**: 16GB+ RAM, 8+ CPU cores, dedicated GPU

### Optimization Tips

1. **Model Selection**:
   - Use `BAAI/bge-small-en-v1.5` for resource-constrained environments
   - Use `nomic-ai/nomic-embed-text-v2-moe` for best quality
   - Consider cloud APIs for CPU-only environments

2. **Hardware Optimization**:
   ```python
   # Auto-detect best device
   memory_service = MemoryService(
       embedding_device="auto"  # Will use GPU if available
   )
   ```

3. **Memory Management**:
   - Regular archiving of old conversations
   - Configurable conversation length limits
   - Automatic cleanup of temporary files

4. **Caching**:
   - Embedding cache reduces computation time
   - Model cache speeds up repeated operations
   - Automatic cache management

## Advanced Features

### Multi-Model Architecture

MoJoAssistant supports multiple AI models simultaneously:

```python
# Configure multiple LLM backends
from app.llm.hybrid_llm_interface import HybridLLMInterface

hybrid_llm = HybridLLMInterface(
    models={
        "primary": "gpt-4",
        "fallback": "claude-3",
        "local": "local-model"
    }
)
```

### Privacy & Security

- **Local Processing**: All memory operations happen locally by default
- **Data Encryption**: Optional encryption for stored memories
- **API Key Security**: Secure storage and management of API keys
- **Access Control**: Configurable access controls for memory data

### Monitoring & Observability

```python
# Get system statistics
stats = memory_service.get_memory_stats()
print(f"Total memories: {stats['total_memories']}")
print(f"Knowledge documents: {stats['knowledge_documents']}")
print(f"Embedding model: {stats['embedding_model']}")

# Monitor system health
health = mcp_service.get_system_health()
print(f"System status: {health['status']}")
print(f"Memory usage: {health['memory_usage']}")
```

## Troubleshooting

### Common Issues

1. **Model Download Fails**:
   ```bash
   # Check internet connection and try again
   python -c "from app.memory.simplified_embeddings import SimpleEmbedding; SimpleEmbedding()"
   ```

2. **Memory Not Persisting**:
   - Check file permissions in data directory
   - Verify disk space availability
   - Check for proper file path configuration

3. **API Connection Issues**:
   - Verify API keys are correctly set in `.env`
   - Check network connectivity to API endpoints
   - Test API connectivity separately

4. **Performance Issues**:
   - Monitor system resources with `htop` or `task manager`
   - Consider switching to smaller embedding models
   - Enable GPU acceleration if available

### Debug Mode

Enable debug logging for troubleshooting:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or in configuration
{
  "debug": true,
  "log_level": "DEBUG"
}
```

## Troubleshooting Common Issues

### **"Module not found" errors**
```bash
# Make sure you're in the project directory and virtual environment is activated
cd MoJoAssistant
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### **Cannot clone repository**
```bash
# If the URL doesn't work, try:
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
```

### **Embedding model fails to load**
```bash
# Try the fast model or fallback
/embed fast
# Or use random embeddings as fallback
/embed fallback
```

### **Out of memory errors**
```bash
# Use CPU instead of GPU
export EMBEDDING_DEVICE="cpu"
# Or use a smaller model
/embed fast
```

### **No immediate success with CLI**
The CLI works immediately without configuration. If you're having issues:
1. Make sure you're in the correct directory
2. Check that the virtual environment is activated
3. Try reinstalling dependencies: `pip install -r requirements.txt`

### **Getting Help**
- Use `/help` in the CLI for command reference
- Use `/stats` to check memory system status
- Check the logs in `.memory/` directory for detailed error information
- Review the documentation in `docs/` for advanced usage

## Contributing

MoJoAssistant is designed to be extensible. Key areas for contribution:

- **New Memory Tiers**: Additional memory storage backends
- **AI Agent Integration**: Support for more AI services
- **Embedding Models**: Integration with new embedding technologies
- **Privacy Features**: Enhanced security and privacy controls
- **Performance Optimizations**: Speed and efficiency improvements

See `CONTRIBUTING.md` for detailed contribution guidelines.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

## Next Steps

### 🎯 **After Your First Session**
1. **Add your documents**: Use `/add filename` to import your files
2. **Experiment with models**: Try `/embed fast` for better performance
3. **Save important conversations**: Use `/save my_conversation.json`
4. **Explore memory statistics**: Use `/stats` to see your memory usage

### 🚀 **Advanced Setup**
1. **Claude Desktop Integration**: Set up MCP server for seamless AI assistant access
2. **Web Search**: Configure Google API for enhanced search capabilities
3. **Custom Applications**: Use the HTTP API for your own integrations
4. **Multiple Models**: Switch between different embedding and LLM models

### 📚 **Learn More**
- **API Documentation**: See `docs/` for detailed technical documentation
- **Google API Setup**: Follow `GOOGLE_API_SETUP.md` for enhanced web search
- **Claude Integration**: Check `claude-docs/` for Claude Desktop setup
- **Examples**: Explore `example.py` and `experimental/` for advanced usage

### 🤝 **Community & Support**
- **Issues**: Report bugs and request features on GitHub Issues
- **Discussions**: Join discussions on GitHub Discussions  
- **Community**: Connect with other users and contributors
- **Contributing**: See `CONTRIBUTING.md` for development guidelines

---

## MoJoAssistant: Your AI Memory Companion

MoJoAssistant helps you remember more, work smarter, and build lasting knowledge. Whether you're a student, researcher, developer, or professional, it adapts to your needs and grows with you over time.

**Start today** and experience the power of persistent, personal memory enhanced by AI.

**Quick reminder**: Don't forget to set up your GPG passphrase for git operations if you encounter issues!
