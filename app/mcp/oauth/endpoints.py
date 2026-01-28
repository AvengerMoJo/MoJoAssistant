"""
OAuth 2.1 Authorization Server Endpoints
Implements authorization code flow with PKCE for chatmcp compatibility
"""
import os
from typing import Optional
from urllib.parse import urlencode, urlparse
from fastapi import APIRouter, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .models import (
    AuthorizationServerMetadata,
    TokenResponse,
    OAuthError
)
from .storage import (
    get_authorization_code_store,
    get_token_store,
    get_client_registration_store,
    AuthorizationCodeData,
    AccessTokenData
)
from .pkce import verify_code_challenge, is_valid_code_verifier
from app.config.app_config import get_app_config
from app.config.logging_config import get_logger

logger = get_logger(__name__)

# Create router for OAuth endpoints
router = APIRouter(prefix="", tags=["oauth"])

# Setup templates
template_dir = Path(__file__).parent / "templates"
template_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(template_dir))


def get_base_url(request: Request) -> str:
    """
    Get base URL for authorization server from request

    Note: This is for OUR authorization server's issuer URL.
    The OAUTH_ISSUER config is for validating EXTERNAL tokens (e.g., from Claude),
    so we construct our server's URL from the request instead.
    """
    return f"{request.url.scheme}://{request.url.netloc}"


