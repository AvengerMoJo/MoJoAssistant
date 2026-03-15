# syntax=docker/dockerfile:1
# MoJoAssistant — Production / Installation Image
#
# Lean runtime image. Local model inference is handled externally (LMStudio).
# Usage:
#   docker build -f docker/Dockerfile -t mojoassistant .
#   docker run -p 8000:8000 --env-file .env -v ~/.memory:/home/mojo/.memory mojoassistant

FROM python:3.12-slim

# ── System deps ──────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN useradd -m -u 1000 -s /bin/bash mojo

# ── Python deps ──────────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements-runtime.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-runtime.txt

# ── App source ────────────────────────────────────────────────────────────────
COPY --chown=mojo:mojo . .

# ── Submodule packages ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir submodules/dreaming-memory-pipeline/

# ── Pre-download embedding model ──────────────────────────────────────────────
# Bakes the model into the image so first startup doesn't hit the network.
# Update this if you change the default model in config/embedding_config.json.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# ── Runtime dirs ─────────────────────────────────────────────────────────────
RUN mkdir -p /home/mojo/.memory/config /home/mojo/.memory/roles \
             /home/mojo/.memory/task_sessions /home/mojo/.memory/events.json \
    && chown -R mojo:mojo /home/mojo/.memory

# ── Default config (if not provided via volume) ───────────────────────────────
RUN if [ -f config/llm_config.json.example ]; then \
        cp config/llm_config.json.example config/llm_config.json; \
    fi

USER mojo
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MEMORY_PATH=/home/mojo/.memory

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["python", "unified_mcp_server.py", "--mode", "http", "--port", "8000"]
