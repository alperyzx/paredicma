#!/bin/bash

# Handle update command (can be run without starting app)
if [[ "$1" == "--update" || "$1" == "update" ]]; then
    # Remove the 'update' or '--update' flag from arguments
    shift
    
    # Extract project directory
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
            echo "To force an update anyway, run: $0 --update --force"
            exit 0
        elif [[ $CHECK_EXIT -eq 0 ]]; then
            # Updates are available, continue with update
            echo "Updates available! Proceeding with update..."
        fi
    fi
    
    # Handle command line arguments for update
    if [[ "$1" == "--dry-run" ]]; then
        echo "Running in DRY-RUN mode..."
        python3 "$PROJECT_DIR/updater.py" --dry-run --project-dir "$PROJECT_DIR"
    elif [[ "$1" == "--force" ]]; then
        echo "Forcing update (skipping version check)..."
        python3 "$PROJECT_DIR/updater.py" --project-dir "$PROJECT_DIR"
    else
        python3 "$PROJECT_DIR/updater.py" --project-dir "$PROJECT_DIR" "$@"
    fi
    
    exit $?
fi

echo "Starting Paredicma - Redis Cluster Management Tool..."

# Function to find the highest Python 3.x version available
find_latest_python() {
    # First check if a specific version is requested through environment variable
    if [[ -n "$PYTHON_VERSION" ]]; then
        python_cmd="python$PYTHON_VERSION"
        if command -v $python_cmd &>/dev/null; then
            echo "Using specified Python version: $python_cmd" >&2
            echo $python_cmd
            return
        else
            echo "Warning: Requested Python version $PYTHON_VERSION not found" >&2
        fi
    fi

    # Dynamically find all python3.x executables, sort, and pick the highest
    highest_python=$(compgen -c | grep -E '^python3\.[0-9]+$' | sort -V | tail -n 1)
    if [[ -n "$highest_python" && "$highest_python" =~ ^python3\.[0-9]+$ ]]; then
        if command -v $highest_python &>/dev/null; then
            python_cmd="$highest_python"
            echo "Found highest Python: $python_cmd" >&2
            echo $python_cmd
            return
        fi
    fi

    # Fallback to generic python3
    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_version=$(python --version 2>&1)
        if [[ $python_version == Python\ 3* ]]; then
            python_cmd="python"
        else
            echo "No Python 3.x installation found. Please install Python 3.6 or higher." >&2
            exit 1
        fi
    else
        echo "No Python installation found. Please install Python 3.6 or higher." >&2
        exit 1
    fi

    # Display detected Python version
    python_full_version=$($python_cmd --version 2>&1 | awk '{print $2}')
    echo "Using $python_cmd (version $python_full_version)" >&2
    echo $python_cmd
}

# Get local IP address for server info
get_local_ip() {
    local python_cmd
    python_cmd=$(find_latest_python)
    $python_cmd -c "import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    try:
        hostname = socket.gethostname()
        print(socket.gethostbyname(hostname))
    except Exception:
        print('127.0.0.1')"
}

# Prevent running multiple instances
PID_FILE="./run.pid"
SERVER_IP=$(get_local_ip)

if [ -f "$PID_FILE" ]; then
    read existing_pid existing_port < "$PID_FILE"
    if [ -z "$existing_port" ]; then
        existing_port=8000
    fi
    if ps -p $existing_pid > /dev/null 2>&1; then
        echo "Paredicma Web Interface is already running (PID: $existing_pid)."
        echo "Access it at: http://$SERVER_IP:$existing_port"
        exit 1
    else
        # Stale PID file
        rm -f "$PID_FILE"
    fi
fi

echo "$$ $AVAILABLE_PORT" > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

# Check and install required packages from requirements.txt
check_and_install_packages() {
    local python_cmd=$1
    
    if [ ! -f "requirements.txt" ]; then
        echo "Warning: requirements.txt not found. Skipping package installation."
        return
    fi

    echo "Checking required packages from requirements.txt..."

    # Check for pip
    if command -v pip3 &>/dev/null; then
        pip_cmd="pip3"
    elif command -v pip &>/dev/null; then
        pip_cmd="pip"
    else
        echo "pip not found. Installing pip..."
        if [ -f /etc/debian_version ]; then
            # Debian/Ubuntu
            sudo apt update && sudo apt install -y python3-pip
        elif [ -f /etc/redhat-release ]; then
            # RHEL/CentOS/Fedora
            sudo yum install -y python3-pip
        else
            echo "Please install pip manually and try again."
            exit 1
        fi
        pip_cmd="pip3"
    fi

    # Install packages from requirements.txt
    echo "Installing packages from requirements.txt..."
    if [[ -n "$VIRTUAL_ENV" ]]; then
        # In venv: do NOT use --user
        $pip_cmd install -r requirements.txt
    else
        # System Python: use --user
        $pip_cmd install --user -r requirements.txt
    fi
    
    if [ $? -eq 0 ]; then
        echo "Package installation complete."
    else
        echo "Warning: Some packages may not have been installed successfully."
    fi
}

