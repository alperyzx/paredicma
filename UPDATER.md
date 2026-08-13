# Paredicma Project Updater - Complete Guide

Your paredicma project includes an automatic update system that downloads the latest code from GitHub while preserving your local configuration files.

## 🚀 Quick Start (2 Minutes)

### One-Command Preview (Safe - No Changes)
```bash
./run.sh --update --dry-run
```

### Apply Update
```bash
./run.sh --update
```

That's it! Your `.local` files are protected automatically.

---

## 📦 What's Included

### Executable Scripts
- **`updater.py`** (12 KB) - Main Python updater with full features
- **`run.sh`** - Main entry point with built-in update support
- **`check_updates.py`** (2.7 KB) - Check for updates without downloading

### Key Features
✅ Automatic GitHub downloads  
✅ Safe dry-run mode  
✅ Preserves local *.local files  
✅ Removes obsolete files  
✅ User confirmation required  
✅ No external dependencies  

---

## 💡 Common Commands

```bash
# Preview changes (recommended first)
./run.sh --update --dry-run

# Apply the update
./run.sh --update

# Check if updates exist (without downloading)
python3 check_updates.py --verbose

# Get update status as JSON
python3 check_updates.py --json
```

---

## 🔒 Protected Files (Never Modified)

The updater **always protects**:
- `pareConfig.py` - User's custom configuration
- `pareNodeList.py` - User's custom node list
- `.env` files
- `.git` repository
- `.venv` virtual environment
- `.vscode` settings
- `__pycache__` directories

## 📝 Files That Are Updated

The updater **always updates** (from the repository):
- `pareConfig.py.default` - Default configuration template
- `pareNodeList.py.default` - Default node list template
- All other project code files

---

## 📖 How It Works

### What Happens When You Update

1. **Downloads** the latest master branch from GitHub (~0.5 MB)
2. **Extracts** to a temporary directory
3. **Analyzes** which files have changed
4. **Shows you** the list of changes
5. **Asks for confirmation** before proceeding
6. **Updates** Python files, docs, and scripts
7. **Removes** obsolete files
8. **Preserves** your custom config files (pareConfig.py, pareNodeList.py)
9. **Cleans up** temporary files

### Download Source
```
https://github.com/alperyzx/paredicma/archive/refs/heads/master.zip
```

---

## 🔄 Common Workflows

### Workflow 1: Manual Update (Recommended First-Time)
```bash
# Step 1: Preview
$ ./run.sh --update --dry-run

[2026-08-12 15:30:45] [INFO] Files to update: 8
[2026-08-12 15:30:45] [INFO] Files to remove: 0
[2026-08-12 15:30:45] [INFO] Files preserved: 2

# Step 2: Review the changes

# Step 3: Apply
$ ./run.sh --update
Proceed with update? (yes/no): yes

[2026-08-12 15:30:48] [SUCCESS] Update completed successfully!
```

### Workflow 2: Automatic Daily Updates (Cron)
```bash
# Edit crontab
crontab -e

# Add this line (updates at 2 AM every day)
0 2 * * * cd /home/alper/Projects/paredicma && ./run.sh --update >/dev/null 2>&1

# Verify it was added
crontab -l
```

### Workflow 3: Scheduled Weekly Updates
```bash
# Edit crontab
crontab -e

# Add this line (updates at 2 AM every Sunday)
0 2 * * 0 cd /home/alper/Projects/paredicma && ./run.sh --update >/dev/null 2>&1
```

### Workflow 4: Update with Logging
```bash
# Create log directory
mkdir -p ~/.logs

# Edit crontab
crontab -e

# Add with logging
0 2 * * * cd /home/alper/Projects/paredicma && ./run.sh --update >> ~/.logs/paredicma-update.log 2>&1

# View logs
tail -f ~/.logs/paredicma-update.log
```

### Workflow 5: Backup Before Update
```bash
#!/bin/bash
PROJECT_DIR="/home/alper/Projects/paredicma"
BACKUP_DIR="$PROJECT_DIR/backups"

mkdir -p "$BACKUP_DIR"
BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S).tar.gz"

tar -czf "$BACKUP_DIR/$BACKUP_NAME" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    -C "$PROJECT_DIR" .

# Keep only last 10 backups
cd "$BACKUP_DIR"
ls -t *.tar.gz | tail -n +11 | xargs rm -f

# Now update
"$PROJECT_DIR/run.sh" --update
```

---

## 🌐 Integration Examples

### Docker Integration
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt && \
    chmod +x run.sh updater.py

