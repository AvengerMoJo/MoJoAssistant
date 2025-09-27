"""
Unified LLM Interface Module for MoJoAssistant

This module provides a centralized interface for working with different LLM backends.
"""

from typing import Dict, List, Any, Optional
import os
import json

# Import implementations
from app.llm.local_llm_interface import LocalLLMInterface
from app.llm.api_llm_interface import APILLMInterface
from app.llm.llm_base import BaseLLMInterface

class LLMInterface:
    """
    Unified LLM interface that supports both local and API-based models
    """
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize the unified LLM interface
        
        Args:
            config_file: Path to configuration file
        """
        self.interfaces: Dict[str, 'BaseLLMInterface'] = {}
        self.active_interface: Optional['BaseLLMInterface'] = None
        self.active_interface_name: Optional[str] = None
        
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
                        model_type=model_config.get('type', 'llama'),
                        server_url=model_config.get('server_url'),
                        server_port=model_config.get('server_port', 8000),
                        context_length=model_config.get('context_length', 4096),
                        timeout=model_config.get('timeout', 60)
                    )
            
            # Configure API models
            if 'api_models' in config:
                for name, api_config in config['api_models'].items():
                    self.add_api_interface(
                        name=name,
                        provider=api_config.get('provider'),
                        api_key=api_config.get('api_key'),
                        model=api_config.get('model'),
                        config=api_config
                    )
            
            # Set active interface
            if 'default_interface' in config and config['default_interface'] in self.interfaces:
                self.set_active_interface(config['default_interface'])
                
        except Exception as e:
            print(f"Error loading configuration: {e}")
    
    def add_local_interface(self, name: str, model_path: Optional[str], model_type: str = "llama", 
                            server_url: Optional[str] = None, server_port: int = 8000, 
                            context_length: int = 4096, timeout: int = 60) -> None:
        """
        Add a local LLM interface
        
        Args:
            name: Name of the interface
            model_path: Path to the model file
            model_type: Model type
            server_url: URL of existing local API server
            server_port: Port for local server
            context_length: Maximum context length
            timeout: Request timeout in seconds
        """
        self.interfaces[name] = LocalLLMInterface(
            model_path=model_path,
            model_type=model_type,
            server_url=server_url,
            server_port=server_port,
            context_length=context_length,
            timeout=timeout
        )
        
        # Set as active if first interface
        if len(self.interfaces) == 1:
            self.set_active_interface(name)
    
    def add_api_interface(self, name: str, provider: str, api_key: Optional[str] = None, 
                         model: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> None:
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
    
    def generate_response(self, query: str, context: Optional[List[Dict[str, Any]]] = None) -> str:
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
    
    def shutdown(self) -> None:
        """
        Shutdown all interfaces and clean up resources
        """
        for name, interface in self.interfaces.items():
            if hasattr(interface, 'shutdown'):
                interface.shutdown()


# Factory function to create a unified LLM interface with default configuration
def create_llm_interface(config_file: Optional[str] = None, model_name: str = "default") -> LLMInterface:
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
    
    # Add default local interface based on OS detection and common model paths
    system_type = os.name
    
    # Default model configurations based on system
    if system_type == 'nt':  # Windows
        default_model_paths = {
            "default": {
                "path": os.path.expanduser("~/AppData/Local/nomic.ai/GPT4All/ggml-model-gpt4all-falcon-q4_0.bin"),
                "type": "gptj"
            },
            "llama": {
                "path": os.path.expanduser("~/AppData/Local/nomic.ai/GPT4All/mistral-7b-instruct-v0.1.Q4_0.gguf"),
                "type": "llama"
            }
        }
    else:  # Linux/Mac
        default_model_paths = {
            "default": {
                "path": os.path.expanduser("~/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin"),
                "type": "gptj"
            },
            "llama": {
                "path": os.path.expanduser("~/.cache/gpt4all/mistral-7b-instruct-v0.1.Q4_0.gguf"),
                "type": "llama"
            }
        }
    
    # Get config or use default
    config = default_model_paths.get(model_name, default_model_paths["default"])
    
    # Check if model file exists, otherwise try different defaults
    model_path = config["path"]
    if not os.path.exists(model_path):
        # Try to find any model file in common directories
        model_dirs = [
            os.path.expanduser("~/.cache/gpt4all/"),
            os.path.expanduser("~/AppData/Local/nomic.ai/GPT4All/"),
            "/usr/local/share/gpt4all/",
            "./models/"
        ]
        
        for dir_path in model_dirs:
            if os.path.exists(dir_path):
                model_files = [f for f in os.listdir(dir_path) 
                              if f.endswith(('.bin', '.gguf')) and os.path.isfile(os.path.join(dir_path, f))]
                if model_files:
                    model_path = os.path.join(dir_path, model_files[0])
                    print(f"Using detected model: {model_path}")
                    break
    
    # Add local interface if we found a model
    if os.path.exists(model_path):
        model_type = "llama" if model_path.endswith(".gguf") else "gptj"
        interface.add_local_interface(
            name=model_name,
            model_path=model_path,
            model_type=model_type
        )
    else:
        # If no local model found, add a warning interface
        interface.add_local_interface(
            name="dummy",
            model_path=None,
            model_type="none"
        )
        print("WARNING: No local LLM model found. Please configure a model path or API endpoint.")
    
    return interface
