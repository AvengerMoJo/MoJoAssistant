# MCP OAuth 2.1 Implementation Plan

## Overview
Implement OAuth 2.1 Resource Server compliance for Claude MCP Connectors per MCP Authorization spec (2025-06-18).

## Required Endpoints

### 1. Protected Resource Metadata Endpoint
**URL**: `/.well-known/oauth-protected-resource`

**Response Format**:
```json
{
  "authorization_servers": [
    "https://your-auth-server.com/.well-known/oauth-authorization-server"
  ]
}
```

### 2. Enhanced MCP Endpoints with OAuth
All existing MCP endpoints must validate Bearer tokens in `Authorization` header.

## Implementation Steps

### Step 1: Add OAuth Dependencies
```bash
pip install PyJWT python-jose[cryptography] python-multipart
```

### Step 2: Create OAuth Validation Module
- Token extraction from Authorization header
- JWT validation (signature, expiry, audience, issuer)
- WWW-Authenticate header generation

### Step 3: Add Protected Resource Metadata Endpoint
- Implement `/.well-known/oauth-protected-resource`
- Return authorization server metadata URL

### Step 4: Enhance Existing MCP Endpoints
- Add token validation to all MCP endpoints
- Return 401/403 for invalid/insufficient tokens

### Step 5: Security Hardening
- HTTPS enforcement
- Secure token handling
- No token passthrough to upstream APIs

## Token Validation Requirements

### Bearer Token Format
```
Authorization: Bearer <access-token>
```

### JWT Claims Validation
- **Signature**: Verify against authorization server public key
- **Expiry (exp)**: Token must not be expired
- **Audience (aud)**: Must match our MCP server URI
- **Issuer (iss)**: Must match our authorization server
- **Scopes**: Check sufficient permissions for requested operation

### Error Responses
- **401 Unauthorized**: Token missing/invalid/expired
- **403 Forbidden**: Insufficient scopes/permissions
- **400 Bad Request**: Malformed authorization request

## Integration with Existing Code

### Modify unified_mcp_server.py
- Add OAuth middleware
- Implement protected resource metadata endpoint
- Enhance all MCP endpoints with token validation

### Enhance mcp_service.py
- Add OAuth validation to API endpoints
- Return proper WWW-Authenticate headers

## Testing Strategy

### 1. MCP Inspector Testing
```bash
git clone https://github.com/modelcontextprotocol/inspector
npm run start
# Point inspector to our OAuth-enabled MCP server
```

### 2. Manual Testing
- Test token validation logic
- Verify WWW-Authenticate headers
- Test error responses

### 3. Claude Desktop Testing
- Configure as custom connector
- Test OAuth flow
- Verify tool access

## Implementation Priority

### Phase 1: Core OAuth Support (Week 1)
1. Add OAuth dependencies
2. Create token validation module
3. Implement protected resource metadata endpoint
4. Add OAuth to HTTP adapter

### Phase 2: MCP Endpoint Integration (Week 2)
1. Enhance STDIO adapter with OAuth
2. Update all MCP endpoints with validation
3. Test with MCP inspector

### Phase 3: Claude Desktop Integration (Week 3)
1. Test OAuth flow with Claude
2. Debug any integration issues
3. Document setup process

## Security Considerations

- All endpoints must be HTTPS
- No access token logging
- Secure token storage
- Regular dependency updates
- No token passthrough to upstream APIs

## Expected Timeline

- **Total Implementation**: 2-3 weeks
- **Core OAuth**: 1 week
- **MCP Integration**: 1 week  
- **Testing & Debugging**: 1 week

This implementation will make MoJoAssistant fully compatible with Claude MCP Connectors while maintaining backward compatibility for non-OAuth clients.