CMD python3 paredicma.py
```

### Flask/FastAPI Web Integration
```python
import subprocess
import json

@app.get("/api/check-updates")
async def check_updates():
    """Check if updates are available"""
    result = subprocess.run(
        ["python3", "check_updates.py", "--json"],
        capture_output=True,
        text=True,
        cwd="/home/alper/Projects/paredicma"
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"error": "Failed to check updates"}

@app.post("/api/apply-updates")
async def apply_updates():
    """Apply pending updates"""
    result = subprocess.run(
        ["./run.sh", "--update"],
        capture_output=True,
        text=True,
        cwd="/home/alper/Projects/paredicma"
    )
    return {
        "status": "success" if result.returncode == 0 else "failed"
    }
```

### GitHub Actions (Auto-Update Fork)
```yaml
name: Auto-Update

on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Run updater
        run: |
          chmod +x run.sh
          ./run.sh --update
      - name: Create Pull Request
        uses: peter-evans/create-pull-request@v5
        with:
          commit-message: 'chore: auto-update from master'
          title: 'Auto-update from upstream'
          branch: 'auto-update'
```

### Systemd Timer (Auto-Update Service)
```ini
# /etc/systemd/system/paredicma-updater.service
[Unit]
Description=Paredicma Auto-Updater
After=network.target

[Service]
Type=oneshot
ExecStart=/home/alper/Projects/paredicma/run.sh --update
User=alper
WorkingDirectory=/home/alper/Projects/paredicma
StandardOutput=journal

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/paredicma-updater.timer
[Unit]
Description=Run Paredicma Updater Daily
Requires=paredicma-updater.service

[Timer]
OnCalendar=daily
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable paredicma-updater.timer
sudo systemctl start paredicma-updater.timer
```

---

## 📋 Real-World Examples

### Example 1: Simple Manual Update
```bash
$ ./run.sh --update --dry-run
# Review changes...
$ ./run.sh --update
Proceed with update? (yes/no): yes
# Done!
```

### Example 2: Check Without Downloading
```bash
$ python3 check_updates.py --verbose
Local version:  7d3a1f2
Remote version: 8b9c4e1
Updates available: Yes

Run './run.sh --update' to update to the latest version
```

### Example 3: Conditional Update
```bash
if python3 check_updates.py &>/dev/null; then
    echo "Updates available, applying..."
    ./run.sh --update
else
    echo "Already up to date"
fi
```

### Example 4: Update with Notification
```bash
RESULT=$(./run.sh --update)
STATUS=$?

if [ $STATUS -eq 0 ]; then
    echo "Paredicma updated successfully" | mail -s "Update Success" admin@example.com
else
    echo "Paredicma update failed" | mail -s "Update Failed" admin@example.com
fi
```

### Example 5: Graceful Restart After Update
```bash
./run.sh --update && \
echo "Update successful, restarting service..." && \
systemctl restart paredicma
```

### Example 6: Background Update Check
```python
import threading
import subprocess
from datetime import datetime

def check_updates_background():
    """Check for updates in the background"""
    try:
        result = subprocess.run(
            ["python3", "check_updates.py", "--json"],
            capture_output=True,
            text=True,
            cwd="/home/alper/Projects/paredicma",
            timeout=10
        )
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
    except Exception as e:
        print(f"Error checking updates: {e}")
    return None

def start_periodic_check(interval_minutes=60):
    """Start background thread for periodic checks"""
    def check_loop():
        import time
        while True:
            check_updates_background()
            time.sleep(interval_minutes * 60)
    
    thread = threading.Thread(target=check_loop, daemon=True)
    thread.start()

