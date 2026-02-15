# Auto-Reload Development Server

## Quick Start

### Option 1: Use --reload flag (Recommended)

```bash
python3 unified_mcp_server.py --mode http --port 8000 --reload
```

**Result**: Server automatically restarts when you edit any Python files in `./app/`

### Option 2: Set ENVIRONMENT=development in .env

Edit your `.env` file:
```env
ENVIRONMENT=development
```

Then run normally:
```bash
python3 unified_mcp_server.py --mode http --port 8000
```

**Result**: Auto-reload is enabled automatically in development mode

### Option 3: Use watchfiles CLI (Alternative)

Install watchfiles:
```bash
pip install watchfiles
```

Run with watchfiles:
```bash
watchfiles --filter python 'python3 unified_mcp_server.py --mode http --port 8000' app/
```

**Result**: Server restarts when any `.py` file in `app/` changes

## How It Works

### What Gets Watched

When auto-reload is enabled, uvicorn watches:
- All Python files in `./app/` directory
- Subdirectories are watched recursively
- Changes trigger automatic restart

### What Does NOT Trigger Reload

- Changes to `.env` files (restart manually)
- Changes to files outside `./app/`
- Changes to non-Python files (unless specified)

## Development Workflow

1. **Start server with --reload**:
   ```bash
   python3 unified_mcp_server.py --mode http --port 8000 --reload
   ```

2. **Edit your code**:
   ```bash
   # Edit any file in app/
   nano app/mcp/opencode/manager.py
   ```

3. **Save the file**:
   - Server automatically detects the change
   - Server restarts within 1-2 seconds
   - Your changes are live!

4. **Test immediately**:
   - No need to manually restart
   - Just refresh/retry your request

## Performance Notes

### Development (--reload enabled)
- Slightly slower startup (watches for file changes)
- Automatic restarts on code changes
- Perfect for rapid development

### Production (--reload disabled)
- Faster startup
- No file watching overhead
- More stable (no unexpected restarts)

## Troubleshooting

### "Module not found" after reload

**Cause**: Python import cache issues

**Solution**: Hard restart:
```bash
# Stop server (Ctrl+C)
# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
# Start again
python3 unified_mcp_server.py --mode http --port 8000 --reload
```

### Changes not detected

**Cause**: File outside `./app/` directory

**Solution**:
- Move file to `./app/` directory, OR
- Add custom reload directory:

Edit `app/mcp/adapters/http.py` line with `reload_dirs`:
```python
reload_dirs=["./app", "./other_dir"] if use_reload else None
```

### Server restarting too often

**Cause**: Editor creating temporary files

**Solution**: Ignore temp files by adding to `.gitignore`:
```
*.swp
*.swo
*~
.*.tmp
```

## Examples

### Typical Development Session

```bash
# Terminal 1: Start server with auto-reload
$ python3 unified_mcp_server.py --mode http --port 8000 --reload
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Auto-reload enabled (development mode)

# Terminal 2: Make changes
$ nano app/mcp/opencode/manager.py
# Save changes...

# Terminal 1: Automatic output
INFO:     Detected file change, restarting...
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Using with .env Development Mode

```bash
# Set in .env
$ echo "ENVIRONMENT=development" >> .env

# Run without --reload flag
$ python3 unified_mcp_server.py --mode http --port 8000

# Auto-reload still enabled (from ENVIRONMENT variable)
```

### Watch Specific Directories

If you want to watch additional directories, edit `app/mcp/adapters/http.py`:

```python
config = uvicorn.Config(
    self.app,
    host=host,
    port=port,
    log_level="info",
    reload=use_reload,
    reload_dirs=["./app", "./config", "./scripts"] if use_reload else None  # Added more dirs
)
```

## Best Practices

### DO:
✅ Use `--reload` during development
✅ Test changes immediately after saving
✅ Keep watched directories minimal (faster reloads)
✅ Use production mode (no --reload) when deploying

### DON'T:
❌ Use `--reload` in production
❌ Edit files while server is reloading
❌ Watch directories with many non-Python files
❌ Expect .env changes to reload automatically

## Summary

**Development**: `python3 unified_mcp_server.py --mode http --port 8000 --reload`

**Production**: `python3 unified_mcp_server.py --mode http --port 8000`

**That's it!** Edit your code and it automatically reloads.
