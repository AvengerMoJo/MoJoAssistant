#!/bin/bash
# MoJoAssistant Interactive CLI Launcher
# Auto-generated script for easy access to interactive CLI

echo "Starting MoJoAssistant Interactive CLI..."
echo ""

# Activate virtual environment
# If venv exists, activate it, otherwise use system Python
if [ -d "venv" ]; then
    source venv/bin/activate
    PYTHON_CMD=$(which python)
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    PYTHON_CMD=$(which python)
else
    PYTHON_CMD=python3
    echo "No venv found, using system Python"
fi

echo "Using Python: $PYTHON_CMD"
echo ""

# Run interactive CLI with setup mode
$PYTHON_CMD app/interactive-cli.py --setup
