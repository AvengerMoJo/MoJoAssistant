# vLLM ROCm CPU 100% Bug — Root Cause & Fix

## Symptom
vLLM Docker container shows 100% CPU usage continuously after startup, even when idle. `VLLM::EngineCore` subprocess consumes one full core for days.

## Root Cause
vLLM's default `compilation_config.mode` is `VLLM_COMPILE` (mode 3). On ROCm consumer GPUs (Radeon 8060S / gfx1151), this triggers PyTorch Inductor (torch.compile) to compile the model's CUDA graphs. Inductor on ROCm consumer hardware enters an infinite or near-infinite compilation loop — it tries every possible kernel fusion permutation without converging. This is a known issue with PyTorch Inductor + MIOpen on non-MI-series GPUs.

## Fix
Add `--enforce-eager` to vLLM server arguments. This forces eager execution mode, bypassing Inductor compilation entirely. Inference speed is nearly identical because:

- vLLM's PagedAttention and continuous batching are the main optimizers
- Inductor compilation provides marginal gains (~5-15%) on NVIDIA, but doesn't converge on consumer ROCm
- The model still runs on GPU via MIOpen kernels

## Updated Docker Command
```bash
docker run -d --name vllm-glm-voice \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video --group-add=render \
  -p 8888:8888 \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai-rocm:latest \
  serve zai-org/glm-4-voice-9b \
  --dtype bfloat16 \
  --port 8888 \
  --trust-remote-code \
  --gpu-memory-utilization 0.50 \
  --max-model-len 4096 \
  --enforce-eager
```

## Verification
After restart, `docker stats` should show CPU < 5% at idle. `VLLM::EngineCore` no longer spins.
