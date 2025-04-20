"""
Enhanced LLM Interface Module for MoJoAssistant

This module provides a flexible interface for interacting with various LLM backends,
supporting both local models (via GPT4All) and remote API-based models.
"""

from typing import Dict, List, Any
from abc import abstractmethod

# For local models
from langchain.llms import GPT4All
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

from app.llm.llm_base import BaseLLMInterface

class APILLMInterface(BaseLLMInterface):
    """
    Interface for API-based LLM models like OpenAI, Claude, Deepseek, etc.
    """
    def __init__(self, 
                 provider: str,
                 api_key: str = None,
                 model: str = None,
                 config: Dict[str, Any] = None):
        """
        Initialize the API LLM interface
        
        Args:
            provider: Name of the LLM provider (openai, claude, deepseek, etc.)
            api_key: API key for the provider
            model: Model name to use
            config: Additional configuration parameters
        """
        self.provider = provider.lower()
        self.api_key = api_key or os.environ.get(f"{provider.upper()}_API_KEY")
        self.config = config or {}
        
        # Set default values
        self.url = self.config.get('url')
        self.model = model or self.config.get('model')
        self.headers = {
            "Content-Type": "application/json",
        }
        
        # Configure provider-specific settings
        self._configure_provider()
    
    def _configure_provider(self):
        """Configure provider-specific settings"""
        if self.provider == "openai":
            self.url = self.url or "https://api.openai.com/v1/chat/completions"
            self.model = self.model or "gpt-4o-mini"
            self.context_limit = self.config.get('context_limit', 128000)
            self.output_limit = self.config.get('output_limit', 16384)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
            
        elif self.provider == "claude":
            self.url = self.url or "https://api.anthropic.com/v1/messages"
            self.model = self.model or "claude-3-5-sonnet-20241022"
            self.context_limit = self.config.get('context_limit', 200000)
            self.output_limit = self.config.get('output_limit', 8192)
            self.headers['x-api-key'] = self.api_key
            self.headers['anthropic-version'] = "2023-06-01"
            self.message_format = "anthropic"
            
        elif self.provider == "deepseek":
            self.url = self.url or "https://api.deepseek.com/v1/chat/completions"
            self.model = self.model or "deepseek-chat"
            self.context_limit = self.config.get('context_limit', 64000)
            self.output_limit = self.config.get('output_limit', 8000)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
            
        elif self.provider == "perplexity":
            self.url = self.url or "https://api.perplexity.ai/chat/completions"
            self.model = self.model or "sonar-pro"
            self.context_limit = self.config.get('context_limit', 128000)
            self.output_limit = self.config.get('output_limit', 32768)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
            self.search_enabled = True
            
        elif self.provider == "local_api":
            self.url = self.url or "http://localhost:8080/v1/chat/completions"
            self.model = self.model or "Yi-1.5-9B-Chat-16K-Q4_0.gguf"
            self.context_limit = self.config.get('context_limit', 16384)
            self.output_limit = self.config.get('output_limit', 8192)
            self.message_format = "openai"
            
        elif self.provider == "xai":
            self.url = self.url or "https://api.x.ai/v1/chat/completions"
            self.model = self.model or "grok-2-1212"
            self.context_limit = self.config.get('context_limit', 131072)
            self.output_limit = self.config.get('output_limit', 32768)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
            
        elif self.provider == "deepinfra":
            self.url = self.url or "https://api.deepinfra.com/v1/openai/chat/completions"
            self.model = self.model or "meta-llama/Llama-3.3-70B-Instruct-Turbo"
            self.context_limit = self.config.get('context_limit', 128000)
            self.output_limit = self.config.get('output_limit', 32768)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
            
        elif self.provider == "groq":
            self.url = self.url or "https://api.groq.com/openai/v1/chat/completions"
            self.model = self.model or "llama-3.3-70b-versatile"
            self.context_limit = self.config.get('context_limit', 128000)
            self.output_limit = self.config.get('output_limit', 32768)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"
        
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def _format_openai_messages(self, query: str, context_text: str) -> List[Dict[str, str]]:
        """Format messages for OpenAI-compatible API"""
        system_message = f"""You are MoJoAssistant, a helpful AI with a tiered memory system.

CONTEXT INFORMATION:
{context_text}

Please respond to the user's query based on the context provided.
If the context doesn't contain relevant information, respond based on your general knowledge.
Keep your response concise, relevant, and helpful."""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": query}
        ]
    
    def _format_anthropic_messages(self, query: str, context_text: str) -> List[Dict[str, str]]:
        """Format messages for Anthropic Claude API"""
        system_message = f"""You are MoJoAssistant, a helpful AI with a tiered memory system.

Please respond to the user's query based on the context provided.
If the context doesn't contain relevant information, respond based on your general knowledge.
Keep your response concise, relevant, and helpful."""

        messages = [
            {"role": "user", "content": f"""CONTEXT INFORMATION:
{context_text}

USER QUERY:
{query}"""}
        ]
        
        return messages
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Generate a response using the API-based LLM
        
        Args:
            query: User query
            context: List of context items
            
        Returns:
            str: Generated response
        """
        try:
            # Format context
            context_text = self.format_context(context) if context else "No context available."
            
            # Format messages according to the provider's API
            if self.message_format == "openai":
                messages = self._format_openai_messages(query, context_text)
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": min(2048, self.output_limit),
                }
                if hasattr(self, 'search_enabled') and self.search_enabled:
                    payload["search"] = True
                    
            elif self.message_format == "anthropic":
                messages = self._format_anthropic_messages(query, context_text)
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "system": f"You are MoJoAssistant, a helpful AI with a tiered memory system.",
                    "temperature": 0.7,
                    "max_tokens": min(2048, self.output_limit),
                }
            
            # Make the API request
            response = requests.post(
                self.url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            # Process the response
            if response.status_code == 200:
                response_data = response.json()
                
                # Extract content from the response based on the provider
                if self.message_format == "openai":
                    return response_data['choices'][0]['message']['content'].strip()
                elif self.message_format == "anthropic":
                    return response_data['content'][0]['text'].strip()
                
            else:
                print(f"API Error: {response.status_code} - {response.text}")
                return self._fallback_response(query, context)
                
        except Exception as e:
            print(f"Error generating API response: {e}")
            return self._fallback_response(query, context)
    
    def _fallback_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """Provide a fallback response when API call fails"""
        context_info = f"(with {len(context)} context items)" if context else "(without context)"
        return f"I'm sorry, I couldn't generate a proper response to your query {context_info}. There was an issue connecting to the {self.provider.capitalize()} API. Please check your API configuration and try again."


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
