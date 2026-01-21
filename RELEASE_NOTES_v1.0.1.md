# MoJoAssistant v1.0.1 Release Notes

**Release Date:** 2026-01-21
**Previous Version:** v1.0.0-beta1

---

## Mission Statement

**Added funding.json to MoJoAssistant** — an open-source, local-first AI proxy protecting human agency & privacy from scams and manipulation. Seeking community support for safety-focused core development and acceleration.

→ **GitHub:** https://github.com/AvengerMoJo/MoJoAssistant
→ **Support:** https://github.com/sponsors/AvengerMoJo

**#FOSS #AISafety #DigitalSovereignty**

---

## What is MoJoAssistant?

MoJoAssistant is a **local-first AI system** that runs entirely on your device, protecting your privacy, agency, and decision-making from public AI risks. It features:

- **Local Memory (MCP)** - Your data stays on your machine
- **Multi-Model Embeddings** - Diverse knowledge representation
- **Adversarial Verification** - Cross-check AI outputs for safety
- **Pedagogical Explainability** - Understand how decisions are made
- **Digital Self-Reliance** - Control your own AI infrastructure

---

## Highlights in v1.0.1

### Community & Sustainability
- **Funding Support Added** - Published `funding.json` with GitHub Sponsors and Ethereum donation channels
- Seeking support for safety-focused core development and feature acceleration
- Open to grants, recurring contributions, and direct arrangements

### Security & Privacy Enhancements
- **OAuth 2.1 Authorization Server** - Secure authentication for Claude Connectors with PKCE flow
- **SSH Key Protection** - Prevents hanging on passphrased keys with timeout detection (10min clone, 5min update)
- **JWT Token Validation** - Signature verification ensures only valid OAuth tokens are accepted

### Critical Bug Fixes
- **Multi-Model Memory Search** - Fixed `MULTI_MODEL_ENABLED=true` being ignored; stored knowledge now accessible
- **Async MCP Tool Calls** - Memory search now works properly when called from MCP protocol
- **Configuration Handling** - Services now properly normalize AppConfig objects to dict format
- **OAuth Middleware Logic** - Fixed loading conditions for `MCP_REQUIRE_AUTH` compatibility

### Developer Experience
- **uv Virtual Environment** - Added compatibility for modern Python environment tools
- **Installation Improvements** - Fixed issues blocking new users from setup
- **Comprehensive Documentation** - Added system-wide documentation for contributors

---

## Technical Details

### Added
- SSH key passphrase detection and timeout protection for git operations
- OAuth 2.1 Authorization Server for Claude Connectors with PKCE flow
- `MCP_REQUIRE_AUTH` configuration support for controlling authentication
- JWT token validation with signature verification
- Funding support via GitHub Sponsors and Ethereum wallet

### Changed
- Unified MCP server configuration handling to support both AppConfig and dict objects
- Enhanced OAuth middleware loading logic
- Improved configuration normalization across all services
- Moved `funding.json` from `docs/` to project root for better visibility

### Fixed
- Multi-model memory search activation (`MULTI_MODEL_ENABLED` now properly recognized)
- SSH key hanging during git operations (timeout and passphrase detection added)
- OAuth/`MCP_REQUIRE_AUTH` logic (middleware loads only when properly configured)
- Async MCP tool calls for memory search
- OAuth token type mismatch (user_id vs Bearer token)
- `remove_document` method bugs in memory services
- `add_conversation` functionality to properly store and retrieve conversations

### Security
- SSH key validation before repository registration prevents hanging on passphrased keys
- JWT signature verification ensures only valid OAuth tokens are accepted
- OAuth PKCE (Proof Key for Code Exchange) flow prevents authorization code interception
- Configuration sensitive data properly handled via environment variables

### Performance
- Multi-model memory now uses all three embedding models (bge-m3:1024, gemma:768, gemma:256) in parallel
- Embedding caching reduces redundant computation
- Async processing prevents blocking during memory searches

---

## Migration Notes

- **No database migration required** - Existing knowledge base and conversations preserved
- **OAuth Configuration** - Update `.env` to enable OAuth when ready:
  ```bash
  OAUTH_ENABLED=true
  OAUTH_ISSUER=https://your-oauth-provider.com
  OAUTH_AUDIENCE=https://your-app.com
  ```
- **SSH Keys** - If you experience git hanging, remove passphrases:
  ```bash
  ssh-keygen -p -f ~/.ssh/id_rsa
  ```

---

## How to Support

MoJoAssistant is maintained solo by an independent open-source developer. Your support enables:
- Continued development of safety features
- Multi-model memory system enhancements
- Adversarial verification improvements
- Educational tools for digital sovereignty

**Ways to Contribute:**
- **GitHub Sponsors:** https://github.com/sponsors/AvengerMoJo
- **Ethereum (Base):** `0x338A9C508F10509151B371f5227f7FFf7cF445D0`
- **Other Arrangements:** Contact AvengerMoJo@gmail.com

---

## Thank You

This release represents a step toward sustainable open-source development for AI safety. Thank you to everyone who has contributed feedback, bug reports, and encouragement.

**Together, we protect human agency in the age of AI.**

---

**Full Changelog:** See [CHANGELOG.md](CHANGELOG.md) for complete technical details.
