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
    """
    Get the local project version from multiple sources in order of preference:
    1. Git commit hash (most reliable)
    2. Version marker file left by updater.py after successful update
    3. File content hash (for manually updated installations)
    """
    project_dir = Path(__file__).parent
    
    # Method 1: Try git first (most reliable)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=5
        )
        if result.returncode == 0:
            git_version = result.stdout.strip()
            if git_version and git_version != "":
                return git_version
    except:
        pass
    
    # Method 2: Check for version marker file (set after successful updater.py run)
    try:
        marker_file = project_dir / ".last_update_version"
        if marker_file.exists():
            with open(marker_file, 'r') as f:
                marker_version = f.read().strip()
                if marker_version and len(marker_version) >= 7:
                    return marker_version[:7]
    except:
        pass
    
    # Method 3: Fallback to hashing key files to detect manual updates
    try:
        import hashlib
        key_files = [
            "parewebMon.py",
            "paredicma.py",
            "pareFunc.py",
            "README.md",
        ]
        
        file_hashes = []
        for filename in key_files:
            filepath = project_dir / filename
            if filepath.exists():
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:7]
                    file_hashes.append(file_hash)
        
        if file_hashes:
            # Combine hashes and take first 7 chars
            combined = "".join(file_hashes)
            return hashlib.md5(combined.encode()).hexdigest()[:7]
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


def is_git_repo() -> bool:
    """Check if the project is a git repository"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


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
    
    # For git repos: trust git version
    # For non-git (manually updated): use file hash comparison
    is_git = is_git_repo()
    
    updates_available = (
        local_version != remote_version and 
        not local_version.startswith("error") and 
        not remote_version.startswith("error") and
        local_version != "unknown" and
        remote_version != "unknown"
    )
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "local_version": local_version,
        "remote_version": remote_version,
        "updates_available": updates_available,
        "is_git_repo": is_git,
        "update_url": "https://github.com/alperyzx/paredicma/archive/refs/heads/master.zip"
    }
    
    if verbose:
        print(f"Local version:  {local_version}")
        print(f"Remote version: {remote_version}")
        print(f"Git repository: {'Yes' if is_git else 'No (using file hash)'}")
        print(f"Updates available: {'Yes' if updates_available else 'No'}")
        if updates_available:
            print(f"\nRun './run.sh --update' to update to the latest version")
        elif local_version == "unknown" or remote_version == "unknown":
            print("\nWarning: Could not determine version. Run './run.sh --update --force' to update anyway.")
    
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
