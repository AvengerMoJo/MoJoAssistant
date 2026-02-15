# Phase 5: Migration & Testing Plan

**Date:** 2026-02-11
**Objective:** Validate complete system, handle edge cases, and ensure production readiness

---

## Status Check

### Completed Phases
- ✅ **Phase 1:** Core Architecture (git_url as primary key)
  - Auto-migration in StateManager and ConfigManager
  - Standalone migration script: `migrate_phase1.py`
  - Utils for git URL normalization

- ✅ **Phase 2:** Worktree/Sandbox Management
  - WorktreeManager wraps `/experimental/worktree` API
  - Integrated with OpenCodeManager

- ✅ **Phase 3:** MCP Tools Update
  - All 15 tools renamed and updated to git_url-based
  - 4 new sandbox management tools added

- ✅ **Phase 4:** SSH Deploy Key Management
  - `opencode_get_deploy_key` tool
  - Auto-generation of SSH keys per git_url

### What Phase 5 Actually Needs

Based on what's already implemented, Phase 5 should focus on:
1. **Testing & Validation** - Comprehensive test suite
2. **Edge Case Handling** - Duplicate project detection
3. **Documentation** - User guides and API docs
4. **Production Readiness** - Error handling, logging, monitoring

---

## Phase 5 Tasks

### Task 1: Comprehensive Testing

#### 1.1 Unit Tests
- [ ] Test `normalize_git_url()` with various URL formats
  - SSH format: `git@github.com:user/repo.git`
  - HTTPS format: `https://github.com/user/repo`
  - With/without .git suffix
  - GitLab, Bitbucket URLs

- [ ] Test `generate_project_name()` edge cases
  - Special characters in repo names
  - Very long repo names
  - Duplicate owner-repo combinations

- [ ] Test StateManager migration
  - Old format → new format
  - Already migrated (idempotent)
  - Corrupt state files

- [ ] Test ConfigManager migration
  - Old format → new format
  - Port conflicts
  - Missing fields

#### 1.2 Integration Tests
- [ ] Complete workflow: Start → Sandbox → Deploy Key → Stop
  ```python
  # Test: Full project lifecycle
  1. opencode_project_start(git_url)
  2. opencode_get_deploy_key(git_url)
  3. opencode_sandbox_create(git_url, "test-sandbox")
  4. opencode_sandbox_list(git_url)
  5. opencode_sandbox_delete(git_url, "test-sandbox")
  6. opencode_project_stop(git_url)
  ```

- [ ] Test duplicate git_url handling
  - Start same git_url twice → should return existing instance
  - Different base_dirs for same git_url → how to handle?

- [ ] Test worktree operations
  - Create multiple worktrees
  - Reset worktree
  - Delete worktree
  - Error handling (invalid branch, already exists)

- [ ] Test SSH key management
  - Generate key for new project
  - Retrieve existing key
  - Key permissions (0600)

#### 1.3 Error Handling Tests
- [ ] Network failures (OpenCode API unreachable)
- [ ] Authentication failures (wrong password)
- [ ] Port conflicts (port already in use)
- [ ] Invalid git URLs
- [ ] Missing SSH keys
- [ ] Disk space issues
- [ ] Process crashes (OpenCode dies)

---

### Task 2: Edge Case Handling

#### 2.1 Duplicate Project Detection

**Problem:** User has same git repo running in multiple locations
```
Port 4100: ~/.memory/opencode-sandboxes/Mobile_MoJoAssistant_Dev/repo
Port 4104: /home/alex/Development/Personal/MoJoAssistant
Both point to: git@github.com:user/repo.git
```

**Solution:** Add detection tool
```python
async def detect_duplicate_projects() -> Dict[str, Any]:
    """
    Scan running OpenCode instances and detect duplicates

    Returns:
        {
            "duplicates": [
                {
                    "git_url": "git@github.com:user/repo.git",
                    "instances": [
                        {"port": 4100, "base_dir": "~/.memory/..."},
                        {"port": 4104, "base_dir": "/home/alex/..."}
                    ],
                    "recommendation": "Keep main dev directory, convert others to worktrees"
                }
            ]
        }
    """
```

**Implementation:**
- [ ] Add `detect_duplicate_projects()` to OpenCodeManager
- [ ] Add `opencode_detect_duplicates` MCP tool
- [ ] Provide recommendations (which to keep, how to migrate)

#### 2.2 Port Conflict Resolution

**Problem:** Requested port is already in use

**Solution:**
- [ ] Auto-assign next available port in range (4100-4199)
- [ ] Store port assignments in state
- [ ] Detect and reuse stopped project ports

#### 2.3 Orphaned Process Cleanup

**Problem:** OpenCode process dies but state still shows "running"

