# Changelog

> **Note (2026-02):** The `opencode_*` and `claude_code_*` tool names referenced in this document have been replaced by unified `agent_*` tools (`agent_start`, `agent_stop`, `agent_status`, `agent_list`, `agent_restart`, `agent_destroy`, `agent_action`, `agent_list_types`). This document is preserved for historical reference.

All notable changes to the MoJoAssistant project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.4-beta] - 2026-02-23

### Added
- **Dreaming Pipeline (A→B→C→D)**: Four-stage autonomous memory consolidation — raw conversations → semantic chunks → synthesized clusters → versioned archives
- Resilient LLM JSON parsing with four-pass strategy for handling malformed output from local LLMs
- Versioned archives with incremental `archive_v<N>.json` files and manifest tracking under `~/.memory/dreams/`
- Scheduler-driven automation: nightly dreaming tasks at 3:00 AM (off-peak)
- MCP tool enhancements returning versioning and lifecycle metadata
- Coding agent policies: `AGENTS.md` and `Coding Agents Rules.md`
- LM Studio integration documentation and authentication configuration

### Fixed
- Removed hardcoded version numbers in dreaming module
- Fixed failure handling in dreaming pipeline stages
- Fixed scheduler task rescheduling after completion
- Fixed thread safety in scheduler daemon
- Fixed archive version detection for existing conversations

## [1.1.3-beta] - 2026-02-21

### Added
- **Smart Installer with AI Agents**: Conversational setup using Model Selector and Environment Configurator agents
- **Tool-Based Configuration**: LLM uses structured tool calls instead of free-text to configure `.env` values
- Comprehensive environment variable documentation (60+ variables in `config/env_variables.json`)
- Model catalog system with curated model metadata in `config/model_catalog.json`
- **LMStudio Integration**: Multi-port detection and API token support (`LMSTUDIO_API_KEY`)
- 5 predefined use case profiles for configuration

### Changed
- Directory reorganization: 42 files moved to proper structure
- Default recommended model changed from Qwen2.5-Coder to Qwen3-1.7B

### Fixed
- Context length handling in model configuration
- Model selection when multiple providers are available
- LLM API error handling during configuration
- Installer crash on missing dependencies
- Mirror configuration for China-region users
- Resume support for interrupted model downloads

## [1.1.0] - 2026-02-09

### Added
- **OpenCode Manager**: Production-ready AI agent orchestration layer
- N:1 architecture — multiple OpenCode instances route through single global MCP tool (port 3005)
- SSH deploy key management with per-project auto-generation
- Global configuration via `~/.memory/opencode-manager.env`
- State persistence across system restarts
- Health monitoring with auto-recovery
- 10 comprehensive automated tests

### Changed
- OpenCode Manager promoted from beta to production-ready status
- Enhanced process lifecycle management with cleaner shutdown handling

## [1.1.0-beta] - 2026-02-07

### Added
- **OpenCode Manager (N:1 Architecture)**: Lifecycle management for OpenCode AI coding agent instances
- Multi-project support with simultaneous instance management
- Global MCP tool on single port (3005) routing to all projects
- Per-project SSH deploy keys (auto-generated ED25519)
- Global password configuration via `~/.memory/opencode-manager.env`
- Development mode with auto-reload support
- 8/8 automated tests passing
- Comprehensive documentation (10+ markdown files)

### Fixed
- PID tracking to capture actual process instead of wrapper
- `active_project_count` when restarting stopped projects
- `opencode_llm_config` to include built-in provider models
- Hot reload with watchfiles alternative
- Port reuse on project restart
- MCP tool startup race condition

## [1.0.1] - 2026-01-21

### Added
- SSH key passphrase detection and timeout protection for git operations
- OAuth 2.1 Authorization Server for Claude Connectors with PKCE flow
- MCP_REQUIRE_AUTH configuration support for controlling authentication
- JWT token validation with signature verification
- Funding support via GitHub Sponsors and Ethereum wallet

### Changed
- Unified MCP server configuration handling to support both AppConfig and dict objects
- Fixed multi-model memory search activation (MULTI_MODEL_ENABLED)
- Enhanced OAuth middleware loading logic
- Improved configuration normalization across all services
- Moved funding.json from docs/ to project root

### Fixed
- **Multi-model memory search** - MULTI_MODEL_ENABLED=true was being ignored due to config type mismatch. Now properly activated and your stored knowledge is accessible via get_memory_context()
- **SSH key hanging** - Git operations now detect passphrased keys and apply timeouts (10min clone, 5min update) to prevent indefinite blocking
- **OAuth/MCP_REQUIRE_AUTH logic** - OAuth middleware now only loads when both OAUTH_ENABLED=true and either MCP_REQUIRE_AUTH=false or OAuth is properly configured (has issuer+audience)
- **Async MCP tool calls** - Fixed memory search not working when called from MCP protocol
- **Configuration handling** - Services now properly normalize AppConfig objects to dict format
- **OAuth token type mismatch** - Fixed issue where OAuth user_id was passed as auth_token instead of Bearer token

### Security
- SSH key validation before repository registration prevents hanging on passphrased keys
- JWT signature verification ensures only valid OAuth tokens are accepted
- OAuth PKCE (Proof Key for Code Exchange) flow prevents authorization code interception
- Configuration sensitive data properly handled via environment variables

### Performance
- Multi-model memory now uses all three embedding models (bge-m3:1024, gemma:768, gemma:256) in parallel
- Embedding caching reduces redundant computation
- Async processing prevents blocking during memory searches

### Migration Notes
- No database migration required
- Existing knowledge base and conversations preserved
- Update .env to enable OAuth when ready:
  ```bash
  OAUTH_ENABLED=true
  OAUTH_ISSUER=https://your-oauth-provider.com
  OAUTH_AUDIENCE=https://your-app.com
  ```
- SSH keys: Remove passphrases with `ssh-keygen -p -f ~/.ssh/id_rsa`

## [1.0.0] - 2025-09-23

### Added
- Initial MCP Server with unified STDIO and HTTP protocol support
- Multi-model embedding system with BAAI/bge-m3 and Google embeddinggemma-300m
- Four-tier memory architecture (working, active, archival, knowledge)
- Google Custom Search API integration

