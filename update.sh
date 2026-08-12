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

# Check if updates are available (unless --force is used)
if [[ "$1" != "--force" ]]; then
    echo "Checking for updates..."
    
    # Run check_updates.py and capture exit code
    python3 "$PROJECT_DIR/check_updates.py" > /dev/null 2>&1
    CHECK_EXIT=$?
    
    # check_updates.py exits with 0 if updates available, 1 if not
    if [[ $CHECK_EXIT -eq 1 ]]; then
        # No updates available
        echo "No updates available. Your project is up to date!"
        echo ""
        echo "To force an update anyway, run: $0 --force"
        exit 0
    elif [[ $CHECK_EXIT -eq 0 ]]; then
        # Updates are available, continue with update
        echo "Updates available! Proceeding with update..."
    fi
fi

# Handle command line arguments
if [[ "$1" == "--dry-run" ]]; then
    echo "Running in DRY-RUN mode..."
    python3 "$PROJECT_DIR/updater.py" --dry-run --project-dir "$PROJECT_DIR"
elif [[ "$1" == "--force" ]]; then
    echo "Forcing update (skipping version check)..."
    python3 "$PROJECT_DIR/updater.py" --project-dir "$PROJECT_DIR"
else
    python3 "$PROJECT_DIR/updater.py" --project-dir "$PROJECT_DIR" "$@"
fi
