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
                 api_key: str | None = None,
                 model: str | None = None,
                 config: Dict[str, Any] | None = None):
        """
        Initialize the API LLM interface
        
        Args:
            provider: Name of the LLM provider (openai, claude, deepseek, etc.)
            api_key: API key for the provider
            model: Model name to use
            config: Additional configuration parameters
        """
        super().__init__()
        self.provider = provider.lower()
        self.config = config or {}
        from app.llm.unified_client import UnifiedLLMClient
        resource_id = self.config.get("resource_id", provider.lower())
        resolved_key = api_key or UnifiedLLMClient.resolve_key(resource_id, self.config)
        self.api_key = resolved_key
        
        # Set default values
        self.base_url = self.config.get('base_url') or self.config.get('url') or ""
        self.url = self.base_url
        self.model = model or self.config.get('model') or None
        self._model_probed = False  # lazy: probe server for model if not configured
        self.headers = {
            "Content-Type": "application/json",
        }

        # Configure provider-specific settings
        self._configure_provider()
    
    def _configure_provider(self):
        """Configure provider-specific settings"""
        if self.provider == "openai":
            base_url = self.config.get('base_url', "https://api.openai.com/v1")
            self.base_url = base_url
            self.url = f"{base_url.rstrip('/')}/chat/completions"
            # Only set a default model for remote OpenAI; local servers report their own model
            is_local = any(base_url.startswith(p) for p in ("http://localhost", "http://127.0.0.1"))
            if not is_local:
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
            self.headers['x-api-key'] = self.api_key or ""
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

        elif self.provider == "google":
            # Google Gemini via its OpenAI-compatible endpoint
            base_url = self.config.get('base_url', "https://generativelanguage.googleapis.com/v1beta/openai")
            self.url = f"{base_url.rstrip('/')}/chat/completions"
            self.model = self.model or "gemini-2.0-flash"
            self.context_limit = self.config.get('context_limit', 1000000)
            self.output_limit = self.config.get('output_limit', 8192)
            self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.message_format = "openai"

        else:
            # Generic config-driven provider — no code change needed for new providers.
            # Required in config: base_url, model
            # Optional in config: message_format ("openai"|"anthropic"), context_limit,
            #                     output_limit, search_enabled, anthropic_version
            base_url = self.config.get('base_url', '').rstrip('/')
            if not base_url:
                print(f"⚠️  Provider '{self.provider}' has no base_url in config — requests will fail")
            self.message_format = self.config.get('message_format', 'openai')
            if self.message_format == 'anthropic':
                self.url = f"{base_url}/messages"
                self.headers['x-api-key'] = self.api_key or ""
                self.headers['anthropic-version'] = self.config.get('anthropic_version', '2023-06-01')
            else:
                self.url = f"{base_url}/chat/completions"
                self.headers['Authorization'] = f"Bearer {self.api_key}"
            self.context_limit = self.config.get('context_limit', 128000)
            self.output_limit = self.config.get('output_limit', 8192)
            if self.config.get('search_enabled'):
                self.search_enabled = True
    
    def _resolve_model(self) -> str:
        """
        Return the model to use for requests.

        If no model was configured (local server), probe /v1/models once and cache the result.
        This means the model field always reflects what the server actually has loaded —
        no stale config required.
        """
        if self.model:
            return self.model

        if not self._model_probed:
            self._model_probed = True
            base = self.base_url.rstrip("/")
            auth = self.headers.get("Authorization", "")
            probe_headers = {"Authorization": auth} if auth else {}
            for path in ("/models", "/v1/models"):
                try:
                    resp = requests.get(f"{base}{path}", headers=probe_headers, timeout=2)
                    if resp.status_code == 200:
                        models = resp.json().get("data", [])
                        if models:
                            self.model = models[0].get("id", "")
                            return self.model
                except Exception:
                    pass

        return self.model or "unknown"

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
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] | None = None) -> str:
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

            model = self._resolve_model()

            # Initialize payload with default
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "temperature": 0.7,
                "max_tokens": 1000,
            }

            # Format messages according to the provider's API
            if self.message_format == "openai":
                messages = self._format_openai_messages(query, context_text)
                payload.update({
                    "model": model,
                    "messages": messages,
                    "max_tokens": min(2048, self.output_limit),
                })
                if hasattr(self, 'search_enabled') and self.search_enabled:
                    payload["search"] = True

            elif self.message_format == "anthropic":
                messages = self._format_anthropic_messages(query, context_text)
                payload.update({
                    "model": model,
                    "messages": messages,
                    "system": "You are MoJoAssistant, a helpful AI with a tiered memory system.",
                    "max_tokens": min(2048, self.output_limit),
                })
            
            # (payload is always set above; guard kept for safety)
            if payload is None:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": query}],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                }
            
            from app.llm.unified_client import UnifiedLLMClient
            resource_config = {
                "base_url": self.base_url,
                "model": self._resolve_model(),
                "api_key": self.api_key,
                "output_limit": self.output_limit,
                "message_format": self.message_format,
                "provider": self.provider,
                "timeout": getattr(self, "timeout", 300),
            }
            uclient = UnifiedLLMClient()
            response_data = uclient.call_sync(
                messages=messages,
                resource_config=resource_config,
            )
            return UnifiedLLMClient._extract_text(response_data, self.message_format)
                
        except Exception as e:
            self.logger.error(f"Error generating API response: {e}")
            return self._fallback_response(query, context or [])
        
        # Fallback if no response was returned
        return self._fallback_response(query, context or [])
    
    def generate_chat_response(self, messages: List[Dict[str, str]]) -> str:
        """
        Generate response from a list of chat messages using the API.
        Passes messages directly to the provider without reformatting.

        Args:
            messages: List of chat messages with 'role' and 'content'

        Returns:
            str: Generated response
        """
        try:
            model = self._resolve_model()
            if self.message_format == "anthropic":
                # Anthropic requires system message to be separate
                system = next((m["content"] for m in messages if m["role"] == "system"), None)
                user_messages = [m for m in messages if m["role"] != "system"]
                payload = {
                    "model": model,
                    "messages": user_messages,
                    "max_tokens": min(2048, self.output_limit),
                }
                if system:
                    payload["system"] = system
            else:
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": min(2048, self.output_limit),
                }

            from app.llm.unified_client import UnifiedLLMClient
            resource_config = {
                "base_url": self.base_url,
                "model": self._resolve_model(),
                "api_key": self.api_key,
                "output_limit": self.output_limit,
                "message_format": self.message_format,
                "provider": self.provider,
                "timeout": getattr(self, "timeout", 300),
            }
            uclient = UnifiedLLMClient()
            response_data = uclient.call_sync(messages=messages, resource_config=resource_config)
            return UnifiedLLMClient._extract_text(response_data, self.message_format)

        except Exception as e:
            self.logger.error(f"Error generating chat response: {e}")

        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return self._fallback_response(last_user_msg)

    def _fallback_response(self, query: str, context: List[Dict[str, Any]] | None = None) -> str:
        """Provide a fallback response when API call fails"""
        context_info = f"(with {len(context)} context items)" if context else "(without context)"
        return f"I'm sorry, I couldn't generate a proper response to your query {context_info}. There was an issue connecting to the {self.provider.capitalize()} API. Please check your API configuration and try again."
