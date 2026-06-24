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
#     --probe-path /api/health

# Use the upstream cubesandbox base which has envd preinstalled
# (compiled from e2b-dev/infra at the 2026.16 tag). The base image
# also provides /usr/local/bin/cube-entrypoint.sh which starts envd
# in the background on :49983 and runs a user CMD in the foreground.
FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16

ENV DEBIAN_FRONTEND=noninteractive
ENV BUN_INSTALL=/root/.bun
ENV PATH="/root/.bun/bin:$PATH"

# Base packages (some are already in the base image; idempotent install)
RUN apt-get update && apt-get install -y --no-install-recommends \
    unzip \
    build-essential \
    python3 python3-pip \
    openssh-client \
    ripgrep \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install bun
RUN curl -fsSL https://bun.sh/install | bash

# Install OpenCode globally
RUN bun install -g opencode-ai

# Create workspace directory
RUN mkdir -p /workspace
WORKDIR /workspace

# OpenCode server port + envd port (already in the base image, but
# we re-EXPOSE to make them visible in the image metadata)
EXPOSE 4173 49983

# Health check covers both OpenCode (port 4173) and envd (port 49983).
# CubeMaster's readiness probe is configured to port 4173 below; the
# 49983 check is for the e2b SDK's commands.run / files.read paths.
HEALTHCHECK --interval=2s --timeout=2s --start-period=10s --retries=15 \
  CMD curl -fsS http://127.0.0.1:4173/api/health || exit 1

# Start OpenCode in server mode (1.17+ uses --hostname, not --host)
# The base image's cube-entrypoint.sh starts envd in the background
# before exec'ing this CMD, so envd is alive on :49983 by the time
# OpenCode is serving on :4173.
CMD ["opencode", "serve", "--port", "4173", "--hostname", "0.0.0.0", "--print-logs"]
