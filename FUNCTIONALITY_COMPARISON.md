# Functionality Comparison - Old vs New

## What We're Removing vs Keeping

### scripts/download_model.py (OLD)

**What it does:**
1. Downloads NON-GGUF models from HuggingFace (e.g., safetensors format)
2. Downloads llama.cpp binary
3. **CONVERTS** models to GGUF format
4. Updates llm_config.json

**Key feature:** Model conversion (safetensors → GGUF)

---

### app/installer/agents/model_selector.py (NEW)

**What it does:**
1. Downloads **pre-quantized GGUF** models directly from HuggingFace
2. No conversion needed (GGUF files ready to use)
3. Supports:
   - Default model from catalog
   - Search HuggingFace for any GGUF model
   - Resume interrupted downloads
   - HuggingFace mirror support (China)
4. Updates llm_config.json

**Key feature:** Direct GGUF download, no conversion

---

## What We'd Lose by Deleting scripts/download_model.py

❌ **Model conversion capability**
- Can't convert safetensors/pytorch → GGUF
- Users must download pre-quantized GGUF files

✅ **But we gain:**
- Faster (no conversion step)
- Simpler (one-step download)
- More reliable (no llama.cpp binary needed)

---

## Recommendation

**Option 1: DELETE scripts/download_model.py**
- Modern approach: use pre-quantized GGUF models
- 99% of users don't need conversion
- Simplifies codebase

**Option 2: KEEP scripts/download_model.py as advanced utility**
- For users who want to convert custom models
- Rename to `scripts/convert_to_gguf.py`
- Document as "advanced users only"

---

## Other Files

### install.py (OLD installer)
- Complete installer with venv setup
- Downloads models using old download_model.py
- **Can safely delete** - functionality now in `app/installer/orchestrator.py`

### scripts/install_mojo.py (Alternative installer)
- Similar to install.py but with more venv control
- **Can safely delete** - functionality in orchestrator

---

## My Recommendation

**Keep:** `scripts/download_model.py` → Rename to `scripts/convert_to_gguf.py`
- For advanced users who want to convert custom models
- Not used by main installer
- Optional utility

**Delete:**
- `install.py` (replaced by orchestrator)
- `scripts/install_mojo.py` (replaced by orchestrator)
- `demo_env_configurator.py` (functionality in orchestrator)

**Result:**
```
Main installer:  python app/interactive-cli.py --setup
Model utility:   python scripts/manage_models.py
Convert utility: python scripts/convert_to_gguf.py (advanced)
```

**What do you think?** Delete all or keep convert_to_gguf.py as advanced utility?
