#!/bin/bash
# Paredicma Project Updater Wrapper
# This script provides an easy way to update the paredicma project

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed"
    exit 1
fi

# Handle command line arguments
if [[ "$1" == "--dry-run" ]]; then
    echo "Running in DRY-RUN mode..."
    python3 "$PROJECT_DIR/updater.py" --dry-run --project-dir "$PROJECT_DIR"
else
    python3 "$PROJECT_DIR/updater.py" --project-dir "$PROJECT_DIR" "$@"
fi