def validate_redirect_uri(redirect_uri: str) -> bool:
    """
    Validate redirect URI for security

    Args:
        redirect_uri: The redirect URI to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        parsed = urlparse(redirect_uri)
        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False
        # Block suspicious schemes
        if parsed.scheme not in ["http", "https", "app"]:
            return False
        return True
    except Exception:
        return False


def is_api_key_valid(api_key: Optional[str]) -> bool:
    """Check if API key is valid (for API key compatibility mode)"""
    if not api_key:
        return False
    mcp_api_key = os.getenv("MCP_API_KEY")
    return mcp_api_key and api_key == mcp_api_key


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request) -> JSONResponse:
    """
    OAuth 2.1 Authorization Server Metadata Discovery (RFC 8414)

    This endpoint allows clients like chatmcp to auto-discover OAuth endpoints

    Returns:
        Authorization server metadata JSON
    """
    config = get_app_config()

    if not config.oauth.enabled or not config.oauth.enable_authorization_server:
        raise HTTPException(
            status_code=501,
            detail="OAuth Authorization Server is not enabled"
        )

    base_url = get_base_url(request)

    metadata = AuthorizationServerMetadata(
        issuer=base_url,
        authorization_endpoint=f"{base_url}/oauth/authorize",
        token_endpoint=f"{base_url}/oauth/token",
        registration_endpoint=f"{base_url}/oauth/register",  # Dynamic Client Registration
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["none"],  # Public client support
        scopes_supported=config.oauth.supported_scopes
    )

    logger.info("OAuth metadata requested from discovery endpoint")
    return JSONResponse(content=metadata.model_dump())


@router.get("/oauth/authorize")
async def oauth_authorize_get(
    request: Request,
    response_type: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: Optional[str] = None,
    client_id: Optional[str] = None
) -> HTMLResponse:
    """
    OAuth 2.1 Authorization Endpoint (GET)

    Displays consent page for user authorization

    Parameters:
        response_type: Must be "code"
        redirect_uri: Client redirect URI
        state: CSRF protection state
        code_challenge: PKCE code challenge
        code_challenge_method: Must be "S256"
        scope: Optional requested scopes (default: "mcp:read mcp:write")
        client_id: Optional client identifier (public client support)

    Returns:
        HTML consent page
    """
    config = get_app_config()

    # Validate OAuth is enabled
    if not config.oauth.enabled or not config.oauth.enable_authorization_server:
        raise HTTPException(
            status_code=501,
            detail="OAuth Authorization Server is not enabled"
        )

    # Validate parameters
    if response_type != "code":
        error_params = urlencode({
            "error": "unsupported_response_type",
            "error_description": "Only 'code' response type is supported",
            "state": state
        })
        return RedirectResponse(url=f"{redirect_uri}?{error_params}")

    if code_challenge_method != "S256":
        error_params = urlencode({
            "error": "invalid_request",
            "error_description": "Only 'S256' code challenge method is supported",
            "state": state
        })
        return RedirectResponse(url=f"{redirect_uri}?{error_params}")

    if not validate_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=400,
            detail="Invalid redirect_uri"
        )

    # Default scope
    if not scope:
        scope = "mcp:read mcp:write"

    # Parse scopes
    requested_scopes = scope.split()

    # Check for API key in query or session for auto-approval
    api_key = request.query_params.get("api_key")
    if config.oauth.auto_approve and config.oauth.api_key_mode:
        if is_api_key_valid(api_key):
            # Auto-approve for valid API key
            logger.info("Auto-approving authorization for valid API key")
            return await oauth_authorize_approve(
                request=request,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                auto_approved=True
            )

    # Show consent page
    logger.info(f"Showing authorization consent page for scopes: {requested_scopes}")
    return templates.TemplateResponse("authorize.html", {
        "request": request,
        "client_id": client_id or "MCP Client",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "scopes": requested_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method
    })


@router.post("/oauth/authorize")
async def oauth_authorize_post(
    request: Request,
    action: str = Form(...),
    client_id: Optional[str] = Form(None),
    redirect_uri: str = Form(...),
    scope: str = Form(...),
    state: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...)
) -> RedirectResponse:
    """
    OAuth 2.1 Authorization Endpoint (POST)

    Processes user consent (allow/deny)

    Parameters:
        action: "allow" or "deny"
        client_id: Optional client identifier
        redirect_uri: Client redirect URI
        scope: Requested scopes
        state: CSRF protection state
        code_challenge: PKCE code challenge
        code_challenge_method: PKCE method ("S256")

    Returns:
        Redirect to client with authorization code or error
    """
    if action == "deny":
        # User denied authorization
        logger.info("User denied authorization request")
        error_params = urlencode({
            "error": "access_denied",
            "error_description": "User denied the authorization request",
            "state": state
        })
        return RedirectResponse(url=f"{redirect_uri}?{error_params}")

    # User approved - generate authorization code
    return await oauth_authorize_approve(
        request=request,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        auto_approved=False
    )


async def oauth_authorize_approve(
    request: Request,
    client_id: Optional[str],
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    auto_approved: bool = False
) -> RedirectResponse:
    """
    Internal helper to approve authorization and generate code

    Args:
        All authorization parameters
        auto_approved: Whether this was auto-approved (for logging)

    Returns:
        Redirect with authorization code
    """
    config = get_app_config()

    # Create authorization code
    code_store = get_authorization_code_store()
    code_data = code_store.create(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        ttl=config.oauth.authorization_code_ttl
    )

    approval_type = "Auto-approved" if auto_approved else "User approved"
    logger.info(f"{approval_type} authorization request, generated code: {code_data.code[:16]}...")

    # Redirect back to client with authorization code
    callback_params = urlencode({
        "code": code_data.code,
        "state": state
    })
    return RedirectResponse(url=f"{redirect_uri}?{callback_params}")


@router.post("/oauth/register")
async def oauth_register_client(request: Request) -> JSONResponse:
    """
    OAuth 2.0 Dynamic Client Registration (RFC 7591)

    Allows clients like Claude to dynamically register themselves

    Expected request body:
    {
        "client_name": "Claude",
        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"]
    }

    Returns:
        Client registration response with client_id
    """
    config = get_app_config()

    if not config.oauth.enabled or not config.oauth.enable_authorization_server:
        raise HTTPException(
            status_code=501,
            detail="OAuth Authorization Server is not enabled"
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in request body"
        )

    # Validate required fields
    client_name = body.get("client_name", "Unknown Client")
    redirect_uris = body.get("redirect_uris", [])
    grant_types = body.get("grant_types", ["authorization_code"])
    response_types = body.get("response_types", ["code"])
    scope = body.get("scope", " ".join(config.oauth.supported_scopes))

    if not redirect_uris:
        raise HTTPException(
            status_code=400,
            detail="redirect_uris is required"
        )

    # Register the client
    client_store = get_client_registration_store()
    client = client_store.register_client(
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        scope=scope
    )

    logger.info(f"Registered new OAuth client: {client_name} (ID: {client.client_id})")

    # Return registration response (RFC 7591)
    registration_response = {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "token_endpoint_auth_method": "none",  # Public client
    }

    return JSONResponse(content=registration_response, status_code=201)


@router.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None)
) -> JSONResponse:
    """
    OAuth 2.1 Token Endpoint

    Exchanges authorization code for access token (with PKCE verification)
    Or refreshes access token using refresh token

    Parameters:
        grant_type: "authorization_code" or "refresh_token"
        code: Authorization code (for authorization_code grant)
        redirect_uri: Redirect URI (must match authorization request)
        code_verifier: PKCE code verifier (for PKCE verification)
        refresh_token: Refresh token (for refresh_token grant)
        client_id: Optional client identifier
        client_secret: Optional client secret

    Returns:
        JSON token response with access_token, refresh_token, expires_in
    """
    config = get_app_config()

    if not config.oauth.enabled or not config.oauth.enable_authorization_server:
        raise HTTPException(
            status_code=501,
            detail="OAuth Authorization Server is not enabled"
        )

    if grant_type == "authorization_code":
        return await handle_authorization_code_grant(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            client_id=client_id,
            config=config
        )
    elif grant_type == "refresh_token":
        return await handle_refresh_token_grant(
            refresh_token=refresh_token,
            client_id=client_id,
            config=config
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported grant_type"
        )


async def handle_authorization_code_grant(
    code: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str],
    client_id: Optional[str],
    config
) -> JSONResponse:
    """Handle authorization_code grant type"""

    if not code or not redirect_uri or not code_verifier:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: code, redirect_uri, code_verifier"
        )

    # Get authorization code
    code_store = get_authorization_code_store()
    code_data = code_store.get(code)

    if not code_data:
        logger.warning("Invalid authorization code provided")
        raise HTTPException(
            status_code=400,
            detail="Invalid authorization code"
        )

    # Validate code is not expired or used
    if not code_data.is_valid():
        logger.warning("Authorization code expired or already used")
        raise HTTPException(
            status_code=400,
            detail="Authorization code expired or already used"
        )

    # Validate redirect URI matches
    if code_data.redirect_uri != redirect_uri:
        logger.warning("Redirect URI mismatch")
        raise HTTPException(
            status_code=400,
            detail="Redirect URI mismatch"
        )

    # Validate client_id matches (if provided)
    if code_data.client_id and client_id and code_data.client_id != client_id:
        logger.warning("Client ID mismatch")
        raise HTTPException(
            status_code=400,
            detail="Client ID mismatch"
        )

    # Validate code verifier (PKCE)
    if not is_valid_code_verifier(code_verifier):
        logger.warning("Invalid code verifier format")
        raise HTTPException(
            status_code=400,
            detail="Invalid code_verifier format"
        )

    if not verify_code_challenge(code_verifier, code_data.code_challenge, code_data.code_challenge_method):
        logger.warning("PKCE verification failed")
        raise HTTPException(
            status_code=400,
            detail="Code verifier does not match code challenge"
        )

    # Mark code as used
    code_store.mark_used(code)

    # Generate access token and refresh token
    token_store = get_token_store()
    token_data = token_store.create_access_token(
        client_id=code_data.client_id,
        scope=code_data.scope,
        ttl=config.oauth.access_token_ttl,
        create_refresh_token=True,
        refresh_token_ttl=config.oauth.refresh_token_ttl
    )

    logger.info(f"Issued access token for scope: {code_data.scope}")

    # Return token response
    response = TokenResponse(
        access_token=token_data.token,
        token_type="Bearer",
        expires_in=token_data.get_expires_in(),
        refresh_token=token_data.refresh_token,
        scope=code_data.scope
    )

    return JSONResponse(content=response.model_dump())


async def handle_refresh_token_grant(
    refresh_token: Optional[str],
    client_id: Optional[str],
    config
) -> JSONResponse:
    """Handle refresh_token grant type"""

    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameter: refresh_token"
        )

    # Get refresh token
    token_store = get_token_store()
    refresh_data = token_store.get_refresh_token(refresh_token)

    if not refresh_data:
        logger.warning("Invalid refresh token provided")
        raise HTTPException(
            status_code=400,
            detail="Invalid refresh token"
        )

    # Validate client_id matches (if provided)
    if refresh_data.client_id and client_id and refresh_data.client_id != client_id:
        logger.warning("Client ID mismatch for refresh token")
        raise HTTPException(
            status_code=400,
            detail="Client ID mismatch"
        )

    # Generate new access token (keep same refresh token)
    new_token_data = token_store.create_access_token(
        client_id=refresh_data.client_id,
        scope=refresh_data.scope,
        ttl=config.oauth.access_token_ttl,
        create_refresh_token=False  # Keep existing refresh token
    )

    logger.info(f"Refreshed access token for scope: {refresh_data.scope}")

    # Return token response
    response = TokenResponse(
        access_token=new_token_data.token,
        token_type="Bearer",
        expires_in=new_token_data.get_expires_in(),
        refresh_token=refresh_token,  # Return same refresh token
        scope=refresh_data.scope
    )

    return JSONResponse(content=response.model_dump())
