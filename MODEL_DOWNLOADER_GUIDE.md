# Model Downloader & Converter

## Overview

The `download_model.py` script handles downloading and converting the Qwen3 1.7B model to GGUF format for use with llama-cpp-python.

## Features

1. **Smart Detection**: Automatically detects if the model already exists
   - If GGUF exists: skips download and conversion
   - If safetensors exists: skips download, proceeds to conversion
   - If model not found: downloads from HuggingFace

2. **Automatic Conversion**: Converts safetensors to GGUF format using llama.cpp
   - Uses Q5_K_M quantization (balanced quality/speed)
   - Preserves tokenizer files
   - Outputs to `~/.cache/mojoassistant/models/`

3. **Auto-Configuration**: Updates `config/llm_config.json` with:
   - New model path
   - Default interface set to `qwen3-1.7b`
   - Model description

## Requirements

### Prerequisites

1. **Python 3.9+**
   ```bash
   python --version  # Should be 3.9 or higher
   ```

2. **HuggingFace Hub**
   ```bash
   pip install huggingface_hub
   ```

3. **llama.cpp** (for conversion)
   ```bash
   cd ~
   git clone https://github.com/ggerganov/llama.cpp
   cd llama.cpp
   git lfs install
   make
   ```

4. **Build Tools** (for llama.cpp)
   - On Linux: `build-essential`, `cmake`, `git`
   - On Mac: `xcode-select --install`
   - On Windows: Visual Studio Build Tools

### Alternative: Pre-converted Model

If you don't want to convert the model, you can:
1. Download the pre-converted GGUF from HuggingFace
2. Place it in `~/.cache/mojoassistant/models/`
3. Run the script to update config (it will skip conversion)

## Usage

### First-Time Setup

```bash
# 1. Clone llama.cpp
cd ~
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
git lfs install
make

# 2. Run the downloader/convertor
cd /path/to/MoJoAssistant
python download_model.py
```

### Subsequent Runs

The script is smart enough to skip unnecessary steps:

```bash
python download_model.py
```

**Output will show:**
- If GGUF already exists: "Model is ready to use! 🎉"
- If safetensors exists: "Download Complete, Ready for Conversion 🎉"
- If model not found: "Download Complete! 🎉" (then run again after installing llama.cpp)

## How It Works

### Step 1: Check for Existing Model
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
  Cache: ~/.cache/huggingface/hub
  This may take several minutes depending on your connection...
  ✓ Model downloaded successfully
```

### Step 3: Convert to GGUF
```
[3/4] Converting model to GGUF format
  llama.cpp found at: ~/Dev/Personal/llama.cpp
  Found 2 safetensors file(s)
  Output file: ~/.cache/mojoassistant/models/Qwen3-1.7b-q5_k_m.gguf
  Running conversion...
  ✓ Model converted to GGUF: ~/.cache/mojoassistant/models/Qwen3-1.7b-q5_k_m.gguf (1.2 GB)
```

### Step 4: Update Configuration
```
[4/4] Updating llm_config.json
  ✓ Updated: config/llm_config.json
  Default interface: qwen3-1.7b
  Model path: ~/.cache/mojoassistant/models/Qwen3-1.7b-q5_k_m.gguf
```

## Configuration

### llama.cpp Directory Locations

The script looks for llama.cpp in these locations (in order):

1. `~/Dev/Personal/llama.cpp`
2. `~/Dev/llama.cpp`
3. `~/llama.cpp`
4. Current directory (if you're in llama.cpp)

To add your custom location, edit `download_model.py`:

```python
llama_cpp_dirs = [
    Path.home() / "Dev" / "Personal" / "llama.cpp",
    Path.home() / "Dev" / "llama.cpp",
    Path.home() / "llama.cpp",
    Path.cwd(),
]
```

### Model Output Location

The GGUF model is saved to:
- **Path**: `~/.cache/mojoassistant/models/Qwen3-1.7b-q5_k_m.gguf`
- **Size**: ~1.2 GB (Q5_K_M quantization)
- **Format**: GGUF (GPT-Generated Unified Format)

## Customization

### Change Quantization Level

Edit the `convert_to_gguf()` function:

```python
# Current (Q5_K_M - balanced)
cmd = [
    "python",
    str(llama_cpp_dir / "convert-hf-to-gguf.py"),
    str(newest_snapshot),
    "--outfile", str(output_file),
    "--outtype", "q5_k_m",  # Change this!
]

