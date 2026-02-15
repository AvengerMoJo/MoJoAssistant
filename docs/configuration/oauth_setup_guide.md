# OAuth 2.1 Setup Guide for Claude Connectors

## Overview

MoJoAssistant uses a **unified configuration system** that supports OAuth 2.1 authentication for Claude Connectors while maintaining backwards compatibility with direct MCP clients. All configuration is managed through environment variables and the unified `app.config.app_config` module.

## Unified Configuration System

MoJoAssistant uses a centralized configuration system located at `app.config.app_config.py` that:

- ✅ **Loads from `.env` file** - All settings in one place
- ✅ **Environment variable override** - Production flexibility
- ✅ **Type validation** - Ensures configuration correctness
- ✅ **Default values** - Works out of the box
- ✅ **Global access** - `get_app_config()` from anywhere

### Configuration Categories

The unified system manages these configuration areas:

1. **Server** - HTTP server settings (`SERVER_HOST`, `SERVER_PORT`, etc.)
2. **OAuth** - OAuth 2.1 authentication (`OAUTH_*` variables)
3. **LLM** - AI model providers (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
4. **Search** - Web search functionality (`GOOGLE_API_KEY`, etc.)
5. **Memory** - Knowledge and embedding system (`EMBEDDING_MODEL`, etc.)
6. **Logging** - Log configuration (`LOG_LEVEL`, etc.)

### Using Configuration in Code

```python
from app.config.app_config import get_app_config

# Get global configuration
config = get_app_config()

# Access OAuth settings
if config.oauth.enabled:
    print(f"OAuth issuer: {config.oauth.issuer}")

# Access server settings
print(f"Server running on {config.server.host}:{config.server.port}")

# Check if features are properly configured
if config.is_oauth_valid():
    print("OAuth is properly configured")

if config.is_search_enabled():
    print("Search functionality is available")
```

## Quick Start

### Option 1: Disabled OAuth (Default - Backwards Compatible)

```bash
# In .env file
OAUTH_ENABLED=false
```

**Endpoints:**
- `POST /` - Original MCP endpoint (no authentication required)
- `GET /health` - Health check

### Option 2: Enable OAuth for Claude Connectors

```bash
# In .env file
OAUTH_ENABLED=true
OAUTH_ISSUER=https://your-auth-provider.com
OAUTH_AUDIENCE=https://your-mcp-server.com
OAUTH_JWKS_URI=https://your-auth-provider.com/.well-known/jwks.json
```

**Endpoints:**
- `POST /` - Original MCP endpoint (backwards compatible)
- `POST /oauth` - OAuth-protected MCP endpoint for Claude Connectors
- `GET /.well-known/oauth-protected-resource` - OAuth 2.1 metadata
- `GET /health` - Health check

## Environment Variables

### Required for OAuth

```bash
OAUTH_ENABLED=true                                    # Enable OAuth 2.1
OAUTH_ISSUER=https://your-auth-provider.com           # OAuth issuer URL
OAUTH_AUDIENCE=https://your-mcp-server.com            # Expected audience
OAUTH_JWKS_URI=https://your-auth-provider.com/.well-known/jwks.json
```

### Optional OAuth Settings

```bash
# Token Validation
OAUTH_VERIFY_SIGNATURE=true
OAUTH_VERIFY_AUDIENCE=true
OAUTH_VERIFY_ISSUER=true
OAUTH_VERIFY_EXP=true

# Scopes
OAUTH_SUPPORTED_SCOPES=mcp:read,mcp:write,mcp:admin
OAUTH_REQUIRED_SCOPE=mcp:read

# Advanced
OAUTH_ALGORITHM=RS256
OAUTH_TOKEN_CACHE_TTL=300
```

## Testing OAuth Setup

### 1. Test OAuth Metadata Endpoint

```bash
curl http://localhost:8000/.well-known/oauth-protected-resource
```

**Expected Response:**
```json
{
  "authorization_servers": [
    "https://your-auth-provider.com/.well-known/oauth-authorization-server"
  ],
  "scopes_supported": ["mcp:read", "mcp:write", "mcp:admin"]
}
```

### 2. Test OAuth-Protected Endpoint

```bash
curl -X POST http://localhost:8000/oauth \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### 3. Test Backwards Compatibility

```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## OAuth Provider Setup Examples

### Using Auth0

```bash
OAUTH_ENABLED=true
OAUTH_ISSUER=https://your-domain.auth0.com/
OAUTH_AUDIENCE=https://your-mcp-server.com
OAUTH_JWKS_URI=https://your-domain.auth0.com/.well-known/jwks.json
```

### Using Google OAuth

```bash
OAUTH_ENABLED=true
OAUTH_ISSUER=https://accounts.google.com
OAUTH_AUDIENCE=your-google-client-id.apps.googleusercontent.com
OAUTH_JWKS_URI=https://www.googleapis.com/oauth2/v3/certs
```

### Development/Testing with JWT.io

For testing purposes, you can use a static secret:

```bash
OAUTH_ENABLED=true
OAUTH_VERIFY_SIGNATURE=true
JWT_SECRET=your-secret-key-for-development
OAUTH_ALGORITHM=HS256
```

## Claude Connectors Integration

Once OAuth is enabled:

1. **Register your MCP server** with Claude Connectors
2. **Provide the OAuth metadata URL**: `https://your-server.com/.well-known/oauth-protected-resource`
3. **Use the OAuth endpoint**: `https://your-server.com/oauth`
4. **Configure scopes**: Typically `mcp:read` and `mcp:write`

## Troubleshooting

### Common Issues

#### 1. "OAuth not enabled" error
- Check `OAUTH_ENABLED=true` in `.env`
- Restart the server after changing config

#### 2. "Invalid token signature" error
- Verify `OAUTH_JWKS_URI` is correct
- Check token is properly formatted JWT
- Ensure clock sync between systems

#### 3. "Invalid audience" error
- Check `OAUTH_AUDIENCE` matches token `aud` claim
- Verify OAuth provider audience configuration

#### 4. "Insufficient scope" error
- Check token contains required scopes
- Verify `OAUTH_REQUIRED_SCOPE` configuration

### Debug Logging

Enable debug logging to troubleshoot OAuth issues:

```bash
LOG_LEVEL=DEBUG
```

## Security Best Practices

1. **Always use HTTPS** in production
2. **Validate all JWT claims** (signature, audience, issuer, expiry)
3. **Use short token lifetimes** (< 1 hour)
4. **Rotate signing keys** regularly
5. **Monitor token usage** for anomalies
6. **Never log access tokens**

## Migration Guide

### From Direct MCP to OAuth

1. **Phase 1**: Enable OAuth with `OAUTH_ENABLED=true`
2. **Phase 2**: Test both endpoints work (`/` and `/oauth`)
3. **Phase 3**: Configure Claude Connectors to use `/oauth`
4. **Phase 4**: Monitor logs for successful OAuth authentication

**No downtime required** - backwards compatibility maintained.