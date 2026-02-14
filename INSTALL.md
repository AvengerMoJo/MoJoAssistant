# MoJoAssistant - Installation Guide

**Quick Setup for Users Without GPU (CPU-Only)**

This guide will help you install and set up MoJoAssistant in just a few minutes. No GPU required!

---

## 📋 Requirements

- **Python 3.9 or higher**
- **~2 GB free disk space** (for model downloads)
- **Internet connection** (for initial setup)
- **No GPU required!** (Works on CPU only)

---

## 🚀 Quick Install (Recommended)

### Step 1: Clone or Download

```bash
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant
```

### Step 2: Run One-Command Install

```bash
python3 install.py
```

That's it! The script will:
- ✅ Check Python version
- ✅ Create virtual environment
- ✅ Install all dependencies (including llama-cpp-python for CPU)
- ✅ Download Qwen2.5-Coder-1.7B model (~1.2 GB)
- ✅ Generate configuration files
- ✅ Create startup scripts
- ✅ Test the installation

**Installation takes about 5-15 minutes** depending on your internet speed.

---

## 🎯 What Gets Installed

### Dependencies
- **FastAPI & Uvicorn** - Web server for MCP
- **llama-cpp-python** - CPU-only inference (no GPU needed!)
- **Anthropic SDK** - For API integration (optional)
- **Prompt Toolkit** - Interactive CLI interface
- **And more...** (see requirements.txt)

### Model
- **Qwen2.5-Coder-1.7B** (Q5_K_M quantization)
  - Size: ~1.2 GB
  - Performance: ~80 tokens/sec on CPU
  - Multi-language support (English, Chinese, etc.)
  - Saved to: `~/.cache/mojoassistant/models/`