# Options:
# - q4_k_m: ~1.0 GB, faster, slightly lower quality
# - q5_k_m: ~1.2 GB, balanced (default)
# - q6_k: ~1.4 GB, better quality, slower
# - f16: ~2.3 GB, full precision, slowest
```

### Change Model Parameters

```python
# Add additional llama.cpp options
cmd = [
    "python",
    str(llama_cpp_dir / "convert-hf-to-gguf.py"),
    str(newest_snapshot),
    "--outfile", str(output_file),
    "--outtype", "q5_k_m",
    "--ctx-size", "2048",      # Context size
    "--vocab-type", "normal",  # Vocabulary type
    "--chunks", "32",          # Split into 32 chunks
]
```

## Troubleshooting

### llama.cpp Not Found

**Error**: `✗ llama.cpp not found!`

**Solution**:
```bash
# Install llama.cpp
cd ~
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
git lfs install
make
```

### Make Fails

**Error**: `make: *** No targets specified and no Makefile found.`

**Solution**:
```bash
# Make sure you're in the llama.cpp directory
cd ~/llama.cpp

# Clone submodules (required for some features)
git submodule update --init --recursive

# Build
make
```

### Model Download Slow

**Problem**: Download takes a long time

**Solution**:
1. Use a faster internet connection
2. Download using HuggingFace CLI directly:
   ```bash
   huggingface-cli download Qwen/Qwen3-1.7B --local-dir ~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B --local-dir-use-symlinks False
   ```
3. Resume interrupted downloads

### Conversion Fails

**Error**: `✗ Conversion failed`

**Solutions**:
1. Check llama.cpp is built:
   ```bash
   cd ~/llama.cpp
   python -m llama_cpp.server --help
   ```
2. Check Python version:
   ```bash
   python --version  # Should be 3.9+
   ```
3. Check available memory (conversion needs ~2GB RAM)

### Config File Not Updated

**Problem**: `config/llm_config.json` doesn't have the new model

**Solution**:
```bash
# Manually edit the config file
nano config/llm_config.json

# Or run the script again
python download_model.py
```

## After Conversion

### Run Setup Wizard

```bash
python app/interactive-cli.py --setup
```

The setup wizard will now use `qwen3-1.7b` as the default interface!

### Run CLI Directly

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

## Advanced Usage

### Download Only (No Conversion)

If you just want to download and manually convert later:

```bash
# The script will skip download if model exists
python download_model.py
```

### Force Re-download

```bash
# Remove existing model
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B

# Run script again
python download_model.py
```

### Convert After Download

1. Run script to download:
   ```bash
   python download_model.py
   ```

2. Install llama.cpp and build
3. Run script again:
   ```bash
   python download_model.py
   ```

The script will skip download (model exists) and proceed to conversion.

## Summary

The `download_model.py` script provides a one-stop solution for:
- ✅ Downloading Qwen3 1.7B from HuggingFace
- ✅ Converting to GGUF format using llama.cpp
- ✅ Updating configuration automatically
- ✅ Smart detection to avoid redundant operations
- ✅ Clear progress feedback and error messages

Just install llama.cpp and run the script!

## Related Files

- **download_model.py**: Main downloader and converter script
- **config/llm_config.json**: LLM configuration (auto-updated)
- **llama.cpp**: Model conversion tool (install separately)
- **app/llm/local_llm_interface.py**: Uses GGUF models

## Support

If you encounter issues:
1. Check the error messages carefully
2. Ensure all prerequisites are installed
3. Verify llama.cpp is properly built
4. Check Python version and dependencies
5. Review the troubleshooting section above
