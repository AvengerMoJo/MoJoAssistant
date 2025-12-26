# MCP OAuth 2.1 Implementation Plan

## Overview
Implement OAuth 2.1 compliance for Claude MCP Connectors per MCP Authorization specs.

**Two Implementation Options Available:**
1. **Option A**: OAuth 2.1 Resource Server (Simpler approach)
2. **Option B**: Third-party Authorization Flow (Advanced approach)

## Option A: OAuth 2.1 Resource Server (Recommended)
Implement basic OAuth 2.1 Resource Server compliance per 2025-06-18 spec.

## Option B: Third-party Authorization Flow (Advanced)
Implement sophisticated third-party authorization per 2025-03-26 spec Section 2.10.

## Option A: OAuth 2.1 Resource Server (Simple)

### Required Endpoints

#### 1. Protected Resource Metadata Endpoint
**URL**: `/.well-known/oauth-protected-resource`

**Response Format**:
```json
{
  "authorization_servers": [
    "https://your-auth-server.com/.well-known/oauth-authorization-server"
  ]
}
```

#### 2. Enhanced MCP Endpoints with OAuth
All existing MCP endpoints must validate Bearer tokens in `Authorization` header.

## Option B: Third-party Authorization Flow (Advanced)

### How It Works
The MCP server acts as both:
- **OAuth Client**: To external authorization servers (Google, GitHub, etc.)
- **OAuth Authorization Server**: To MCP clients

### Flow Overview
1. MCP client requests authorization from our MCP server
2. Our MCP server redirects user to third-party auth server (e.g., GitHub)
3. User authorizes with third-party server
4. Third-party server returns authorization code to our MCP server
5. Our MCP server exchanges code for third-party access token
6. Our MCP server generates its own token bound to third-party session
7. Our MCP server completes OAuth flow with original MCP client

### Advanced Requirements
- **Session Binding**: Secure mapping between third-party tokens and MCP tokens
- **Token Lifecycle Management**: Handle third-party token expiration/renewal
- **Dual OAuth Implementation**: Act as both client and authorization server
- **Complex Token Chaining**: Manage token relationships between systems

## Implementation Approach Comparison

| Aspect | Option A: Resource Server | Option B: Third-party Flow |
|--------|---------------------------|---------------------------|
| **Complexity** | Low | High |
| **Development Time** | 1-2 weeks | 3-4 weeks |
| **External Dependencies** | OAuth provider required | None (self-contained) |
| **User Experience** | Standard OAuth flow | Seamless (uses existing accounts) |
| **Token Management** | Simple JWT validation | Complex token chaining |
| **Security** | Standard OAuth 2.1 | Advanced token binding |
| **Maintenance** | Low | High |

## Implementation Steps

### Option A: Resource Server (Recommended for Start)

#### Step 1: Add OAuth Dependencies
```bash
pip install PyJWT python-jose[cryptography] python-multipart
```

#### Step 2: Create OAuth Validation Module
- Token extraction from Authorization header
- JWT validation (signature, expiry, audience, issuer)
- WWW-Authenticate header generation

#### Step 3: Add Protected Resource Metadata Endpoint
- Implement `/.well-known/oauth-protected-resource`
- Return authorization server metadata URL

#### Step 4: Enhance Existing MCP Endpoints
- Add token validation to all MCP endpoints
- Return 401/403 for invalid/insufficient tokens

#### Step 5: Security Hardening
- HTTPS enforcement
- Secure token handling
- No token passthrough to upstream APIs

### Option B: Third-party Authorization Flow

#### Step 1: Dual OAuth Implementation
- Implement OAuth client for third-party servers
- Implement OAuth authorization server for MCP clients
- Handle PKCE for all clients (REQUIRED)

#### Step 2: Session Binding System
- Secure token mapping between third-party and MCP tokens
- Token lifecycle management
- Third-party token validation

#### Step 3: Complex Flow Implementation
- Redirect handling for third-party authorization
- Authorization code exchange
- Token generation and binding

#### Step 4: Advanced Security
- Redirect URI validation (HTTPS or localhost only)
- Secure credential storage
- Session timeout handling
- Token chaining security analysis

#### Step 5: Dynamic Client Registration
- Implement RFC 7591 for automatic client registration
- Support PKCE for all clients
- Token rotation implementation

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

### Option A: Resource Server Integration

#### Modify unified_mcp_server.py
- Add OAuth middleware
- Implement protected resource metadata endpoint
- Enhance all MCP endpoints with token validation

#### Enhance mcp_service.py
- Add OAuth validation to API endpoints
- Return proper WWW-Authenticate headers

### Option B: Third-party Flow Integration

