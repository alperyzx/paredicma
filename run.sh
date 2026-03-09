#!/bin/bash

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

# Always choose the max python version available
PYTHON_CMD=$(find_latest_python)

# Install packages if not using venv, or if venv was just created
if [[ "$VIRTUAL_ENV" == "" || $venv_created -eq 1 ]]; then
    check_and_install_packages $PYTHON_CMD
fi

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

