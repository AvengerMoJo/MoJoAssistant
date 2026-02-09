# Auto-Reload for Development - FIXED

## The Issue

Uvicorn's `--reload` flag doesn't work well with our async initialization in `unified_mcp_server.py`. It causes event loop conflicts.

## Working Solution: Use watchfiles

### Install watchfiles

```bash
pip install watchfiles
```

### Method 1: Use watchfiles CLI (Recommended)

```bash
# Watch app/ directory and restart server on changes
watchfiles --filter python 'python3 unified_mcp_server.py --mode http --port 8000' app/
```

### Method 2: Create a wrapper script

Create `run_dev_watch.sh`:

```bash
#!/bin/bash
source venv/bin/activate

echo "Starting server with auto-reload (watchfiles)..."
echo "Edit any .py file in ./app/ to trigger restart"
echo ""

watchfiles --filter python \
  'python3 unified_mcp_server.py --mode http --port 8000' \
  app/
```

Make it executable:
```bash
chmod +x run_dev_watch.sh
./run_dev_watch.sh
```

### Method 3: Manual restart (Simple)

Just restart manually when you make changes:

```bash
# Start server
python3 unified_mcp_server.py --mode http --port 8000

# Edit code...
# Press Ctrl+C to stop
# Press Up arrow + Enter to restart
```

## Why Not Uvicorn --reload?

Uvicorn's `--reload` mode:
- Spawns subprocess that re-imports modules
- Conflicts with our async engine initialization
- Causes `RuntimeError: asyncio.run() cannot be called from a running event loop`

## watchfiles vs uvicorn --reload

**watchfiles**:
✅ Restarts entire process (clean initialization)
✅ Works with complex async setup
✅ Simple and reliable
❌ Slightly slower (full process restart)

**uvicorn --reload**:
✅ Faster (in-process reload)
❌ Doesn't work with our architecture
❌ Event loop conflicts

## Recommended Development Workflow

1. **Install watchfiles**:
   ```bash
   pip install watchfiles
   ```

2. **Start with watchfiles**:
   ```bash
   watchfiles --filter python 'python3 unified_mcp_server.py --mode http --port 8000' app/
   ```

3. **Edit code**:
   - Make changes to any file in `app/`
   - Save the file
   - Server automatically restarts within 1-2 seconds

4. **Test your changes**:
   - No manual restart needed
   - Fresh process each time

## Summary

**Don't use**: `./run_dev.sh` or `--reload` flag (broken)

**Use instead**: `watchfiles` for auto-reload

**Command**:
```bash
watchfiles --filter python 'python3 unified_mcp_server.py --mode http --port 8000' app/
```

**Or just restart manually** - it's simple and works perfectly.