#### Modify unified_mcp_server.py
- Implement dual OAuth system (client + authorization server)
- Add third-party authorization redirect handling
- Implement session binding system
- Add token chaining logic

#### Create New Modules
- `oauth_client.py`: Handle third-party OAuth flows
- `oauth_server.py`: Handle MCP client authorization
- `session_binding.py`: Manage token relationships
- `token_manager.py`: Complex token lifecycle management

## Testing Strategy

### Option A: Resource Server Testing

#### 1. MCP Inspector Testing
```bash
git clone https://github.com/modelcontextprotocol/inspector
npm run start
# Point inspector to our OAuth-enabled MCP server
```

#### 2. OAuth Provider Testing
- Test with Auth0, Google, GitHub OAuth providers
- Verify token validation logic
- Test token expiry and refresh

#### 3. Claude Desktop Testing
- Configure as custom connector
- Test OAuth flow
- Verify tool access

### Option B: Third-party Flow Testing

#### 1. Complex Flow Testing
- Test third-party authorization redirect
- Verify session binding between tokens
- Test token lifecycle management

#### 2. Security Testing
- Validate redirect URI security
- Test token chaining vulnerabilities
- Verify PKCE implementation

#### 3. Integration Testing
- Test with multiple third-party providers
- Verify dynamic client registration
- Test token rotation

## Implementation Priority Recommendations

### Recommended: Start with Option A (Resource Server)

#### Phase 1: Core OAuth Support (1-2 weeks)
1. Add OAuth dependencies
2. Create token validation module
3. Implement protected resource metadata endpoint
4. Add OAuth to HTTP adapter

#### Phase 2: MCP Endpoint Integration (1 week)
1. Enhance STDIO adapter with OAuth
2. Update all MCP endpoints with validation
3. Test with MCP inspector

#### Phase 3: Claude Desktop Integration (1 week)
1. Test OAuth flow with Claude
2. Debug any integration issues
3. Document setup process

### Alternative: Option B (Advanced) - Future Phase

#### Phase 1: OAuth Foundation (2 weeks)
1. Implement OAuth client for third-party servers
2. Implement OAuth authorization server
3. Add PKCE support

#### Phase 2: Session Binding (1-2 weeks)
1. Implement token mapping system
2. Add token lifecycle management
3. Test with single third-party provider

#### Phase 3: Advanced Features (1 week)
1. Dynamic client registration
2. Token rotation
3. Multi-provider support

## Security Considerations

### Option A: Resource Server
- All endpoints must be HTTPS
- No access token logging
- Secure token storage
- Regular dependency updates
- No token passthrough to upstream APIs

### Option B: Third-party Flow
- All Option A security measures
- Redirect URI validation (HTTPS/localhost only)
- Secure third-party credential storage
- Session timeout handling
- Token chaining security analysis

## Expected Timeline

### Option A: Resource Server
- **Total Implementation**: 2-3 weeks
- **Core OAuth**: 1-2 weeks
- **MCP Integration**: 1 week  
- **Testing & Debugging**: 1 week

### Option B: Third-party Flow
- **Total Implementation**: 4-6 weeks
- **OAuth Foundation**: 2-3 weeks
- **Session Binding**: 2 weeks
- **Advanced Features**: 1-2 weeks

This implementation will make MoJoAssistant fully compatible with Claude MCP Connectors while maintaining backward compatibility for non-OAuth clients.

## Recommendation

### **Start with Option A: OAuth 2.1 Resource Server**

**Reasons:**
1. **Faster Time to Market**: 2-3 weeks vs 4-6 weeks
2. **Proven Pattern**: Standard OAuth 2.1 implementation
3. **Easier Maintenance**: Simpler architecture
4. **Lower Risk**: Fewer moving parts to break
5. **Immediate Compatibility**: Works with existing OAuth providers

**Future Enhancement:**
After Option A is working, you can optionally implement Option B for users who want seamless integration with their existing accounts (GitHub, Google, etc.) without separate OAuth setup.

### **Implementation Decision Matrix**

Choose **Option A** if:
- ✅ You want Claude compatibility quickly
- ✅ You have access to OAuth providers (Auth0, Google, etc.)
- ✅ You prefer simpler maintenance
- ✅ You want lower implementation risk

Consider **Option B** if:
- 🔄 You need seamless user experience (no separate OAuth setup)
- 🔄 You want to support multiple third-party providers
- 🔄 You have time for more complex implementation
- 🔄 You want advanced token management features

### **Quick Start Recommendation**
1. **Week 1-2**: Implement Option A (Resource Server)
2. **Week 3**: Test with Claude Desktop
3. **Future**: Consider Option B if user feedback indicates need for seamless third-party integration