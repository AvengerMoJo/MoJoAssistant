# Release Notes - v1.1.3-beta

**Release Date:** 2026-02-21
**Type:** Beta Release
**Theme:** Smart Installer & AI-Powered Configuration

---

## 🎯 Overview

This beta release introduces a completely redesigned installation system powered by AI agents. The new smart installer provides an intelligent, conversational setup experience that adapts to user needs while maintaining simplicity for beginners.

---

## ✨ Major Features

### 1. 🤖 Smart Installer with AI Agents

**New architecture:** Installer orchestrator coordinates specialized AI agents to guide users through setup.

**Key improvements:**
- **Model Selector Agent** - Intelligently downloads and configures LLM models
  - Default recommended model (Qwen3-1.7B) for quick start
  - HuggingFace search to find any GGUF model
  - Automatic mirror configuration for China users
  - Resume support for interrupted downloads

- **Environment Configurator Agent** - AI-guided `.env` setup
  - Tool-based approach optimized for small (1.7B) models
  - Analyzes existing configuration before asking questions
  - Adapts questions based on user's chosen use case
  - Validates API key formats and provides helpful error messages

- **Bootstrap LLM** - Quiet background LLM for installer agents
  - Auto-detects Ollama, LMStudio, or local models
  - Suppresses debug output for clean installation UX
  - Graceful fallback to rule-based mode if no LLM available

**Usage:**
```bash
python app/interactive-cli.py --setup
```

**File:** `app/installer/orchestrator.py`

---

### 2. 📋 Tool-Based Configuration System

**Problem solved:** Small LLMs (1.7B) struggled with complex prompts and hallucinated status summaries.

**New approach:**
- **Code handles structure** - Python parses `.env` and metadata
- **LLM asks questions** - AI only formulates natural questions
- **Tool calling** - LLM calls `get_missing_keys()` and `set_value()` functions

**Benefits:**
- ✅ Works reliably with 1.7B models
- ✅ No hallucinations about configuration state
- ✅ Clear separation: data (Python) vs conversation (LLM)
- ✅ Optimized prompt (50 lines vs 382 lines)

**Files:**
- `config/installer_prompts/env_configurator_tool_based.md` - Optimized prompt
- `app/installer/agents/env_configurator.py` - Tool implementations
- `demo_tool_based_config.py` - Standalone demo

**Documentation:** `TOOL_BASED_CONFIGURATOR.md`

---

### 3. 📚 Comprehensive Environment Variable Documentation

**New file:** `config/env_variables.json`

**Contains:**
- **60+ variables** fully documented with:
  - Description and purpose
  - Type, default value, examples
  - How to obtain API keys
  - Format requirements (e.g., "starts with 'sk-'")
  - Cost information for paid services
  - Sensitive flag for secrets

- **10 categories:**
  - Server configuration
  - MCP authentication
  - OAuth 2.1 settings
  - LLM provider API keys
  - Search configuration
  - Memory/knowledge system
  - Logging
  - Feature flags
  - GitHub integration
  - OpenCode manager

- **5 predefined use cases:**
  - `local_only` - No API keys, fully private
  - `cloud_ai` - OpenAI/Anthropic/Google/OpenRouter
  - `hybrid` - Mix of local + cloud
  - `github_integration` - GitHub token + OpenCode
  - `claude_desktop` - OAuth 2.1 setup

**Enables:** Data-driven configuration instead of hardcoded templates.

---

### 4. 🗂️ Model Catalog System

**New file:** `config/model_catalog.json`

**Features:**
- **6 curated models** with metadata:
  - Download URLs from HuggingFace
  - Repository and filename info
  - Model size, requirements, capabilities
  - Default model marked (`qwen3-1.7b-q5`)

- **Mirror configuration** for China users
- **Extensible** - agents can add searched models to catalog

**Files:**
- `config/model_catalog.json` - Model metadata
- `app/installer/agents/model_selector.py` - Model download logic

---

### 5. 🔌 LMStudio Integration Improvements

**Enhancements:**
- Multi-port detection (tries 8080, then 1234)
- API token support via `LMSTUDIO_API_KEY` environment variable
- Authorization header for auth-required instances
- Better error messages when connection fails

**File:** `app/installer/bootstrap_llm.py`

---

### 6. 🧹 Directory Cleanup & Organization

**Reorganized:**
- Documentation → `docs/` subdirectories:
  - `docs/api/` - API specs
  - `docs/architecture/` - System design
  - `docs/configuration/` - Setup guides
  - `docs/guides/` - User documentation
  - `docs/installation/` - Installation docs
  - `docs/releases/` - Release notes

- Scripts → `scripts/`:
  - `scripts/manage_models.py` - Model management utility
  - `scripts/configure_env.py` - Environment reconfiguration
  - `scripts/convert_to_gguf.py` - Model conversion (advanced)
  - `scripts/install_amd.sh` - AMD GPU setup

- Tests → `tests/integration/`

**Deleted:**
- `install.py` - Old installer (replaced by orchestrator)

**Moved total:** 42 files to proper locations

---

## 🛠️ Technical Improvements

### Installer Architecture

**Before:**
```
User → install.py → download_model.py → async wizard
```

**After:**
```
User → interactive-cli.py --setup → orchestrator
                                    ↓
                        ┌──────────────────────┐
                        │  Bootstrap LLM       │ (quiet)
                        └──────────────────────┘
                                    ↓
                        ┌──────────────────────┐
                        │  Model Selector      │ (with AI)
                        └──────────────────────┘
                                    ↓
                        ┌──────────────────────┐
                        │  Env Configurator    │ (tool-based)
                        └──────────────────────┘
                                    ↓
                        ┌──────────────────────┐
                        │  Validator           │
                        └──────────────────────┘
```

