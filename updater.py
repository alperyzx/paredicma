#!/usr/bin/env python3
"""
Paredicma Project Updater
Downloads the latest version from GitHub and updates the codebase
while preserving user configuration files (*.local, pareConfig.py, pareNodeList.py)
"""

import os
import sys
import shutil
import urllib.request
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime


class ParedicmaUpdater:
    """Handles updating the paredicma project from GitHub"""
    
    # GitHub raw archive URL
    GITHUB_URL = "https://github.com/alperyzx/paredicma/archive/refs/heads/master.zip"
    
    # Files/patterns to preserve (not to be overwritten)
    PRESERVE_PATTERNS = [
        ".env",                 # Environment variables
        ".git*",                # Git files
        "__pycache__",          # Python cache
        ".venv",                # Virtual environment
        ".vscode",              # VS Code settings
        "pareConfig.py",        # User's custom pareConfig.py
        "pareNodeList.py",      # User's custom pareNodeList.py
    ]
    
    def __init__(self, project_dir: str = None):
        """
        Initialize the updater
        
        Args:
            project_dir: Path to the project directory. If None, uses current directory
        """
        if project_dir is None:
            project_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.project_dir = Path(project_dir)
        self.temp_dir = None
        self.extract_dir = None
        
    def should_preserve(self, filepath: Path) -> bool:
        """
        Check if a file should be preserved (not updated)
        
        Args:
            filepath: Path to check
            
        Returns:
            True if file should be preserved, False otherwise
        """
        name = filepath.name
        for pattern in self.PRESERVE_PATTERNS:
            if "*" in pattern:
                # Handle wildcard patterns
                import fnmatch
                if fnmatch.fnmatch(name, pattern):
                    return True
            elif name == pattern:
                # Exact match only for non-wildcard patterns
                return True
        return False
    
    def print_status(self, message: str, status: str = "INFO"):
        """Print formatted status message"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{status}] {message}")
    
    def download_archive(self) -> Path:
        """
        Download the latest archive from GitHub
        
        Returns:
            Path to the downloaded zip file
            
        Raises:
            Exception: If download fails
        """
        self.print_status(f"Downloading latest version from GitHub...")
        self.print_status(f"URL: {self.GITHUB_URL}")
        
        self.temp_dir = tempfile.mkdtemp()
        zip_path = Path(self.temp_dir) / "paredicma-master.zip"
        
        try:
            urllib.request.urlretrieve(self.GITHUB_URL, zip_path)
            file_size_mb = zip_path.stat().st_size / (1024 * 1024)
            self.print_status(f"Downloaded successfully ({file_size_mb:.2f} MB)")
            return zip_path
        except Exception as e:
            self.print_status(f"Download failed: {str(e)}", "ERROR")
            raise
    
    def extract_archive(self, zip_path: Path) -> Path:
        """
        Extract the zip archive
        
        Args:
            zip_path: Path to the zip file
            
        Returns:
            Path to the extracted directory
            
        Raises:
            Exception: If extraction fails
        """
        self.print_status("Extracting archive...")
        
        extract_dir = Path(self.temp_dir) / "extracted"
        extract_dir.mkdir(exist_ok=True)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # The GitHub archive creates a "paredicma-master" subdirectory
            extracted_project = extract_dir / "paredicma-master"
            
            if not extracted_project.exists():
                raise FileNotFoundError("Expected 'paredicma-master' directory not found in archive")
            
            self.print_status(f"Extracted to temporary directory")
            self.extract_dir = extracted_project
            return extracted_project
        except Exception as e:
            self.print_status(f"Extraction failed: {str(e)}", "ERROR")
            raise
    
    def get_files_to_update(self) -> tuple:
        """
        Determine which files need to be updated
        
        Returns:
            Tuple of (files_to_update, files_to_remove, files_preserved)
        """
        files_to_update = []
        files_to_remove = []
        files_preserved = []
        
        # Get all files in the extracted archive
        if not self.extract_dir:
            return files_to_update, files_to_remove, files_preserved
        
        for extracted_file in self.extract_dir.rglob("*"):
            if extracted_file.is_file():
                # Get relative path from extracted dir
                rel_path = extracted_file.relative_to(self.extract_dir)
                target_file = self.project_dir / rel_path
                
                # Check if should preserve
                if self.should_preserve(extracted_file):
                    files_preserved.append(str(rel_path))
                    continue
                
                files_to_update.append((extracted_file, target_file))
        
        # Find files in project that don't exist in the archive (for removal)
        for project_file in self.project_dir.rglob("*"):
            if project_file.is_file():
                # Skip certain directories
                if any(part in project_file.parts for part in ['__pycache__', '.git', '.venv', 'docs', '.vscode']):
                    continue
                
                rel_path = project_file.relative_to(self.project_dir)
                
                # Check if should preserve (for files not in archive)
                if self.should_preserve(project_file):
                    # Add preserved files to the preserved list even if not in archive
                    extracted_equiv = self.extract_dir / rel_path
                    if not extracted_equiv.exists():
                        files_preserved.append(str(rel_path))
                    continue
                
                extracted_equiv = self.extract_dir / rel_path
                
                # If file doesn't exist in archive, mark for removal
                if not extracted_equiv.exists():
                    # Only remove if it looks like project code
                    if project_file.suffix in ['.py', '.md', '.sh', '.txt', '.json', '.yml', '.yaml']:
                        files_to_remove.append(str(rel_path))
        
        return files_to_update, files_to_remove, files_preserved
    
    def update_files(self, files_to_update: list) -> int:
        """
        Copy updated files to the project directory
        
        Args:
            files_to_update: List of (source, destination) tuples
            
        Returns:
            Number of files updated
        """
        import stat
        count = 0
        for src, dest in files_to_update:
            try:
                # Create parent directories if needed
                dest.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file with metadata
                shutil.copy2(src, dest)
                
                # Preserve executable bit for scripts
                src_stat = src.stat()
                if src_stat.st_mode & stat.S_IXUSR:  # If source is executable
                    dest_mode = dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    dest.chmod(dest_mode)
                
                count += 1
            except Exception as e:
                self.print_status(f"Failed to update {dest.relative_to(self.project_dir)}: {str(e)}", "WARN")
        
        return count
    
    def remove_obsolete_files(self, files_to_remove: list) -> int:
        """
        Remove files that are no longer in the archive
        
        Args:
            files_to_remove: List of file paths to remove (relative to project dir)
            
        Returns:
            Number of files removed
        """
        count = 0
        for filepath in files_to_remove:
            try:
                target = self.project_dir / filepath
                if target.exists():
                    target.unlink()
                    count += 1
            except Exception as e:
                self.print_status(f"Failed to remove {filepath}: {str(e)}", "WARN")
        
        return count
    
    def cleanup(self):
        """Clean up temporary files"""
        if self.temp_dir and Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
                self.print_status("Cleaned up temporary files")
            except Exception as e:
                self.print_status(f"Warning: Could not clean up temp directory: {str(e)}", "WARN")
    
    def run(self, dry_run: bool = False) -> bool:
        """
        Run the update process
        
        Args:
            dry_run: If True, only show what would be done without making changes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.print_status("=" * 60)
            self.print_status("Paredicma Project Updater")
            self.print_status("=" * 60)
            
            if dry_run:
                self.print_status("Running in DRY-RUN mode (no changes will be made)")
            
            # Download
            zip_path = self.download_archive()
            
            # Extract
            extract_dir = self.extract_archive(zip_path)
            
            # Analyze changes
            self.print_status("Analyzing changes...")
            files_to_update, files_to_remove, files_preserved = self.get_files_to_update()
            
            # Report
            self.print_status("=" * 60)
            self.print_status(f"Files to update: {len(files_to_update)}")
            self.print_status(f"Files to remove: {len(files_to_remove)}")
            self.print_status(f"Files preserved: {len(files_preserved)}")
            self.print_status("=" * 60)
            
            if files_preserved:
                self.print_status("Preserved files (will NOT be modified):")
                for file in sorted(files_preserved)[:10]:  # Show first 10
                    print(f"  - {file}")
                if len(files_preserved) > 10:
                    print(f"  ... and {len(files_preserved) - 10} more")
            
            if dry_run:
                self.print_status("DRY-RUN: Would update the above files. Run without --dry-run to apply.", "INFO")
                self.cleanup()
                return True
            
            # Confirm with user
            response = input("\nProceed with update? (yes/no): ").strip().lower()
            if response != "yes":
                self.print_status("Update cancelled by user")
                self.cleanup()
                return False
            
            # Apply updates
            self.print_status("Updating files...")
            updated = self.update_files(files_to_update)
            self.print_status(f"Updated {updated} files")
            
            # Remove obsolete files
            if files_to_remove:
                self.print_status("Removing obsolete files...")
                removed = self.remove_obsolete_files(files_to_remove)
                self.print_status(f"Removed {removed} obsolete files")
            
            # Success
            self.print_status("=" * 60)
            self.print_status("Update completed successfully!", "SUCCESS")
            self.print_status("=" * 60)
            
            return True
            
        except Exception as e:
            self.print_status(f"Update failed: {str(e)}", "ERROR")
            return False
        finally:
            self.cleanup()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update paredicma project from GitHub master branch"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    parser.add_argument(
        "--project-dir",
        help="Path to project directory (default: script directory)"
    )
    
    args = parser.parse_args()
    
    updater = ParedicmaUpdater(project_dir=args.project_dir)
    success = updater.run(dry_run=args.dry_run)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