### Configuration Files
- **config/llm_config.json** - LLM configuration
- **.env** - Environment variables
- **~/.memory/** - Memory storage directories

### Startup Scripts
- **run_cli.sh** - Start interactive chat CLI
- **run_mcp.sh** - Start MCP server for Claude Desktop

---

## 🔧 Post-Installation

### 1. Test the Interactive CLI

```bash
./run_cli.sh
```

This starts a chat interface where you can talk to Qwen2.5-Coder-1.7B.

Example conversation:
```
You: Hello, can you help me?
AI: Hello! Yes, I'd be happy to help. What would you like to know about?
```

### 2. Start the MCP Server (for Claude Desktop)

```bash
./run_mcp.sh
```

This starts the MCP server in STDIO mode, ready for Claude Desktop integration.

### 3. Configure Claude Desktop

Add to your Claude Desktop config file:

**macOS/Linux**: `~/.config/claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

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

**Replace** `/absolute/path/to/MoJoAssistant` with your actual path!

To get the absolute path:
```bash
cd MoJoAssistant
pwd
```

---

## 🆘 Troubleshooting

### Python Version Issues

**Problem**: "Python 3.9 or higher required"

**Solution**:
```bash
# Check your Python version
python3 --version

# On Ubuntu/Debian
sudo apt update
sudo apt install python3.11

# On macOS (using Homebrew)
brew install python@3.11
```

### llama-cpp-python Installation Fails

**Problem**: "Failed to install llama-cpp-python"

**Solution**: Install build tools

**Ubuntu/Debian**:
```bash
sudo apt-get install build-essential python3-dev
```

**macOS**:
```bash
xcode-select --install
```

**Then retry**:
```bash
python3 install.py
```

### Model Download Fails

**Problem**: "Failed to download model"

**Solution**: Download manually

```bash
# Activate virtual environment
source venv/bin/activate

# Download model
python -m app.dreaming.setup install

# Validate model
python -m app.dreaming.setup validate
```

### MCP Server Won't Start

**Problem**: MCP server fails to start

**Solution**: Check logs

```bash
# Check server logs
cat server.log
cat mcp_server.log

# Test manually
source venv/bin/activate
python unified_mcp_server.py --mode stdio
```

### Memory/Disk Space Issues

**Problem**: "No space left on device"

**Solution**: Free up space

The model requires ~1.2 GB. If you're low on space:
1. Delete unnecessary files
2. Use a different cache directory (edit `config/llm_config.json`)

---

##  📚 Next Steps

### Learn Available Tools

The MCP server provides 30+ tools for Claude Desktop:

- **Memory Tools** - Store and recall information
  - `get_memory_context` - Search memory
  - `add_conversation` - Save conversations
  - `add_documents` - Store documents

- **Dreaming Tools** - Memory consolidation
  - `dreaming_process` - Process conversations (A→B→C→D)
  - `dreaming_list_archives` - List archived memories
  - `dreaming_get_archive` - Retrieve specific archive

- **Scheduler Tools** - Background tasks
  - `scheduler_add_task` - Schedule tasks
  - `scheduler_list_tasks` - View scheduled tasks
  - `scheduler_get_status` - Check scheduler status

- **OpenCode Tools** - Remote development
  - `opencode_project_start` - Start coding project
  - `opencode_project_status` - Check project status
  - `opencode_project_stop` - Stop project

### Configure Advanced Features

**1. Add API Keys (Optional)**

Edit `.env` file to enable premium features:

```bash
# OpenAI (for embeddings, advanced features)
OPENAI_API_KEY=sk-your-key-here

# Anthropic (for Claude API)
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Google (for web search)
GOOGLE_API_KEY=your-key-here
```

**2. Customize LLM Configuration**

Edit `config/llm_config.json` to:
- Add more models
- Adjust quality levels
- Configure task assignments

**3. Set Up Automatic Dreaming**

Dreaming consolidates conversations automatically.

Edit `.env`:
```bash
DREAMING_ENABLED=true
DREAMING_SCHEDULE=0 3 * * *  # Daily at 3 AM
```

Start scheduler:
```bash
# Already running if you use run_mcp.sh
# The scheduler starts automatically
```

---

## 🔍 Verify Installation

Run the system check:

```bash
source venv/bin/activate
python -m app.dreaming.setup check
```

Expected output:
```
✓ LMStudio detected (if running)
✓ Ollama detected (if running)
✓ Qwen2.5-Coder-1.7B model found locally
✓ llama-cpp-python installed
```

---

## 🌟 What You Can Do Now

### 1. Chat with AI

```bash
./run_cli.sh
```

Ask questions, get help, store knowledge!

### 2. Use in Claude Desktop

Once MCP server is configured in Claude Desktop, you can:
- Store and retrieve memories
- Schedule background tasks
- Process and archive conversations
- Search your knowledge base
- And much more!

### 3. Explore Features

Read the documentation:
- `README.md` - Main documentation
- `app/dreaming/README.md` - Memory consolidation
- `app/scheduler/README.md` - Task scheduling
- `app/mcp/opencode/README.md` - Remote development

---

## 💡 Tips for Best Experience

1. **Use Descriptive Names**: When saving memories, use clear, descriptive names
2. **Regular Dreaming**: Let the system consolidate memories overnight
3. **Organize with Labels**: Tag conversations with topics for easier search
4. **Backup Your Memory**: Your memory is stored in `~/.memory/` - back it up!

---

## 🎓 Learning Resources

- **Interactive Setup Wizard**: `python app/setup_wizard.py`
- **API Documentation**: See `docs/` folder (coming soon)
- **Example Scripts**: Check `examples/` folder (coming soon)

---

## 🤝 Getting Help

- **Issues**: Open an issue on GitHub
- **Discussions**: Join community discussions
- **Logs**: Check `server.log` and `mcp_server.log`

---

## 🎉 Congratulations!

You've successfully installed MoJoAssistant!

Start with the interactive CLI to get familiar:
```bash
./run_cli.sh
```

Then configure Claude Desktop to unlock the full power of MCP tools!

---

**Happy coding with MoJoAssistant!** 🚀
