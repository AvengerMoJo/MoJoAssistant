# Installation & Setup Files - Complete Overview

## Current State (Messy)

### 📦 ROOT LEVEL

| File | Purpose | Status |
|------|---------|--------|
| `install.py` | OLD installer - CPU-only setup, downloads models | ❓ Still used? |
| `demo_model_selector.py` | TEST/DEMO - model selection agent showcase | 🧪 Demo only |
| `demo_env_configurator.py` | TEST/DEMO - env config agent showcase | 🧪 Demo only |
| `app_factory.py` | FastAPI app factory | ✅ Used by MCP server |
| `unified_mcp_server.py` | MCP server entry point | ✅ Used for MCP |

### 📁 scripts/

| File | Purpose | Status |
|------|---------|--------|
| `scripts/install_mojo.py` | Alternative installer with venv setup | ❓ Duplicate of install.py? |
| `scripts/download_model.py` | Standalone model downloader | ❓ Duplicate of agent? |
| `scripts/mcp_stdio_entrypoint.py` | MCP STDIO wrapper | ✅ Used by MCP |

### 🏗️ app/installer/ (NEW Smart Installer)

| File | Purpose | Status |
|------|---------|--------|
| `app/installer/orchestrator.py` | Main installer coordinator | ✅ NEW system |
| `app/installer/bootstrap_llm.py` | Quiet LLM startup for agents | ✅ NEW system |
| `app/installer/agents/base_agent.py` | Base class for setup agents | ✅ NEW system |
| `app/installer/agents/model_selector.py` | Model selection agent | ✅ NEW system |
| `app/installer/agents/env_configurator.py` | Environment config agent | ✅ NEW system |

### 🎯 Entry Points

| Command | What It Does | Implemented |
|---------|--------------|-------------|
| `python install.py` | OLD installer | ✅ Works (old way) |
| `python app/interactive-cli.py --setup` | NEW smart installer | ✅ Works (new way) |
| `python demo_model_selector.py` | Test model selector agent | ✅ Works (demo) |
| `python demo_env_configurator.py` | Test env config agent | ✅ Works (demo) |
| `python scripts/install_mojo.py` | Alternative installer | ❓ Unknown |

---

## 🎯 Three Clean Options

### Option A: Keep NEW System Only (Recommended)

**DELETE:**
- `install.py` (old installer)
- `scripts/install_mojo.py` (duplicate)
- `scripts/download_model.py` (duplicate)
- `demo_model_selector.py` (move to scripts)
- `demo_env_configurator.py` (move to scripts)

**KEEP:**
- `app/installer/` (new smart installer)
- `app/interactive-cli.py --setup` (main entry point)

**CREATE:**
- `scripts/manage_models.py` (renamed from demo_model_selector.py)
- `scripts/configure_env.py` (renamed from demo_env_configurator.py)

**Result:**
```
One installer: python app/interactive-cli.py --setup
Utilities in scripts/: manage_models.py, configure_env.py
```

**User Instructions:**
```bash
# Install
python app/interactive-cli.py --setup

# Change model later
python scripts/manage_models.py --list
python scripts/manage_models.py --search "llama 3"

# Reconfigure environment later
python scripts/configure_env.py
```

---

### Option B: Keep OLD and NEW (Support Both)

**KEEP EVERYTHING, but organize:**

**Root:**
- `install.py` → Rename to `install_legacy.py`

**scripts/:**
- `install.py` → NEW simple wrapper that calls orchestrator
- `manage_models.py` → Moved from demo_model_selector.py
- `configure_env.py` → Moved from demo_env_configurator.py
- Keep `install_mojo.py` for advanced users

**Result:**
```
scripts/install.py          # NEW recommended installer
scripts/install_legacy.py   # OLD installer (fallback)
scripts/install_mojo.py     # Alternative with venv control
scripts/manage_models.py    # Model management utility
scripts/configure_env.py    # Env configuration utility
```

**User Instructions:**
```bash
# Install (recommended)
python scripts/install.py

# Install (old way)
python scripts/install_legacy.py

# Install (with venv control)
python scripts/install_mojo.py --python python3.11
```

---

### Option C: Simplify to Bare Minimum

**DELETE:**
- `install.py`
- `scripts/install_mojo.py`
- `scripts/download_model.py`
- `demo_*.py` files

**KEEP ONLY:**
- `app/interactive-cli.py --setup` (single entry point)
- `app/installer/` (backend)

**CREATE:**
- `scripts/manage_models.py` (for post-install model changes)

**Result:**
```
One command for everything: python app/interactive-cli.py --setup
One utility: scripts/manage_models.py (optional)
```

**User Instructions:**
```bash
# Install
python app/interactive-cli.py --setup

# Everything else happens in setup
# To change models after install:
python scripts/manage_models.py --list
```

---

## 📊 Comparison

| Aspect | Option A | Option B | Option C |
|--------|----------|----------|----------|
| **Simplicity** | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Backwards Compat** | ❌ | ✅ | ❌ |
| **User Confusion** | Low | Medium | Lowest |
| **Maintenance** | Easy | Hard | Easiest |
| **Flexibility** | Good | Best | Good |
| **Files to Change** | 7 files | 5 files | 6 files |

---

## My Recommendation

**Option C** - Simplify to bare minimum:

**Why?**
1. **One way to install** - no confusion
2. **Cleanest codebase** - less maintenance
3. **Modern approach** - everything in one smart installer
4. **User-friendly** - one command does everything

**Users get:**
- `python app/interactive-cli.py --setup` (installs everything)
- `scripts/manage_models.py` (optional utility for later)
- No confusion about which installer to use

**What do you think?** Pick Option A, B, or C and I'll execute it cleanly.
