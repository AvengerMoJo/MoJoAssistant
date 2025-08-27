"""
Configuration loader with environment variable support for MoJoAssistant
"""
import os
import json
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

def load_embedding_config(config_file: str = "config/embedding_config.json") -> Dict[str, Any]:
    """
    Load embedding model configuration with environment variable support
    
    Environment variables take precedence over config file values:
    - OPENAI_API_KEY: OpenAI API key
    - COHERE_API_KEY: Cohere API key  
    - EMBEDDING_MODEL: Default embedding model name
    - EMBEDDING_BACKEND: Default embedding backend
    - EMBEDDING_DEVICE: Default device (cpu/cuda)
    """
    try:
        # Load base configuration from file
        config = _load_base_config(config_file)
        
        # Override with environment variables
        config = _apply_env_overrides(config)
        
        # Validate configuration
        _validate_config(config)
        
        return config
        
    except Exception as e:
        logger.error(f"Failed to load embedding configuration: {e}")
        return _get_fallback_config()

def _load_base_config(config_file: str) -> Dict[str, Any]:
    """Load base configuration from JSON file"""
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            return json.load(f)
    else:
        # Create default config if it doesn't exist
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        default_config = _get_default_config()
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"Created default configuration at {config_file}")
        return default_config

def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to configuration"""
    
    # Override API keys from environment variables
    if "openai" in config.get("embedding_models", {}):
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            config["embedding_models"]["openai"]["api_key"] = openai_key
            logger.info("Using OpenAI API key from environment variable")
    
    if "cohere" in config.get("embedding_models", {}):
        cohere_key = os.getenv("COHERE_API_KEY")
        if cohere_key:
            config["embedding_models"]["cohere"]["api_key"] = cohere_key
            logger.info("Using Cohere API key from environment variable")
    
    # Override default model settings
    embedding_model = os.getenv("EMBEDDING_MODEL")
    if embedding_model and "default" in config.get("embedding_models", {}):
        config["embedding_models"]["default"]["model_name"] = embedding_model
        logger.info(f"Using embedding model from environment: {embedding_model}")
    
    embedding_backend = os.getenv("EMBEDDING_BACKEND")
    if embedding_backend and "default" in config.get("embedding_models", {}):
        config["embedding_models"]["default"]["backend"] = embedding_backend
        logger.info(f"Using embedding backend from environment: {embedding_backend}")
    
    embedding_device = os.getenv("EMBEDDING_DEVICE")
    if embedding_device and "default" in config.get("embedding_models", {}):
        config["embedding_models"]["default"]["device"] = embedding_device
        logger.info(f"Using embedding device from environment: {embedding_device}")
    
    # Override memory settings
    data_dir = os.getenv("MEMORY_DATA_DIR")
    if data_dir:
        config.setdefault("memory_settings", {})["data_directory"] = data_dir
        logger.info(f"Using memory data directory from environment: {data_dir}")
    
    return config

def _validate_config(config: Dict[str, Any]) -> None:
    """Validate configuration structure and required fields"""
    errors = []
    
    # Check top-level structure
    if "embedding_models" not in config:
        errors.append("Configuration missing 'embedding_models' section")
        return  # Can't continue without this
    
    if "default" not in config["embedding_models"]:
        errors.append("Configuration missing 'default' embedding model")
    
    # Validate each embedding model
    for model_name, model_config in config["embedding_models"].items():
        model_errors = _validate_embedding_model(model_name, model_config)
        errors.extend(model_errors)
    
    # Validate memory settings if present
    if "memory_settings" in config:
        memory_errors = _validate_memory_settings(config["memory_settings"])
        errors.extend(memory_errors)
    
    # Report all errors
    if errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors)
        raise ValueError(error_msg)
    
    logger.info("Configuration validation passed")

def _validate_embedding_model(model_name: str, model_config: Dict[str, Any]) -> List[str]:
    """Validate a single embedding model configuration"""
    errors = []
    
    # Required fields
    required_fields = ["backend"]
    for field in required_fields:
        if field not in model_config:
            errors.append(f"Model '{model_name}' missing required field: {field}")
    
    backend = model_config.get("backend")
    if backend:
        # Backend-specific validation
        if backend == "huggingface":
            if "model_name" not in model_config:
                errors.append(f"HuggingFace model '{model_name}' missing 'model_name' field")
            
            device = model_config.get("device")
            if device and device not in ["cpu", "cuda", "auto"]:
                errors.append(f"Model '{model_name}' has invalid device '{device}' (use: cpu, cuda, auto)")
        
        elif backend == "api":
            if "model_name" not in model_config:
                errors.append(f"API model '{model_name}' missing 'model_name' field")
            
            # Check for API key (either in config or environment)
            api_key = model_config.get("api_key")
            model_name_val = model_config.get("model_name", "")
            
            if not api_key or api_key.startswith("YOUR_"):
                # Check environment variables
                if "openai" in model_name_val.lower() and not os.getenv("OPENAI_API_KEY"):
                    errors.append(f"API model '{model_name}' missing OpenAI API key (set OPENAI_API_KEY or api_key in config)")
                elif "cohere" in model_name_val.lower() and not os.getenv("COHERE_API_KEY"):
                    errors.append(f"API model '{model_name}' missing Cohere API key (set COHERE_API_KEY or api_key in config)")
        
        elif backend == "local":
            if "server_url" not in model_config:
                errors.append(f"Local model '{model_name}' missing 'server_url' field")
            else:
                url = model_config["server_url"]
                if not url.startswith(("http://", "https://")):
                    errors.append(f"Local model '{model_name}' has invalid server_url format")
        
        elif backend == "random":
            if "embedding_dim" not in model_config:
                errors.append(f"Random model '{model_name}' missing 'embedding_dim' field")
            else:
                dim = model_config["embedding_dim"]
                if not isinstance(dim, int) or dim <= 0:
                    errors.append(f"Random model '{model_name}' has invalid embedding_dim (must be positive integer)")
        
        elif backend not in ["huggingface", "api", "local", "random"]:
            errors.append(f"Model '{model_name}' has unsupported backend '{backend}'")
    
    # Validate embedding_dim if present
    if "embedding_dim" in model_config:
        dim = model_config["embedding_dim"]
        if not isinstance(dim, int) or dim <= 0:
            errors.append(f"Model '{model_name}' has invalid embedding_dim (must be positive integer)")
    
    return errors

def _validate_memory_settings(memory_settings: Dict[str, Any]) -> List[str]:
    """Validate memory settings configuration"""
    errors = []
    
    # Validate working memory max tokens
    if "working_memory_max_tokens" in memory_settings:
        max_tokens = memory_settings["working_memory_max_tokens"]
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            errors.append("working_memory_max_tokens must be a positive integer")
    
    # Validate active memory max pages
    if "active_memory_max_pages" in memory_settings:
        max_pages = memory_settings["active_memory_max_pages"]
        if not isinstance(max_pages, int) or max_pages <= 0:
            errors.append("active_memory_max_pages must be a positive integer")
    
    # Validate data directory
    if "data_directory" in memory_settings:
        data_dir = memory_settings["data_directory"]
        if not isinstance(data_dir, str) or not data_dir.strip():
            errors.append("data_directory must be a non-empty string")
    
    return errors

def validate_runtime_config(config: Dict[str, Any]) -> bool:
    """
    Validate configuration at runtime and return success status
    
    Args:
        config: Configuration dictionary to validate
    
    Returns:
        True if valid, False otherwise
    """
    try:
        _validate_config(config)
        return True
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        return False

def get_config_validation_help() -> str:
    """Get help text for configuration validation"""
    return """
