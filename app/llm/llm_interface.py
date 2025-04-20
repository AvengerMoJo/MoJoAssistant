"""
Unified LLM Interface Module for MoJoAssistant

This module provides a centralized interface for working with different LLM backends.
"""

from typing import Dict, List, Any
import os
import json

# Import implementations
from app.llm.local_llm_interface import LocalLLMInterface
from app.llm.api_llm_interface import APILLMInterface

class LLMInterface:
    """
    Unified LLM interface that supports both local and API-based models
    """
    def __init__(self, config_file: str = None):
        """
        Initialize the unified LLM interface
        
        Args:
            config_file: Path to configuration file
        """
        self.interfaces = {}
        self.active_interface = None
        self.active_interface_name = None
        
        # Load configuration if provided
        if config_file and os.path.exists(config_file):
            self.load_config(config_file)
    
    def load_config(self, config_file: str) -> None:
        """
        Load configuration from file
        
        Args:
            config_file: Path to configuration file
        """
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Configure local models
            if 'local_models' in config:
                for name, model_config in config['local_models'].items():
                    self.add_local_interface(
                        name=name,
                        model_path=model_config.get('path'),
                        model_type=model_config.get('type', 'gptj'),
                        n_threads=model_config.get('n_threads', 6)
                    )
            
            # Configure API models
            if 'api_models' in config:
                for name, api_config in config['api_models'].items():
                    self.add_api_interface(
                        name=name,
                        provider=api_config.get('provider'),
                        api_key=api_config.get('api_key'),
                        model=api_config.get('model'),
                        config=api_config.get('config', {})
                    )
            
            # Set active interface
            if 'default_interface' in config and config['default_interface'] in self.interfaces:
                self.set_active_interface(config['default_interface'])
                
        except Exception as e:
            print(f"Error loading configuration: {e}")
    
    def add_local_interface(self, name: str, model_path: str, model_type: str = "gptj", n_threads: int = 6) -> None:
        """
        Add a local LLM interface
        
        Args:
            name: Name of the interface
            model_path: Path to the model file
            model_type: Model backend type
            n_threads: Number of threads to use
        """
        self.interfaces[name] = LocalLLMInterface(
            model_path=model_path,
            model_type=model_type,
            n_threads=n_threads
        )
        
        # Set as active if first interface
        if len(self.interfaces) == 1:
            self.set_active_interface(name)
    
    def add_api_interface(self, name: str, provider: str, api_key: str = None, model: str = None, config: Dict[str, Any] = None) -> None:
        """
        Add an API-based LLM interface
        
        Args:
            name: Name of the interface
            provider: Provider name (openai, claude, etc.)
            api_key: API key
            model: Model name
            config: Additional configuration
        """
        self.interfaces[name] = APILLMInterface(
            provider=provider,
            api_key=api_key,
            model=model,
            config=config
        )
        
        # Set as active if first interface
        if len(self.interfaces) == 1:
            self.set_active_interface(name)
    
    def set_active_interface(self, name: str) -> bool:
        """
        Set the active interface
        
        Args:
            name: Name of the interface to activate
            
        Returns:
            bool: True if successful, False otherwise
        """
        if name in self.interfaces:
            self.active_interface = self.interfaces[name]
            self.active_interface_name = name
            print(f"Active LLM interface set to: {name}")
            return True
        else:
            print(f"Interface not found: {name}")
            return False
    
    def get_available_interfaces(self) -> List[str]:
        """
        Get names of available interfaces
        
        Returns:
            List[str]: List of interface names
        """
        return list(self.interfaces.keys())
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Generate a response using the active interface
        
        Args:
            query: User query
            context: List of context items
            
        Returns:
            str: Generated response
        """
        if self.active_interface is None:
            return "No active LLM interface configured. Please set up an interface."
        
        return self.active_interface.generate_response(query, context)


# Factory function to create default local LLM interface
def create_local_llm_interface(model_name: str = "default") -> LocalLLMInterface:
    """
    Factory function to create a local LLM interface with a specific model
    
    Args:
        model_name: Name of the model configuration to use
        
    Returns:
        LocalLLMInterface: Configured local LLM interface
    """
    # Model configurations
    model_configs = {
        "default": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin",
            "type": "gptj"
        },
        "llama": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-llama-q4_0.bin",
            "type": "llama"
        },
        # Add more models as needed
    }
    
    # Get config or use default
    config = model_configs.get(model_name, model_configs["default"])
    
    # Create and return interface
    return LocalLLMInterface(
        model_path=config["path"],
        model_type=config["type"]
    )


# Factory function to create a unified LLM interface with default configuration
def create_llm_interface(config_file: str = None, model_name: str = "default") -> LLMInterface:
    """
    Factory function to create a unified LLM interface
    
    Args:
        config_file: Path to configuration file
        model_name: Name of the model to use if no config file
        
    Returns:
        LLMInterface: Configured unified LLM interface
    """
    # If config file exists, use it
    if config_file and os.path.exists(config_file):
        return LLMInterface(config_file=config_file)
    
    # Otherwise, create a default interface
    interface = LLMInterface()
    
    # Add default local interface
    model_configs = {
        "default": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin",
            "type": "gptj"
        },
        "llama": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-llama-q4_0.bin",
            "type": "llama"
        }
    }
    
    # Get config or use default
    config = model_configs.get(model_name, model_configs["default"])
    
    # Add local interface
    interface.add_local_interface(
        name=model_name,
        model_path=config["path"],
        model_type=config["type"]
    )
    
    return interface
