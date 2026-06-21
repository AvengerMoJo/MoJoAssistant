# vLLM ROCm — Status & Compatibility Check

## Current Status (2026-06-16)

**Not usable as primary inference server.** LMStudio remains the primary local LLM backend.

### Why vLLM is parked

- Qwen 3.6 MoE GGUF files use architecture `qwen35moe`, which transformers cannot parse
- vLLM v0.23.0 triggers `ValueError: GGUF model with architecture qwen35moe is not supported yet` on every load attempt
- Safetensors workaround works but defeats the purpose — 70GB download per model vs reusing 338GB of existing GGUF files
- MTP (Multi-Token Prediction) only works with safetensors, not GGUF

### What vLLM needs to become useful

1. **GGUF `qwen35moe` architecture support** in transformers/huggingface
2. **GGUF + MTP speculative decoding** end-to-end
3. Or: built-in Qwen 3.6 native quantization support (AWQ/GPTQ) matching LMStudio quality

## Monthly Compatibility Check

Run this script on the 1st of each month to see if vLLM has caught up:

```bash
# 1. Check for new vLLM releases
docker run --rm vllm/vllm-openai-rocm:latest --version 2>&1

# 2. Check if qwen35moe GGUF is now supported
docker run --rm --device=/dev/kfd --device=/dev/dri --group-add=video --group-add=render \
  -v ~/.lmstudio/models:/models/lmstudio:ro \
  vllm/vllm-openai-rocm:latest \
  /models/lmstudio/lmstudio-community/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf \
  --max-model-len 4096 --gpu-memory-utilization 0.10

# 3. If it loads, test MTP
docker run --rm --device=/dev/kfd --device=/dev/dri --group-add=video --group-add=render \
  -v ~/.lmstudio/models:/models/lmstudio:ro \
  vllm/vllm-openai-rocm:latest \
  /models/lmstudio/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf \
  --max-model-len 4096 --gpu-memory-utilization 0.10 \
  --speculative-config '{"method":"mtp","num_speculative_tokens":1}'
```

**If step 2 passes** → vLLM is ready to replace LMStudio for Qwen 3.6 workloads.
**If step 3 also passes** → full MTP speculative decoding on GGUF, superior to LMStudio.

## Infrastructure Ready

When vLLM becomes viable, the infrastructure is already in place:

- **`docker/docker-compose.yml`** — `vllm-rocm` service with shared volume mounts
- **`scripts/vllm.sh`** — utility script for starting any model with sane defaults
- **Shared caches** — `~/.lmstudio/models` (GGUF) + `~/.cache/huggingface` (safetensors)

### Starting vLLM (when ready)

```bash
# Single model
./scripts/vllm.sh <model-id-or-gguf-path> --port 8081 --gpu-mem 0.50

# Multiple models (split GPU)
./scripts/vllm.sh qwen/qwen3.6-35b-a3b --port 8081 --gpu-mem 0.45
./scripts/vllm.sh google/gemma-4-26b-a4b --port 8082 --gpu-mem 0.45
```

## Reference

- vLLM GGUF docs: https://docs.vllm.ai/en/stable/features/quantization/gguf/
- vLLM MTP docs: https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/
- vLLM ROCm images: https://hub.docker.com/r/vllm/vllm-openai-rocm/tags