Configuration Validation Help:

Required Structure:
{
  "embedding_models": {
    "default": { ... },  // At least one model required
    "model_name": { ... }
  },
  "memory_settings": { ... }  // Optional
}

Embedding Model Fields:
- backend: "huggingface" | "api" | "local" | "random" (required)
- model_name: string (required for huggingface/api)
- embedding_dim: positive integer (required for random)
- device: "cpu" | "cuda" | "auto" (optional, for huggingface)
- api_key: string (required for api models)
- server_url: valid URL (required for local)

Memory Settings Fields:
- working_memory_max_tokens: positive integer
- active_memory_max_pages: positive integer  
- data_directory: non-empty string

Environment Variables (override config):
- OPENAI_API_KEY, COHERE_API_KEY
- EMBEDDING_MODEL, EMBEDDING_BACKEND, EMBEDDING_DEVICE
- MEMORY_DATA_DIR
"""

def _get_default_config() -> Dict[str, Any]:
    """Get default configuration structure"""
    return {
        "embedding_models": {
            "default": {
                "backend": "huggingface",
                "model_name": "nomic-ai/nomic-embed-text-v2-moe",
                "embedding_dim": 768,
                "device": "cpu"
            },
            "fast": {
                "backend": "huggingface",
                "model_name": "BAAI/bge-small-en-v1.5",
                "embedding_dim": 384,
                "device": "cpu"
            },
            "openai": {
                "backend": "api",
                "model_name": "text-embedding-3-small",
                "api_key": "",
                "embedding_dim": 1536
            },
            "cohere": {
                "backend": "api",
                "model_name": "embed-english-v3.0",
                "api_key": "",
                "embedding_dim": 1024
            },
            "local-server": {
                "backend": "local",
                "server_url": "http://localhost:8080/embed"
            },
            "fallback": {
                "backend": "random",
                "embedding_dim": 768
            }
        },
        "memory_settings": {
            "working_memory_max_tokens": 4000,
            "active_memory_max_pages": 20,
            "data_directory": ".memory"
        }
    }

def _get_fallback_config() -> Dict[str, Any]:
    """Get minimal fallback configuration"""
    return {
        "embedding_models": {
            "default": {
                "backend": "random",
                "embedding_dim": 768
            }
        },
        "memory_settings": {
            "data_directory": ".memory"
        }
    }

def get_env_config_help() -> str:
    """Get help text for environment variable configuration"""
    return """
Environment Variable Configuration:

API Keys:
  OPENAI_API_KEY     - OpenAI API key for text-embedding models
  COHERE_API_KEY     - Cohere API key for embedding models

Model Settings:
  EMBEDDING_MODEL    - Default embedding model name
  EMBEDDING_BACKEND  - Default backend (huggingface, api, local, random)
  EMBEDDING_DEVICE   - Default device (cpu, cuda)

Memory Settings:
  MEMORY_DATA_DIR    - Directory for memory storage (default: .memory)

Example:
  export OPENAI_API_KEY="sk-..."
  export EMBEDDING_MODEL="text-embedding-3-small"
  export EMBEDDING_BACKEND="api"
"""
