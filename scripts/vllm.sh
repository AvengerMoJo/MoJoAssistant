#!/bin/bash
# vllm.sh — Start a vLLM inference server on ROCm Docker
#
# Usage:
#   ./scripts/vllm.sh <model> [options]
#
# Examples:
#   ./scripts/vllm.sh zai-org/glm-4-voice-9b
#   ./scripts/vllm.sh qwen/qwen3.6-35b-a3b
#   ./scripts/vllm.sh /models/lmstudio/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_S.gguf
#   ./scripts/vllm.sh google/gemma-4-26b-a4b --port 8082 --gpu-mem 0.45
#
# Options (all have defaults):
#   --port <port>              Host port (default: 8888)
#   --gpu-mem <fraction>       GPU memory utilization 0.0-1.0 (default: 0.50)
#   --max-len <tokens>         Max model context length (default: 32768)
#   --dtype <dtype>            bfloat16, float16, auto (default: auto)
#   --name <container-name>    Docker container name (default: auto from model)
#   --extra "<args>"           Extra args passed to vllm serve
#   --detach / -d              Run in background (default: yes)
#   --foreground / -f          Run in foreground (streams logs)
#   --lmstudio-models          Also mount LMStudio GGUF cache (default: yes)
#
# Env vars (override defaults):
#   VLLM_IMAGE     Docker image (default: vllm/vllm-openai-rocm:latest)
#   HF_HOME        HuggingFace cache (default: ~/.cache/huggingface)
#   LMSTUDIO_MODELS  LMStudio model dir (default: ~/.lmstudio/models)

set -e

# ── Defaults ────────────────────────────────────────────────────────────────
IMAGE="${VLLM_IMAGE:-vllm/vllm-openai-rocm:latest}"
HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface}"
LMSTUDIO_DIR="${LMSTUDIO_MODELS:-$HOME/.lmstudio/models}"
PORT=8888
GPU_MEM=0.50
MAX_LEN=32768
DTYPE="auto"
CONTAINER_NAME=""
EXTRA_ARGS=""
DETACH=true
MOUNT_LMSTUDIO=true

# ── Parse args ──────────────────────────────────────────────────────────────
if [ $# -lt 1 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    head -25 "$0" | tail -23
    exit 0
fi

MODEL="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)       PORT="$2"; shift 2 ;;
        --gpu-mem)    GPU_MEM="$2"; shift 2 ;;
        --max-len)    MAX_LEN="$2"; shift 2 ;;
        --dtype)      DTYPE="$2"; shift 2 ;;
        --name)       CONTAINER_NAME="$2"; shift 2 ;;
        --extra)      EXTRA_ARGS="$2"; shift 2 ;;
        --detach|-d)  DETACH=true; shift ;;
        --foreground|-f) DETACH=false; shift ;;
        --no-lmstudio) MOUNT_LMSTUDIO=false; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Auto-derive container name from model
if [ -z "$CONTAINER_NAME" ]; then
    # Strip path and org prefix, keep model identity
    BASENAME=$(basename "$MODEL")
    BASENAME="${BASENAME%.gguf}"
    BASENAME="${BASENAME%.safetensors}"
    CONTAINER_NAME="vllm-$(echo "$BASENAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | head -c 40)"
fi

# ── Build docker command ────────────────────────────────────────────────────
DOCKER_ARGS=(
    --device=/dev/kfd --device=/dev/dri
    --group-add=video --group-add=render
    -p "${PORT}:8000"
    -e VLLM_COMPILATION_MODE=0
    -v "${HF_CACHE}:/root/.cache/huggingface"
)

if [ "$MOUNT_LMSTUDIO" = true ] && [ -d "$LMSTUDIO_DIR" ]; then
    DOCKER_ARGS+=(-v "${LMSTUDIO_DIR}:/models/lmstudio:ro")
fi

if [ "$DETACH" = true ]; then
    DOCKER_ARGS+=(-d)
fi

# Model serve args
SERVE_ARGS=(
    --port 8000
    --trust-remote-code
    --gpu-memory-utilization "$GPU_MEM"
    --max-model-len "$MAX_LEN"
)

if [ "$DTYPE" != "auto" ]; then
    SERVE_ARGS+=(--dtype "$DTYPE")
fi

if [ -n "$EXTRA_ARGS" ]; then
    read -r -a EXTRA_ARRAY <<< "$EXTRA_ARGS"
    SERVE_ARGS+=("${EXTRA_ARRAY[@]}")
fi

# ── Run ─────────────────────────────────────────────────────────────────────
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "Starting vLLM container: $CONTAINER_NAME"
echo "  image:   $IMAGE"
echo "  model:   $MODEL"
echo "  port:    $PORT → 8000"
echo "  gpu_mem: $GPU_MEM"
echo "  max_len: $MAX_LEN"
echo "  dtype:   $DTYPE"
echo ""

if [ "$DETACH" = true ]; then
    docker run "${DOCKER_ARGS[@]}" --name "$CONTAINER_NAME" "$IMAGE" "$MODEL" "${SERVE_ARGS[@]}"
    echo ""
    echo "Container started in background."
    echo "  Logs:  docker logs -f $CONTAINER_NAME"
    echo "  Stop:  docker stop $CONTAINER_NAME"
    echo "  Test:  python3 -c \"import requests; print(requests.get('http://localhost:$PORT/v1/models').json())\""
else
    docker run "${DOCKER_ARGS[@]}" --name "$CONTAINER_NAME" "$IMAGE" "$MODEL" "${SERVE_ARGS[@]}"
fi
