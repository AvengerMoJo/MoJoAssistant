#!/bin/bash
# Start GLM-4-Voice vLLM server on ROCm Docker
# Usage: ./scripts/run_vllm_glm4voice.sh
# Docs: docs/vllm-rocm-cpu-bug.md

set -e

CONTAINER_NAME="vllm-glm-voice"
MODEL="${GLM_MODEL:-zai-org/glm-4-voice-9b}"
PORT="${GLM_PORT:-8888}"
DTYPE="${GLM_DTYPE:-bfloat16}"
IMAGE="vllm/vllm-openai-rocm:latest"
GPU_MEM="${GLM_GPU_MEM:-0.50}"
MAX_LEN="${GLM_MAX_LEN:-4096}"

docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "Starting vLLM: model=$MODEL port=$PORT dtype=$DTYPE gpu_mem=$GPU_MEM max_len=$MAX_LEN"
docker run -d --name "$CONTAINER_NAME" \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video --group-add=render \
  -p "$PORT:$PORT" \
  -e VLLM_COMPILATION_MODE=0 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  "$IMAGE" \
  "$MODEL" \
    --dtype "$DTYPE" \
    --port "$PORT" \
    --trust-remote-code \
    --gpu-memory-utilization "$GPU_MEM" \
    --max-model-len "$MAX_LEN" \
    --enforce-eager

echo ""
echo "Container started. docker logs -f $CONTAINER_NAME"
echo "Test: curl http://localhost:$PORT/v1/completions ..."
echo "Stop: docker stop $CONTAINER_NAME"
