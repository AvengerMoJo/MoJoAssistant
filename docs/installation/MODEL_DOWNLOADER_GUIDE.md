# Simplified Model Downloader Guide

## Overview

The `download_model.py` script is now **simplified** to use pre-compiled binaries from GitHub releases instead of building from scratch.

## Quick Start

### macOS (Easiest)

```bash
# Install via Homebrew
brew install llama.cpp

# Run downloader
python download_model.py
```

Or with Homebrew Cask:
```bash
brew install --cask llama
python download_model.py
```

### Linux/Windows

```bash
# Install llama-cpp-python
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121

# Run downloader
python download_model.py
```

## How It Works

### Step 0: Check for llama.cpp
```
[0/4] Checking for llama.cpp binary
  ✓ Found Homebrew installation: /opt/homebrew/bin/llama
```

### Step 1: Check for Model
```
[1/4] Checking for existing model...
  Model found at: ~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B
  ⚠️  Safetensors model found, but no GGUF file
  Will convert the model...
```

### Step 2: Download (if needed)
```
[2/4] Downloading Qwen3 1.7B model
  Model: Qwen/Qwen3-1.7B
  ✓ Model downloaded successfully
```

### Step 3: Convert to GGUF
```
[3/4] Converting model to GGUF format
  Output file: ~/.cache/mojoassistant/models/Qwen3-1.7b-q5_k_m.gguf
  Using: /opt/homebrew/bin/llama
  ✓ Model converted to GGUF
```

### Step 4: Update Configuration
```
[4/4] Updating llm_config.json
  ✓ Updated: config/llm_config.json
  Default interface: qwen3-1.7b
```

## Installation Options

### Option 1: Homebrew (macOS) - Recommended

```bash
brew install llama.cpp

# Or with Cask (easier)
brew install --cask llama
```

**Pros:**
- ✅ One command
- ✅ Automatic updates
- ✅ Handles dependencies
- ✅ Pre-compiled for your platform

### Option 2: Pre-compiled Binary

Download manually from:
```
https://github.com/ggml-org/llama.cpp/releases
```

**Pros:**
- ✅ No build required
- ✅ Simple download
- ✅ Works on any OS

**Cons:**
- ❌ Manual download
- ❌ Manual extraction

### Option 3: Build from Source (Not Recommended)

```bash
cd ~/llama.cpp
make
```

**Pros:**
- ✅ Latest features
- ✅ Custom compilation

**Cons:**
- ❌ Slow (30-60 minutes)
- ❌ Requires build tools
- ❌ Uses more RAM

## Platform-Specific Commands

### macOS

**Apple Silicon (M1/M2/M3):**
```bash
brew install llama.cpp
# or
brew install --cask llama
```

**Intel Mac:**
```bash
brew install llama.cpp
# or
brew install --cask llama
```

### Linux

**Ubuntu/Debian:**
```bash
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

**Fedora/RHEL:**
```bash
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

### Windows

**Standard Python:**
```bash
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

**Using WSL (Windows Subsystem for Linux):**
```bash
# Install in WSL
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

## Troubleshooting

### llama.cpp Not Found

**Error**: `✗ llama.cpp binary not found!`

**Solution (macOS):**
```bash
brew install llama.cpp
```

**Solution (Linux/Windows):**
```bash
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

### Homebrew Not Installed

**Error**: Homebrew installation failed

**Solution:**
```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install llama.cpp
brew install llama.cpp
```

### Model Download Slow

**Problem**: Download takes a long time

**Solutions:**
1. Use a faster internet connection
2. Download using HuggingFace CLI directly:
   ```bash
   huggingface-cli download Qwen/Qwen3-1.7B --local-dir ~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B --local-dir-use-symlinks False
   ```

### Conversion Fails

**Error**: `✗ Conversion failed`

**Solutions:**
1. Check llama.cpp is installed:
   ```bash
   # macOS
   which llama
   # or
   which llama-cli

   # Linux
   which llama
   # or
   which llama-cli
   ```

2. Check permissions:
   ```bash
   # macOS
   ls -la /opt/homebrew/bin/llama-cli

   # Linux
   ls -la /usr/local/bin/llama-cli
   ```

3. Reinstall:
   ```bash
   # macOS
   brew reinstall llama.cpp

   # Linux
   python -m pip uninstall llama-cpp-python
   python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
   ```

## After Conversion

### Run Setup Wizard

```bash
python app/interactive-cli.py --setup
```

The setup wizard will now use `qwen3-1.7b` as the default interface!

### Run CLI

```bash
python app/interactive-cli.py
```

### Check Available Interfaces

```bash
python -c "
from app.llm.llm_interface import LLMInterface
llm = LLMInterface(config_file='config/llm_config.json')
print('Available:', llm.get_available_interfaces())
print('Active:', llm.active_interface_name)
"
```

## Comparison: Homebrew vs Build from Source

| Aspect | Homebrew | Build from Source |
|--------|----------|-------------------|
| Time | 30 seconds | 30-60 minutes |
| RAM | 500 MB | 4-8 GB |
| Complexity | Simple | Complex |
| Dependencies | Auto-handled | Manual |
| Ease | Easy | Hard |

## Summary

The simplified approach uses **pre-compiled binaries**:

✅ **macOS**: `brew install llama.cpp` (30 seconds)
✅ **Linux/Windows**: `pip install llama-cpp-python` (2-5 minutes)
✅ **No build tools needed**
✅ **Automatic platform detection**
✅ **Fast and reliable**

**Recommendation**: Use Homebrew on macOS for the easiest experience!

## Files

- **download_model.py**: Main downloader script
- **MODEL_DOWNLOADER_GUIDE.md**: This guide
- **config/llm_config.json**: Auto-updated with new model

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify llama.cpp is installed correctly
3. Check your OS and Python version
4. Review error messages carefully
