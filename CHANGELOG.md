# Changelog

All notable changes to the MoJoAssistant project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

