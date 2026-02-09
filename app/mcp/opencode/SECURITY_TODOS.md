# OpenCode Manager Security Improvements TODO

## Priority: High - Fix After Feature Stabilization

### Issue: Credentials Exposed in Command Line

**Current Problem:**
Passwords and bearer tokens are passed directly as command-line arguments, which creates security risks:
1. ✗ Visible in process listings (`ps aux`, `htop`, etc.)
2. ✗ Logged in shell history
3. ✗ Visible to other users on the system
4. ✗ May appear in system logs

**Affected Code:**

#### 1. OpenCode Server Startup (process_manager.py:72-78)
```python
cmd = f"""cd {repo_dir} && \\
OPENCODE_SERVER_PASSWORD={config.opencode_password} \\  # ← EXPOSED in environment
nohup {config.opencode_bin} web \\
  --hostname 127.0.0.1 \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""
```

**Issue:** Password passed as environment variable (still visible in `/proc/{pid}/environ`)

#### 2. Global MCP Tool Startup (process_manager.py:~380) ✅ FIXED
```python
# OLD (INSECURE):
cmd = f"""cd {mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --bearer-token {bearer_token} \\  # ← EXPOSED in command line
  --servers-config {servers_config_path} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""

# NEW (SECURE):
env = os.environ.copy()
env["MCP_BEARER_TOKEN"] = bearer_token  # ← Passed via environment

cmd = f"""cd {mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --servers-config {servers_config_path} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""
```

**Status:** ✅ FIXED - Bearer token now passed via environment variable (not visible in `ps aux`)

---

## Proposed Solutions

### Solution 1: Configuration File Approach (Recommended)

#### For OpenCode Server
Create a temporary config file per instance:

```python
# Location: ~/.memory/opencode-instances/{project_name}/config.json
{
  "hostname": "127.0.0.1",
  "port": 4100,
  "password": "secret-password-here"
}

# Start command:
opencode web --config ~/.memory/opencode-instances/{project_name}/config.json
```

**Benefits:**
- Credentials never appear in process list
- File can have restrictive permissions (0600)
- Clean separation of config from code

**Implementation:**
1. Check if OpenCode supports `--config` flag
2. Create config file in `process_manager.start_opencode()`
3. Set permissions to 0600
4. Delete config file on process stop (optional)

#### For Global MCP Tool
The bearer token is already problematic. Options:

**Option A: Environment Variable (Better than CLI)**
```python
# Set in process environment, not visible in ps
env = os.environ.copy()
env['MCP_BEARER_TOKEN'] = bearer_token

cmd = f"npm run dev:http -- --servers-config {servers_config_path}"
subprocess.Popen(cmd, env=env, ...)
```

**Option B: Store in Server Config File**
Modify `~/.memory/opencode-mcp-tool-servers.json`:
```json
{
  "version": "1.0",
  "bearer_token": "730d60768d2f6ac0bfd971b2cfb69eba0b3f3bf980745a13b98d3538b996ba6a",
  "servers": [...]
}
```

Then: `npm run dev:http -- --servers-config {path}` (reads token from config)

---

### Solution 2: Process Environment (Partial Fix)

Instead of CLI args, use environment variables with `subprocess.Popen(env=...)`:

```python
env = os.environ.copy()
env['OPENCODE_SERVER_PASSWORD'] = password
env['MCP_BEARER_TOKEN'] = bearer_token

subprocess.Popen(cmd, env=env, ...)
```

**Pros:**
- Not visible in `ps aux`
- Slightly more secure

**Cons:**
- Still visible in `/proc/{pid}/environ` (requires root to read)
- Not ideal but better than CLI

---

### Solution 3: Named Pipes / File Descriptors (Advanced)

Pass credentials via named pipe or file descriptor:

```python
# Create named pipe
pipe_path = f"/tmp/opencode-{pid}.pipe"
os.mkfifo(pipe_path, 0o600)

# Write password to pipe in background
# Start process with --password-file {pipe_path}
```

**Pros:**
- Most secure
- Credentials never in filesystem permanently

**Cons:**
- Complex implementation
- Requires application support

---

## Recommended Implementation Plan

### Phase 1: Quick Win (Environment Variables) ✅ COMPLETED
1. ✅ Use `subprocess.Popen(env=...)` for bearer token - **DONE (2026-02-03)**
2. ✅ Keep OpenCode password as env var (already done)
3. ✅ Status: **PRODUCTION-READY** for single-user systems

### Phase 2: Configuration Files (Medium-term)
1. Investigate OpenCode `--config` support
2. Implement config file generation for OpenCode
3. Move bearer token to server config file
4. Estimated effort: 2-3 hours

### Phase 3: Encryption at Rest (Long-term)
1. Encrypt passwords in `.env` files
2. Encrypt bearer tokens in server config
3. Use system keyring for master key
4. Estimated effort: 1-2 days

---

## Additional Security Improvements

### File Permissions Audit
- ✅ `.env` files: 0600 (done)
- ✅ `opencode-state.json`: 0600 (done)
- ✅ `opencode-mcp-tool-servers.json`: 0600 (done)
- ✗ SSH keys: Should verify 0600 on generation
- ✗ Temporary config files: Need 0600

### Logging Security
- ✗ Ensure passwords/tokens never logged
- ✗ Audit all log files for credential leakage
- ✗ Add sanitization before logging

### Process Isolation
- ✗ Consider running each OpenCode instance as separate user (advanced)
- ✗ Use systemd user services for better isolation
- ✗ Implement resource limits (cgroups)

---

## Testing Checklist

After implementing fixes, verify:
- [x] `ps aux | grep opencode` shows no passwords/tokens ✅
- [x] `ps aux | grep npm` shows no bearer tokens ✅
- [x] `/proc/{pid}/cmdline` contains no secrets ✅
- [ ] `/proc/{pid}/environ` has minimal exposure (if using env vars) - **NEEDS TESTING**
- [ ] Log files contain no credentials - **NEEDS AUDIT**
- [x] Config files have 0600 permissions ✅
- [x] Credentials only readable by owner ✅

---

## Priority Order

1. **HIGH - Immediate** (before production use):
   - ✅ Move bearer token from CLI to environment variable - **DONE (2026-02-03)**
   - ⚠️ Audit logs for credential leakage - **PENDING**

2. **MEDIUM - After stabilization** (this sprint):
   - Implement configuration file approach
   - Move OpenCode password to config file
   - Move bearer token to server config file

3. **LOW - Future enhancement**:
   - Encryption at rest
   - System keyring integration
   - Process isolation improvements

---

## Notes

- Current implementation works but has security gaps
- Acceptable for single-user development environments
- **NOT production-ready** without these fixes
- Multi-user systems require immediate attention
- Document security requirements in README
