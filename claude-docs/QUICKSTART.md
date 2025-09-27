# MoJoAssistant Quick Start Guide

Get up and running with MoJoAssistant in minutes!

## 🚀 5-Minute Quick Start

No setup required! Try MoJoAssistant immediately:

```bash
# Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# Install dependencies
pip install -r requirements.txt

# Start interactive demo (works immediately!)
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

## Prerequisites

- Python 3.8+
- Git

## Full Installation

For production use or advanced features:

```bash
# 1. Clone the repository
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. Set up virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment (optional for advanced features)
cp .env.example .env
# Edit .env with your API keys if using cloud services
```

## Basic Usage

### Start the Interactive CLI

```bash
python app/interactive-cli.py
```

### Basic Commands

Once in the CLI, you can:

- **Chat normally**: Just type your message and press Enter
- **View memory stats**: `/stats`
- **Change embedding model**: `/embed fast` (for faster, lighter model)
- **Save conversation**: `/save my_conversation.json`
- **Add documents**: `/add path/to/document.txt`
- **Get help**: `/help`

### Example Session

```
> Hello, I'm working on a Python project
Assistant: Hello! I'd be happy to help with your Python project...

> /stats
Memory Statistics:
- Working Memory: 2 messages
- Active Memory: 0 pages
- Archival Memory: 0 items
- Knowledge Base: 0 documents

> /add README.md
Document added to knowledge base successfully!

> What does my README say about installation?
Assistant: Based on your README, the installation process involves...
```

## Configuration

### Using Environment Variables (Recommended)

For API-based embedding models, set environment variables instead of editing config files:

```bash
# For OpenAI embeddings
export OPENAI_API_KEY="sk-your-key-here"
export EMBEDDING_MODEL="text-embedding-3-small"
export EMBEDDING_BACKEND="api"

# For Cohere embeddings  
export COHERE_API_KEY="your-cohere-key"
export EMBEDDING_MODEL="embed-english-v3.0"
export EMBEDDING_BACKEND="api"

# Then start the CLI
python app/interactive-cli.py
```

### Configuration Files

Configuration files are in the `config/` directory:
- `embedding_config.json` - Embedding model settings
- `llm_config.json` - LLM settings

## Available Embedding Models

| Model | Speed | Quality | Memory Usage |
|-------|-------|---------|--------------|
| `default` | Medium | High | High |
| `fast` | Fast | Good | Low |
| `openai` | Fast | High | None (API) |
| `cohere` | Fast | High | None (API) |

Switch models anytime with: `/embed MODEL_NAME`

## Memory System

MoJoAssistant uses a 4-tier memory system:

1. **Working Memory** - Current conversation
2. **Active Memory** - Recent conversations  
3. **Archival Memory** - Long-term storage
4. **Knowledge Base** - Your documents

The system automatically manages memory transitions and provides semantic search across all tiers.

## Troubleshooting

### Common Issues

**"Module not found" errors**
```bash
# Make sure you're in the project directory and virtual environment is activated
cd MoJoAssistant
source .venv/bin/activate
```

**Embedding model fails to load**
```bash
# Try the fast model or fallback
/embed fast
# Or use random embeddings as fallback
/embed fallback
```

**Out of memory errors**
```bash
# Use CPU instead of GPU
export EMBEDDING_DEVICE="cpu"
# Or use a smaller model
/embed fast
```

### Getting Help

- Use `/help` in the CLI for command reference
- Use `/env` for environment variable help
- Check the logs in `.memory/` directory for detailed error information

## Next Steps

- Add your documents with `/add filename`
- Experiment with different embedding models
- Save important conversations with `/save`
- Explore the memory statistics with `/stats`

For advanced usage and development, see the full documentation in the `docs/` directory.