# Usage
start_periodic_check(interval_minutes=60)  # Check hourly
```

---

## ⚙️ Advanced Configuration

### Protected Files Pattern
The updater uses these patterns to protect files:
```python
PRESERVE_PATTERNS = [
    ".env",                 # Environment variables
    ".git*",                # Git files
    "__pycache__",          # Python cache
    ".venv",                # Virtual environment
    ".vscode",              # VS Code settings
    "pareConfig.py",        # User's custom pareConfig.py
    "pareNodeList.py",      # User's custom pareNodeList.py
]
```

### Custom Protected Files
To protect additional files, edit `updater.py`:
```python
PRESERVE_PATTERNS = [
    ".env",
    ".git*",
    "__pycache__",
    ".venv",
    ".vscode",
    "pareConfig.py",
    "pareNodeList.py",
    "my_custom_file.txt",  # Add here
    "custom_*.conf",       # Or use patterns
]
```

### Update Only Dry-Run
To see changes without applying:
```bash
python3 updater.py --dry-run --project-dir /path/to/paredicma
```

---

## 🆘 Troubleshooting

### Problem: "python3 is not installed"
**Solution:**
```bash
sudo apt install python3     # Ubuntu/Debian
brew install python3         # macOS
```

### Problem: "Permission denied"
**Solution:**
```bash
chmod +x run.sh updater.py check_updates.py
```

### Problem: "Certificate verify failed"
Usually happens behind corporate proxy. The updater still works locally.

### Problem: "No space left on device"
The updater needs ~2 MB free for download and extraction.

### Problem: Update interrupted
**Solution:** Run again - the updater handles partial states gracefully.

### Problem: Need to rollback
**Solution:** Use git to rollback:
```bash
git log --oneline           # See update history
git checkout <commit-hash>  # Rollback to specific version
```

---

## ❓ FAQ

**Q: Will my custom configuration files be overwritten?**  
A: No! Your custom configuration files are always protected:
   - `pareConfig.py` - Your custom configuration (PROTECTED)
   - `pareNodeList.py` - Your custom node list (PROTECTED)
   
   However, default templates ARE updated:
   - `pareConfig.py.default` - Updated to latest version
   - `pareNodeList.py.default` - Updated to latest version

**Q: How do I preview changes?**  
A: Run `./run.sh --update --dry-run` to see what will change without modifying anything.

**Q: Can I automate updates?**  
A: Yes! Use cron, systemd, Docker, GitHub Actions, or any other scheduler. See integration examples above.

**Q: What if something goes wrong?**  
A: You can rollback using git: `git checkout HEAD~1`

**Q: How much disk space is needed?**  
A: About 2 MB for download and temporary extraction.

**Q: Does it work with my .local files?**  
A: Yes! They're completely protected automatically.

**Q: Can I schedule updates?**  
A: Yes! Multiple methods shown above (cron, systemd, GitHub Actions, etc.)

**Q: How do I check for updates without downloading?**  
A: Run `python3 check_updates.py --verbose`

**Q: Can I update to a specific version?**  
A: The updater always gets the latest master branch. Use git for specific versions.

**Q: Is it safe to run the updater multiple times?**  
A: Yes! It's safe to run the updater as often as you like. It won't duplicate changes.

---

## 🔐 Security & Safety

- **File Permissions**: The `.local` files are protected by filename pattern matching
- **Network**: Uses HTTPS for GitHub downloads
- **Local Execution**: All updates happen locally, no credentials transmitted
- **Confirmation**: User confirmation is required before any modifications
- **Rollback**: Git repository allows easy rollback if needed
- **Temporary Files**: All temporary files are automatically cleaned up

---

## 📊 What Gets Updated

### Files Updated
- `.py` files (Python source code)
- `.md` files (Documentation)
- `.sh` files (Shell scripts)
- `.json`, `.yml`, `.yaml` (Config files)

### Files Preserved
- `*.local` files (Your local config)
- `.env` files (Environment)
- `.git*` files (Repository)
- Virtual environment
- Cache directories

### Files Removed
- Obsolete code files no longer in the repository

---

## 🎯 Next Steps

1. **Try a dry-run** (safe, no changes):
   ```bash
   ./run.sh --update --dry-run
   ```

2. **Review the changes** shown in the output

3. **Apply the update** if satisfied:
   ```bash
   ./run.sh --update
   ```

4. **Verify** your local files still exist:
   ```bash
   ls -la pareConfig.py.local pareNodeList.py.local
   ```

5. **Set up automation** (optional):
   - See cron examples above
   - Or use GitHub Actions
   - Or use systemd timer

---

## 📞 Support

For issues or questions:
- GitHub: https://github.com/alperyzx/paredicma
- Download: https://github.com/alperyzx/paredicma/archive/refs/heads/master.zip

---

## 📝 Version History

**Version 1.0** - August 12, 2026
- Initial release
- Full GitHub integration
- Local file protection
- Multiple update methods
- Comprehensive documentation

---

## ✅ Checklist Before First Update

- [ ] Read this guide (you're reading it!)
- [ ] Run dry-run: `./run.sh --update --dry-run`
- [ ] Review the file list shown
- [ ] Check that your `.local` files are listed as "preserved"
- [ ] Apply update: `./run.sh --update`
- [ ] Verify local files still exist: `ls pareConfig.py.local`

---

**Status**: ✅ Ready to Use  
**Last Updated**: August 12, 2026

Start with: `./run.sh --update --dry-run`
