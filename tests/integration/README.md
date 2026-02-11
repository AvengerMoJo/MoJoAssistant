# OpenCode Manager Integration Tests

This directory contains end-to-end integration tests for the OpenCode Manager.

## Prerequisites

1. **OpenCode installed** - Ensure `opencode` is in your PATH or configured in your environment
2. **Global config setup** - Required file: `~/.memory/opencode-manager.env`
   ```bash
   # Create from template
   cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env

   # Edit and set passwords
   vim ~/.memory/opencode-manager.env

   # Set permissions
   chmod 600 ~/.memory/opencode-manager.env
   ```

3. **SSH key setup** (if using private repos) - The test will generate SSH keys, but you may need to add them to GitHub

## Running the Complete Workflow Test

### Quick Start (Public Repo)

```bash
# Run with default public repository
python tests/integration/test_complete_workflow.py
```

This will test with Anthropic's quickstarts repo (public, no SSH key needed).

### Test with Your Own Repository

```bash
# Test with a specific git repository
python tests/integration/test_complete_workflow.py --git-url git@github.com:user/repo.git
```

### What the Test Does

The complete workflow test validates all major OpenCode Manager operations:

1. **Start Project** - Initialize OpenCode instance for a git repository
2. **Get Deploy Key** - Retrieve SSH public key for GitHub
3. **List Projects** - Verify project is registered
4. **Project Status** - Check OpenCode process is running
5. **Create Sandbox** - Create a git worktree
6. **List Sandboxes** - Verify worktree creation
7. **Create Session** - Start a new chat session
8. **Send Message** - Send a test message to the session
9. **List Sessions** - Verify session exists
10. **Cleanup** - Delete sandbox and stop project

### Expected Output

```
======================================================================
  OpenCode Manager - Complete Workflow Integration Test
======================================================================

Git URL: git@github.com:anthropics/anthropic-quickstarts.git

======================================================================
  Step 1: Start Project
======================================================================

Starting project for: git@github.com:anthropics/anthropic-quickstarts.git
✅ Start Project
   project: anthropics-anthropic-quickstarts
   git_url: git@github.com:anthropics/anthropic-quickstarts.git
   opencode_port: 4100
   base_dir: /home/user/.opencode-projects/anthropics-anthropic-quickstarts

======================================================================
  Step 2: Get Deploy Key
======================================================================

Retrieving SSH deploy key...
✅ Get Deploy Key
   project: anthropics-anthropic-quickstarts

📋 Public Key:
----------------------------------------------------------------------
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... opencode@localhost
----------------------------------------------------------------------

🔗 Add key at: https://github.com/anthropics/anthropic-quickstarts/settings/keys

... (continues for all steps)

======================================================================
  Test Summary
======================================================================

Results: 9/9 tests passed

✅ Start Project
✅ Get Deploy Key
✅ List Projects
✅ Project Status
✅ Create Sandbox
✅ List Sandboxes
✅ Create Session
✅ Send Message
✅ List Sessions

======================================================================
🎉 ALL TESTS PASSED!
======================================================================
```

## Troubleshooting

### Error: "Global config not found"

```bash
# Create global config
cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env
vim ~/.memory/opencode-manager.env  # Set OPENCODE_PASSWORD and MCP_BEARER_TOKEN
chmod 600 ~/.memory/opencode-manager.env
```

### Error: "OpenCode binary not found"

```bash
# Install OpenCode (if not installed)
npm install -g @opencode/cli

# Or specify path in global config
echo "OPENCODE_BIN=/path/to/opencode" >> ~/.memory/opencode-manager.env
```

### Error: "SSH key authentication failed"

If testing with a private repository:

1. Run the test once to generate SSH key
2. Copy the public key from the output
3. Add it to your repository's deploy keys:
   - Go to GitHub: `https://github.com/user/repo/settings/keys`
   - Click "Add deploy key"
   - Paste the public key
   - Save
4. Run the test again

### Test Hangs or Times Out

- Check if OpenCode is already running on the port (4100-4199)
- Check if port is blocked by firewall
- Try with a smaller/public repository first

### Cleanup After Failed Test

If a test fails and doesn't clean up properly:

```bash
# List running projects
python -c "
import asyncio
from app.mcp.core.tools import ToolRegistry
from app.services.memory_service import MemoryService

async def main():
    tools = ToolRegistry(MemoryService())
    result = await tools.execute('opencode_project_list', {})
    print(result)

asyncio.run(main())
"

# Stop a specific project
python -c "
import asyncio
from app.mcp.core.tools import ToolRegistry
from app.services.memory_service import MemoryService

async def main():
    tools = ToolRegistry(MemoryService())
    result = await tools.execute('opencode_project_stop', {
        'git_url': 'git@github.com:user/repo.git'
    })
    print(result)

asyncio.run(main())
"
```

## Adding More Tests

To add more integration tests:

1. Create a new file: `test_<feature>.py`
2. Follow the same pattern as `test_complete_workflow.py`
3. Use the `ToolRegistry` to execute MCP tools
4. Always include cleanup steps

Example:

```python
import asyncio
from app.mcp.core.tools import ToolRegistry
from app.services.memory_service import MemoryService

async def test_my_feature():
    tools = ToolRegistry(MemoryService())

    # Your test here
    result = await tools.execute("opencode_project_start", {
        "git_url": "git@github.com:user/repo.git"
    })

    assert result["status"] == "success"

    # Cleanup
    await tools.execute("opencode_project_stop", {
        "git_url": "git@github.com:user/repo.git"
    })

if __name__ == "__main__":
    asyncio.run(test_my_feature())
```

## CI/CD Integration

To run integration tests in CI/CD:

1. Set up OpenCode in the CI environment
2. Create global config with test credentials
3. Use a test repository (public or with deploy key)
4. Run tests:

```yaml
# .github/workflows/integration-tests.yml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          npm install -g @opencode/cli

      - name: Set up OpenCode config
        run: |
          mkdir -p ~/.memory
          echo "OPENCODE_PASSWORD=${{ secrets.OPENCODE_PASSWORD }}" > ~/.memory/opencode-manager.env
          echo "MCP_BEARER_TOKEN=${{ secrets.MCP_BEARER_TOKEN }}" >> ~/.memory/opencode-manager.env
          chmod 600 ~/.memory/opencode-manager.env

      - name: Run integration tests
        run: python tests/integration/test_complete_workflow.py
```
