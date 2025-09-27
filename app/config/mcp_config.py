"""
MCP Server configuration loader with environment variable support
"""
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def load_mcp_config() -> Dict[str, Any]:
    """
    Load MCP server configuration from environment variables
    
    Returns:
        Dict containing all MCP configuration
    """
    config: Dict[str, Any] = {}
    
    # Google API Configuration
    config['google_api_key'] = os.getenv("GOOGLE_API_KEY")
    config['google_search_engine_id'] = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
    
    # MCP Server Configuration
    config['mcp_require_auth'] = os.getenv("MCP_REQUIRE_AUTH", "true").lower() == "true"
    config['mcp_api_key'] = os.getenv("MCP_API_KEY")
    
    # Logging Configuration
    config['log_level'] = os.getenv("LOG_LEVEL", "INFO")
    
    # Validate required configurations
    if not config['google_api_key']:
        logger.warning("GOOGLE_API_KEY not set - web search will not work")
    
    if not config['google_search_engine_id']:
        logger.warning("GOOGLE_SEARCH_ENGINE_ID not set - web search will not work")
    
    if not config['mcp_api_key'] and config['mcp_require_auth']:
        logger.warning("MCP_API_KEY not set - authentication will be required but no key available")
    
    logger.info(f"MCP Configuration loaded:")
    logger.info(f"  Google API Key: {'***' if config['google_api_key'] else 'Not set'}")
    logger.info(f"  Search Engine ID: {'***' if config['google_search_engine_id'] else 'Not set'}")
    logger.info(f"  Require Auth: {config['mcp_require_auth']}")
    logger.info(f"  Log Level: {config['log_level']}")
    
    return config

def get_google_api_config() -> tuple[Optional[str], Optional[str]]:
    """
    Get Google API configuration
    
    Returns:
        Tuple of (api_key, search_engine_id)
    """
    config = load_mcp_config()
    return config['google_api_key'], config['google_search_engine_id']

def get_mcp_auth_config() -> tuple[bool, Optional[str]]:
    """
    Get MCP authentication configuration
    
    Returns:
        Tuple of (require_auth, api_key)
    """
    config = load_mcp_config()
    return config['mcp_require_auth'], config['mcp_api_key']

def get_logging_config() -> str:
    """
    Get logging configuration
    
    Returns:
        Log level string
    """
    config = load_mcp_config()
    return config['log_level']