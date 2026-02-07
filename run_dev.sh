#!/bin/bash
# Development server with hot reload
# Usage: ./run_dev.sh

echo "Starting development server with hot reload..."
uvicorn app_factory:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --reload-dir ./app \
  --log-level info
