"""
API-based LLM Interface Module for MoJoAssistant

This module provides an interface for interacting with various API-based LLM backends
like OpenAI, Claude, Deepseek, etc.
"""

from typing import Dict, List, Any
import os
import requests
import json

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
        return [
            {"role": "user", "content": f"""CONTEXT INFORMATION:
{context_text}

USER QUERY:
{query}"""}
        ]
    
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
                    "system": "You are MoJoAssistant, a helpful AI with a tiered memory system.",
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
