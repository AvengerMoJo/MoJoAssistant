# MoJoAssistant Dockerfile
# This creates a Docker container for MoJoAssistant with all dependencies

FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download and install Ollama (optional, for local models)
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy project
COPY . .

# Create necessary directories
RUN mkdir -p .memory/archival_memory .memory/knowledge_base .memory/embeddings

# Set up environment file
RUN if [ ! -f .env ]; then cp .env.example .env; fi

# Create non-root user for security
RUN useradd -m -u 1000 mojo && chown -R mojo:mojo /app
USER mojo

# Expose port for MCP server
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/system/health || exit 1

# Default command
CMD ["python", "start_mcp_service.py"]