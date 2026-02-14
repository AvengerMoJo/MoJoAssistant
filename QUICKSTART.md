# MoJoAssistant - Quick Start Guide

Get MoJoAssistant running in **5 minutes** with this quick start guide.

---

## Prerequisites

- **Python 3.9+** ([Download Python](https://www.python.org/downloads/))
- **~2 GB free disk space**
- **Internet connection** (for initial setup)
- **No GPU required!** (Works on CPU only)

---

## Installation (One Command)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant

# 2. Run the installer
python3 install.py
```

That's it! The installer will:
- ✅ Create Python virtual environment
- ✅ Install all dependencies (CPU-only)
- ✅ Download Qwen2.5-Coder-1.7B model (~1.2 GB)
- ✅ Generate configuration files
- ✅ Create startup scripts

**Installation takes 5-15 minutes** depending on your internet speed.

---

## Usage

### Option 1: Interactive Chat CLI

Talk to the AI assistant directly in your terminal:

```bash
./run_cli.sh
```

Example:
```
You: Hello! Can you help me understand how dreaming works?
AI: Hello! I'd be happy to explain the dreaming system...
```

### Option 2: Claude Desktop Integration (MCP Server)

Use MoJoAssistant's 30+ tools in Claude Desktop:

**Step 1**: Start the MCP server
```bash
./run_mcp.sh
```

**Step 2**: Configure Claude Desktop

Edit your Claude Desktop config file:
- **macOS/Linux**: `~/.config/claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add this configuration:
```json
{
  "mcpServers": {
    "mojoassistant": {
      "command": "/absolute/path/to/MoJoAssistant/run_mcp.sh",
      "args": []
    }
  }
}
```

**Replace** `/absolute/path/to/MoJoAssistant` with your actual path:
```bash
cd MoJoAssistant
pwd  # Copy this path
```

**Step 3**: Restart Claude Desktop

---

## Available Features

Once installed, you can use:

### 🧠 Memory & Knowledge
- **Save conversations** - Store important discussions
- **Search memories** - Find information from past conversations
- **Document storage** - Save and retrieve documents

### 💭 Dreaming (Memory Consolidation)
- **Process conversations** - Transform chats into structured knowledge
- **Archive memories** - Long-term storage with versioning
- **Progressive quality** - Upgrade archive quality levels

### ⏰ Scheduler
- **Schedule tasks** - Run background jobs
- **Automatic dreaming** - Consolidate memories overnight
- **Task management** - View and manage scheduled tasks

### 💻 OpenCode Manager (Remote Development)
- **Start coding projects** - Spin up development environments
- **Remote access** - Work from anywhere
- **Project management** - Manage multiple coding sessions

---

## Next Steps

### 1. Test the Installation

```bash
# Verify everything is working
source venv/bin/activate
python -m app.dreaming.setup check
```

Expected output:
```
✓ Qwen2.5-Coder-1.7B model found locally
✓ llama-cpp-python installed
✓ Configuration valid
```

### 2. Explore the Tools

In Claude Desktop, you can now use tools like:
- `get_memory_context` - Search your knowledge base
- `dreaming_process` - Process conversations through A→B→C→D pipeline
- `scheduler_add_task` - Schedule background tasks
- `opencode_project_start` - Start a coding project

### 3. Read the Full Documentation

- **[INSTALL.md](INSTALL.md)** - Comprehensive installation guide with troubleshooting
- **[README.md](README.md)** - Full project documentation
- **[app/dreaming/README.md](app/dreaming/README.md)** - Dreaming system details

---

## Troubleshooting

### Installation Failed?

**Python version too old**:
```bash
python3 --version  # Must be 3.9+

# Ubuntu/Debian
sudo apt update && sudo apt install python3.11

# macOS (with Homebrew)
brew install python@3.11
```

**Build tools missing** (for llama-cpp-python):
```bash
# Ubuntu/Debian
sudo apt-get install build-essential python3-dev

# macOS
xcode-select --install
```

### MCP Server Won't Start?

```bash
# Check logs
cat server.log
cat mcp_server.log

# Manually test
source venv/bin/activate
python unified_mcp_server.py --mode stdio
```

### Need More Help?

See **[INSTALL.md](INSTALL.md)** for detailed troubleshooting or open an issue on GitHub.

---

## Configuration (Optional)

### Add API Keys

Edit `.env` to enable premium features:

```bash
# OpenAI (for embeddings, optional)
OPENAI_API_KEY=sk-your-key-here

# Anthropic (for Claude API, optional)
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Customize LLM Settings

Edit `config/llm_config.json` to:
- Add more models
- Adjust context lengths
- Configure task assignments

### Enable Automatic Dreaming

Edit `.env`:
```bash
DREAMING_ENABLED=true
DREAMING_SCHEDULE=0 3 * * *  # Daily at 3 AM
```

---

## Performance

**Qwen2.5-Coder-1.7B on CPU**:
- **Speed**: ~80 tokens/sec on modern CPUs
- **Memory**: ~2 GB RAM
- **Context**: 32K tokens

**Good enough for**:
- Interactive chat
- Memory consolidation
- Background tasks
- Code assistance

---

## Support

- **GitHub Issues**: Report bugs or request features
- **Documentation**: See `README.md` and `INSTALL.md`
- **Logs**: Check `server.log` and `mcp_server.log`

---

## What's Next?

1. ✅ **Try the Interactive CLI** - Chat with the AI
2. ✅ **Configure Claude Desktop** - Unlock MCP tools
3. ✅ **Save your first conversation** - Test memory storage
4. ✅ **Process a dream** - Run the A→B→C→D pipeline
5. ✅ **Schedule a task** - Set up automatic dreaming

**Happy coding with MoJoAssistant!** 🚀

---

**CPU-Only Setup** | **No GPU Required** | **~80 tokens/sec** | **1.2 GB Download**
