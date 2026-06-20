# OpenCode Sandbox Image for CubeSandbox
#
# This image is converted by CubeSandbox into a KVM microVM template.
# The template snapshot is taken AFTER OpenCode fully loads — enabling
# hot-start in <60ms for each new coding session.
#
# Build & register:
#   docker build -t my-registry/opencode-sandbox:latest -f docker/opencode-sandbox/Dockerfile .
#   docker push my-registry/opencode-sandbox:latest
#
#   cubemastercli tpl create-from-image \
#     --image my-registry/opencode-sandbox:latest \
#     --writable-layer-size 2G \
#     --expose-port 4173 \
#     --probe 4173 \
#     --probe-path /health

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV BUN_INSTALL=/root/.bun
ENV PATH="/root/.bun/bin:$PATH"

# Base packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates \
    build-essential \
    python3 python3-pip \
    openssh-client \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install bun
RUN curl -fsSL https://bun.sh/install | bash

# Install OpenCode globally
RUN bun install -g opencode

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace

# OpenCode server port
EXPOSE 4173

# Health check endpoint is provided by OpenCode's built-in server
# CubeSandbox probes GET /health during template creation

# Start OpenCode in server mode
CMD ["opencode", "serve", "--port", "4173", "--host", "0.0.0.0"]
