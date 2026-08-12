#!/usr/bin/env python3
"""
Check if updates are available for paredicma
This can be called from the web interface or command line
"""

import subprocess
import urllib.request
import json
from pathlib import Path
from datetime import datetime
import sys


def get_local_version() -> str:
    """Get the local project version from git or file"""
    try:
        # Try to get from git
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    
    return "unknown"


def get_remote_version() -> str:
    """Get the remote master branch version"""
    try:
        url = "https://api.github.com/repos/alperyzx/paredicma/commits/master"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data['sha'][:7]
    except Exception as e:
        return f"error: {str(e)}"


def check_updates(verbose: bool = False) -> dict:
    """
    Check if updates are available
    
    Args:
        verbose: Print detailed information
        
    Returns:
        Dictionary with update status
    """
    local_version = get_local_version()
    remote_version = get_remote_version()
    
    updates_available = (
        local_version != remote_version and 
        not local_version.startswith("error") and 
        not remote_version.startswith("error")
    )
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "local_version": local_version,
        "remote_version": remote_version,
        "updates_available": updates_available,
        "update_url": "https://github.com/alperyzx/paredicma/archive/refs/heads/master.zip"
    }
    
    if verbose:
        print(f"Local version:  {local_version}")
        print(f"Remote version: {remote_version}")
        print(f"Updates available: {'Yes' if updates_available else 'No'}")
        if updates_available:
            print(f"\nRun './update.sh' to update to the latest version")
    
    return result


def format_json_response(result: dict) -> str:
    """Format result as JSON for API responses"""
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    json_output = "--json" in sys.argv
    
    result = check_updates(verbose=verbose)
    
    if json_output:
        print(format_json_response(result))
    elif not verbose:
        print(json.dumps(result, indent=2))
    
    # Exit with code 0 if updates available, 1 if not
    sys.exit(0 if result["updates_available"] else 1)