**Solution:**
- [ ] Add health check on manager startup
- [ ] Detect orphaned PIDs (process doesn't exist)
- [ ] Clean up state automatically
- [ ] Add `opencode_cleanup` tool for manual cleanup

---

### Task 3: Documentation

#### 3.1 User Documentation

- [ ] **Getting Started Guide**
  - Installing OpenCode Manager
  - First project setup
  - Adding SSH deploy key to GitHub
  - Creating sandboxes

- [ ] **Common Workflows**
  - Starting/stopping projects
  - Working with sandboxes
  - Managing multiple projects
  - Troubleshooting

- [ ] **Migration Guide** (v1 → v2)
  - What changed (project_name → git_url)
  - How to migrate existing projects
  - Breaking changes in MCP tools
  - FAQ

#### 3.2 API Documentation

- [ ] **MCP Tools Reference**
  - All 16 OpenCode tools documented
  - Input schemas
  - Output formats
  - Examples

- [ ] **Architecture Overview**
  - System diagram
  - Data flow
  - Component responsibilities

- [ ] **Developer Guide**
  - Adding new tools
  - Extending managers
  - Testing guidelines

#### 3.3 Troubleshooting Guide

- [ ] **Common Issues**
  - "Port already in use"
  - "SSH key authentication failed"
  - "Project not found"
  - "Worktree creation failed"

- [ ] **Debugging**
  - Enable debug logging
  - Check state files
  - Verify OpenCode API
  - Manual cleanup steps

---

### Task 4: Production Readiness

#### 4.1 Logging & Monitoring

- [ ] Structured logging throughout
  - Manager operations
  - API calls to OpenCode
  - Errors with stack traces

- [ ] Log levels
  - DEBUG: Detailed flow
  - INFO: Operations (start, stop, create)
  - WARNING: Recoverable issues
  - ERROR: Failures requiring attention

#### 4.2 Error Messages

- [ ] User-friendly error messages
  - Clear explanation of what went wrong
  - Suggested fixes
  - Relevant context (git_url, port, etc.)

- [ ] Error codes
  - Categorize errors (AUTH, NETWORK, CONFIG, etc.)
  - Machine-readable error codes
  - Link to documentation

#### 4.3 Performance

- [ ] Optimize StateManager
  - Cache project lookups
  - Lazy load project details
  - Batch state writes

- [ ] Optimize startup time
  - Parallel health checks
  - Async initialization
  - Skip unnecessary validations

#### 4.4 Security

- [ ] File permissions
  - State files: 0600
  - SSH keys: 0600
  - Config files: 0600

- [ ] Secret handling
  - Never log passwords/tokens
  - Secure storage in .env files
  - Clear documentation on secrets

- [ ] Input validation
  - Sanitize git URLs
  - Validate file paths
  - Prevent command injection

---

## Testing Strategy

### Manual Testing Checklist

- [ ] Fresh installation
  - Install on clean system
  - Create first project
  - Verify all tools work

- [ ] Migration testing
  - Start with v1 state files
  - Run migration
  - Verify all projects still work

- [ ] Multi-project testing
  - Start 3+ different repos
  - Create sandboxes in each
  - Verify no cross-contamination

- [ ] Error recovery
  - Kill OpenCode process manually
  - Restart manager
  - Verify cleanup works

### Automated Testing

- [ ] CI/CD integration
  - Run tests on every commit
  - Test on multiple Python versions
  - Test on Linux/macOS

- [ ] Coverage goals
  - Unit tests: >80% coverage
  - Integration tests: critical paths
  - Error handling: all error paths

---

## Success Criteria

Phase 5 is complete when:

1. **All tests pass**
   - Unit tests: >80% coverage
   - Integration tests: all critical workflows
   - Error handling: all edge cases

2. **Documentation complete**
   - User guide published
   - API reference available
   - Migration guide ready

3. **Production ready**
   - Error messages clear
   - Logging comprehensive
   - Performance acceptable

4. **Edge cases handled**
   - Duplicate detection works
   - Port conflicts resolved
   - Orphaned processes cleaned up

---

## Implementation Order

### Week 1: Testing
1. Write unit tests for utils, models
2. Write integration tests for managers
3. Test migration scripts
4. Test error handling

### Week 2: Edge Cases
1. Implement duplicate detection
2. Improve port conflict resolution
3. Add orphaned process cleanup
4. Test edge case handling

### Week 3: Documentation
1. Write user documentation
2. Write API documentation
3. Create troubleshooting guide
4. Record demo videos

### Week 4: Production Readiness
1. Improve logging
2. Polish error messages
3. Security review
4. Performance optimization
5. Final testing & release

---

## Open Questions

1. **Should duplicate detection be automatic or manual?**
   - Option A: Auto-detect on startup, warn user
   - Option B: Manual tool, user runs when needed
   - Recommendation: Manual tool, too invasive to auto-run

2. **Should we support non-GitHub repos?**
   - GitLab, Bitbucket, self-hosted
   - Current: Basic support via URL normalization
   - Future: Add provider-specific helpers

3. **How to handle local-only repos (no remote)?**
   - Use local path as "git_url"
   - Warn that project_id won't be portable
   - Current: Not supported, require git remote

4. **Should we add telemetry?**
   - Track tool usage
   - Error reporting
   - Performance metrics
   - Privacy concerns → probably not

---

## Next Steps

1. Review this plan
2. Prioritize tasks
3. Start with testing (highest ROI)
4. Iterate based on findings

**Status:** Ready to begin Phase 5 implementation.
