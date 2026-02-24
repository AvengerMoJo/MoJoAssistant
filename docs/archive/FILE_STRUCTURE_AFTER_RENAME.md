# File Structure After Rename (Pre-Cleanup)

## ✅ What We Have Now

### 📦 Main Installer
```
python app/interactive-cli.py --setup
```
- **Location:** `app/installer/orchestrator.py`
- **Uses:** Smart installer with AI agents
- **Status:** ✅ Ready to test

### 🛠️ Utility Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/manage_models.py` | Manage/download models | ✅ Renamed (was demo_model_selector.py) |
| `scripts/configure_env.py` | Configure .env file | ✅ Renamed (was demo_env_configurator.py) |
| `scripts/convert_to_gguf.py` | Convert models to GGUF | ✅ Renamed (was download_model.py) |
| `scripts/mcp_stdio_entrypoint.py` | MCP STDIO wrapper | ✅ Keep (needed) |

### 🗑️ To Be Deleted After Testing

| File | Reason |
|------|--------|
| `scripts/install_mojo.py` | Old installer (replaced by orchestrator) |

### 📝 Documentation Files (New)

| File | Purpose |
|------|---------|
| `INSTALLER_ISSUES.md` | Analysis of problems before fixes |
| `INSTALLATION_FILES_OVERVIEW.md` | Bird's eye view & options |
| `FUNCTIONALITY_COMPARISON.md` | What each file does |
| `FILE_STRUCTURE_AFTER_RENAME.md` | This file |

---

## 🧪 Testing Plan

### 1. Test Main Installer
```bash
# Fresh install (no model)
python app/interactive-cli.py --setup

# Should show:
# - Model selection (default or search)
# - AI-guided env configuration
# - Validation
```

### 2. Test Model Management
```bash
# List available models
python scripts/manage_models.py --list

# Search for model
python scripts/manage_models.py --search "llama 3.1"

# Install specific model
python scripts/manage_models.py --model qwen3-1.7b-q5
```

### 3. Test Environment Configuration
```bash
# Reconfigure environment
python scripts/configure_env.py
```

### 4. Test Model Conversion (Advanced)
```bash
# Convert a model to GGUF
python scripts/convert_to_gguf.py
```

---

## 🗑️ Major Cleanup (After Testing Passes)

**Files to delete:**
1. `scripts/install_mojo.py` - Old installer
2. `INSTALLER_ISSUES.md` - Analysis doc (archive?)
3. `INSTALLATION_FILES_OVERVIEW.md` - Planning doc (archive?)
4. `FUNCTIONALITY_COMPARISON.md` - Planning doc (archive?)

**What to keep:**
- `app/installer/` - New installer system
- `scripts/manage_models.py` - Utility
- `scripts/configure_env.py` - Utility
- `scripts/convert_to_gguf.py` - Advanced utility
- `scripts/mcp_stdio_entrypoint.py` - MCP needed
- `FILE_STRUCTURE_AFTER_RENAME.md` - Final reference

---

## 📋 Summary

✅ **Renamed correctly:**
- Model management: `scripts/manage_models.py`
- Env configuration: `scripts/configure_env.py`
- Model conversion: `scripts/convert_to_gguf.py`

✅ **Main installer:**
- `python app/interactive-cli.py --setup`

⏳ **Ready for testing**

🗑️ **Cleanup after test:** Delete `scripts/install_mojo.py`