# Check for virtual environment and use it if available
venv_created=0
if [ -d ".venv" ]; then
    echo "Virtual environment found. Activating..."

    # Different activation files based on OS
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
        PYTHON_CMD="python"
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
        PYTHON_CMD="python"
    else
        echo "Virtual environment found but activation script not located."
        echo "Falling back to system Python..."
        PYTHON_CMD=$(find_latest_python)
    fi

    # Verify virtual environment is active
    if [[ "$VIRTUAL_ENV" != "" ]]; then
        echo "Using virtual environment at: $VIRTUAL_ENV"
    else
        echo "Failed to activate virtual environment. Falling back to system Python..."
        PYTHON_CMD=$(find_latest_python)
    fi
else
    echo "No virtual environment found."
    read -p "Would you like to create a virtual environment now? (y/n): " create_venv
    if [[ "$create_venv" =~ ^[Yy]$ ]]; then
        PYTHON_CMD=$(find_latest_python)
        echo "Creating virtual environment with $PYTHON_CMD..."
        $PYTHON_CMD -m venv .venv
        if [ $? -eq 0 ]; then
            echo "Virtual environment created. Activating..."
            source .venv/bin/activate
            PYTHON_CMD="python"
            venv_created=1
        else
            echo "Failed to create virtual environment. Falling back to system Python..."
            PYTHON_CMD=$(find_latest_python)
        fi
    else
        echo "Continuing without virtual environment. Using system Python..."
        PYTHON_CMD=$(find_latest_python)
    fi
fi

# Choose Python command:
# - If virtual environment is active, keep venv python
# - Otherwise choose highest available system python
if [[ -n "$VIRTUAL_ENV" ]]; then
    PYTHON_CMD="python"
else
    PYTHON_CMD=$(find_latest_python)
fi

# Enforce minimum Python version required by this project
if ! $PYTHON_CMD - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 8) else 1)
PY
then
    detected_version=$($PYTHON_CMD --version 2>&1)
    echo "Error: $detected_version detected. Paredicma requires Python 3.8 or higher." >&2
    echo "Tip: set PYTHON_VERSION (e.g., PYTHON_VERSION=3.10 ./run.sh) or recreate .venv with newer Python." >&2
    exit 1
fi

# Install packages if not using venv, or if venv was just created
if [[ "$VIRTUAL_ENV" == "" || $venv_created -eq 1 ]]; then
    check_and_install_packages $PYTHON_CMD
fi

# Check for available updates
check_for_updates() {
    local python_cmd=$1
    
    echo ""
    echo "Checking for updates..."
    
    # Run check_updates.py and capture output
    if [ -f "check_updates.py" ]; then
        update_result=$($python_cmd check_updates.py 2>/dev/null)
        exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            # Exit code 0 means updates are available
            echo ""
            echo "╔════════════════════════════════════════════╗"
            echo "║     ⚠️  UPDATE AVAILABLE                   ║"
            echo "╚════════════════════════════════════════════╝"
            echo ""
            echo "A new version of Paredicma is available!"
            echo ""
            
            read -p "Would you like to update now before starting? (y/n): " update_choice
            if [[ "$update_choice" =~ ^[Yy]$ ]]; then
                echo ""
                # Call run.sh with --update flag recursively (this script can handle it)
                "$0" --update
                if [ $? -eq 0 ]; then
                    echo ""
                    echo "✅ Update completed! Restarting application..."
                    echo ""
                    # Restart the application after update
                    exec "$0" "$@"
                else
                    echo ""
                    echo "❌ Update failed. Starting application with current version..."
                    echo ""
                fi
            else
                echo "Skipping update. Starting application..."
                echo ""
            fi
        fi
    fi
}

# Check for updates before running the application
check_for_updates $PYTHON_CMD

# Run the application
echo "Launching Paredicma Web Interface..."

# Function to find the next available port starting from 8000
find_available_port() {
    local port=8000
    while lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; do
        port=$((port + 1))
    done
    echo $port
}

# Find an available port
AVAILABLE_PORT=$(find_available_port)
if [ "$AVAILABLE_PORT" -ne 8000 ]; then
    echo "Port 8000 is busy. Using port $AVAILABLE_PORT instead."
    export PARE_WEB_PORT=$AVAILABLE_PORT
else
    export PARE_WEB_PORT=8000
fi

export PARE_SERVER_IP=$SERVER_IP

SERVER_ADDR="http://$SERVER_IP:$AVAILABLE_PORT"

$PYTHON_CMD parewebMon.py

exit $?