### Tool-Based Configuration Flow

```
Turn 1:
  LLM: get_missing_keys()
  Tool: {"status": "incomplete", "missing": [...], "count": 3}

Turn 2:
  LLM: "DEBUG is optional. Enable debug mode? (yes/no)"
  User: "no"

Turn 3:
  LLM: set_value("DEBUG", "no")
  Tool: {"success": true, "key": "DEBUG", "value": "false"}

Turn 4:
  LLM: get_missing_keys()
  Tool: {"status": "complete"}
```

---

## 📝 Utility Scripts

### Model Management
```bash
# List available models
python scripts/manage_models.py --list

# Search HuggingFace
python scripts/manage_models.py --search "llama 3.1"

# Install specific model
python scripts/manage_models.py --model qwen3-1.7b-q5
```

### Environment Configuration
```bash
# Reconfigure .env file
python scripts/configure_env.py
```

### Model Conversion (Advanced)
```bash
# Convert safetensors → GGUF
python scripts/convert_to_gguf.py
```

---

## 🐛 Bug Fixes

1. **Context length exceeded error** in setup wizard - Fixed by truncating system prompts to 500 chars
2. **Model selector sys.path** - Fixed to use `parent.parent` for project root
3. **Empty AI responses** - Fixed by removing USE_CASE marker stripping that left blank output
4. **Qwen2-1.5B outdated** - Updated to Qwen3-1.7B with better performance
5. **LLM API errors** - Removed invalid `model` parameter from llama-cpp-python calls
6. **Keyword matching** - Replaced with real conversation loop and AI intent detection

---

## 📖 Documentation

### New Documentation
- `TOOL_BASED_CONFIGURATOR.md` - Architecture and design
- `INSTALLER_ISSUES.md` - Analysis of problems before fixes
- `INSTALLATION_FILES_OVERVIEW.md` - File structure overview
- `FUNCTIONALITY_COMPARISON.md` - Old vs new approach
- `FILE_STRUCTURE_AFTER_RENAME.md` - Post-cleanup reference

### Updated Documentation
- `docs/installation/INSTALL.md` - Updated for new installer
- `docs/installation/QUICKSTART.md` - New quick start guide

---

## 🔄 Migration Notes

### From v1.1.2-beta

**No breaking changes.** The new installer is a complete replacement for the old `install.py`:

**Old way:**
```bash
python install.py  # Deprecated
```

**New way:**
```bash
python app/interactive-cli.py --setup  # Recommended
```

**Existing installations:** No action needed. Your current `.env` and `config/llm_config.json` continue to work.

**Reconfiguring:** Run the setup wizard again to use the new AI-powered configuration:
```bash
python app/interactive-cli.py --setup
```

---

## 🎯 Use Cases Supported

The new installer adapts to your needs:

1. **Local AI only** - Fully private, no internet required
2. **Cloud AI** - OpenAI, Anthropic, Google, OpenRouter
3. **Local + Cloud** - Use both (local for privacy, cloud for quality)
4. **GitHub integration** - Code workflows with OpenCode
5. **Just trying it out** - Minimal setup to explore

---

## 🚀 Performance

**Installation speed:**
- Model download: ~2-5 min (1.7B model, ~1.2GB)
- Configuration: ~30 sec - 2 min (depending on user choices)
- Total: ~3-7 min for complete setup

**Resource usage:**
- Bootstrap LLM: ~2GB RAM for 1.7B model
- Installer agents: Minimal overhead
- Clean shutdown: Automatic LLM cleanup

---

## 🔮 What's Next

### Planned for v1.1.4
- Configuration validator agent
- Test runner agent to verify setup
- Health check dashboard
- One-click Claude Desktop integration

### Under Development
- Model performance benchmarking
- Custom model training workflow
- Multi-model orchestration

---

## 🙏 Credits

**Core Contributors:**
- Smart installer architecture design
- Tool-based configuration system
- Environment variable documentation
- Directory reorganization

**Testing:**
- Beta testers on `wip_smart_installer` branch
- LMStudio integration testing

---

## 📦 Files Changed

**Summary:**
- **66 files changed**
- **5,346 insertions**
- **1,463 deletions**

**New files:** 21
**Modified files:** 19
**Moved/renamed files:** 42
**Deleted files:** 1

**Key additions:**
- `app/installer/` - Complete installer system (6 files)
- `config/env_variables.json` - 611 lines of documentation
- `config/model_catalog.json` - Curated model library
- `scripts/manage_models.py` - Model management utility
- `demo_tool_based_config.py` - Standalone demo

---

## 📥 Installation

### Fresh Install
```bash
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant
git checkout v1.1.3-beta
python app/interactive-cli.py --setup
```

### Upgrade from v1.1.2-beta
```bash
git pull origin main
git checkout v1.1.3-beta
python app/interactive-cli.py --setup  # Optional: reconfigure with AI
```

---

## 🐞 Known Issues

1. **LMStudio auth** - Requires `LMSTUDIO_API_KEY` environment variable if auth is enabled
2. **Small model limitations** - 1.7B models may struggle with complex free-text questions (use numbered menu options)
3. **Tool calling format** - Currently uses text parsing, not OpenAI function calling spec

**Workarounds documented in:** `TOOL_BASED_CONFIGURATOR.md`

---

## 📞 Support

**Issues:** https://github.com/yourusername/MoJoAssistant/issues
**Discussions:** https://github.com/yourusername/MoJoAssistant/discussions
**Docs:** `docs/` directory

---

## ⚖️ License

MIT License - See LICENSE file for details

---

**Thank you for testing MoJoAssistant v1.1.3-beta!** 🎉

Your feedback helps make the smart installer even better. Please report any issues or suggestions.
