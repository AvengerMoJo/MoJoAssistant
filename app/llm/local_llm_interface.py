"""
Enhanced Local LLM Interface Module for MoJoAssistant

This module provides a direct interface for local LLM models without LangChain dependencies,
using a standardized approach similar to the API interface.
"""

from typing import Dict, List, Any, Optional
import os
import json
import subprocess
import time
import requests

from app.llm.llm_base import BaseLLMInterface

class LocalLLMInterface(BaseLLMInterface):
    """
    Interface for local LLM models using direct subprocess or local API calls
    without LangChain dependencies
    """
    def __init__(self, 
                 model_path: str = None,
                 model_type: str = "llama", 
                 server_url: str = None,
                 server_port: int = 8000,
                 context_length: int = 4096,
                 timeout: int = 60,
                 verbose: bool = True):
        """
        Initialize the local LLM interface
        
        Args:
            model_path: Path to the model file
            model_type: Model type (llama, gptj, mistral, etc.)
            server_url: URL of existing local API server (if already running)
            server_port: Port to run local server on (if starting new server)
            context_length: Maximum context length for the model
            timeout: Request timeout in seconds
            verbose: Whether to enable verbose output
        """
        self.model_path = model_path
        self.model_type = model_type
        self.server_url = server_url or f"http://localhost:{server_port}/v1"
        self.server_port = server_port
        self.context_length = context_length
        self.timeout = timeout
        self.verbose = verbose
        self.server_process = None
        self._started = False
        
        # Initialize server if model path is provided and not external server URL
        if model_path and not server_url:
            self._start_local_server()
    
    def _start_local_server(self) -> bool:
        """
        Start a local server using llama-cpp-python, llm-server, or other appropriate backend
        
        Returns:
            bool: True if server started successfully
        """
        try:
            # Check if server is already running
            try:
                response = requests.get(f"{self.server_url}/models", timeout=self.timeout)
                if response.status_code == 200:
                    print(f"Local LLM server already running at {self.server_url}")
                    self._started = True
                    return True
            except requests.RequestException:
                pass  # Server not running, continue to start it
            
            # Determine server command based on model type
            if self.model_type.lower() in ["llama", "mistral", "phi"]:
                # For llama.cpp compatible models
                cmd = [
                    "python", "-m", "llama_cpp.server",
                    "--model", self.model_path,
                    "--port", str(self.server_port),
                    "--chat_format", "chatml"
                ]
            elif self.model_type.lower() in ["gptj", "gpt4all"]:
                # For GPT4All compatible models
                cmd = [
                    "gpt4all-server",
                    "--model", self.model_path,
                    "--port", str(self.server_port)
                ]
            else:
                # Generic command, might need adjustments for other model types
                cmd = [
                    "python", "-m", "llm_server",
                    "--model", self.model_path,
                    "--port", str(self.server_port)
                ]
            
            if self.verbose:
                print(f"Starting local LLM server with command: {' '.join(cmd)}")
            
            # Start server in background
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE if not self.verbose else None,
                stderr=subprocess.PIPE if not self.verbose else None
            )
            
            # Wait for server to start (with timeout)
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                try:
                    response = requests.get(f"{self.server_url}/models", timeout=self.timeout)
                    if response.status_code == 200:
                        self._started = True
                        print(f"Local LLM server started at {self.server_url}")
                        return True
                except requests.RequestException:
                    time.sleep(1)  # Wait and retry
            
            print("Failed to start local LLM server within timeout period")
            return False
            
        except Exception as e:
            print(f"Error starting local LLM server: {e}")
            if self.server_process:
                self.server_process.terminate()
                self.server_process = None
            return False
    
    def set_model(self, model_path: str, model_type: str = "llama") -> bool:
        """
        Change the active model
        
        Args:
            model_path: Path to the new model file
            model_type: Model type
            
        Returns:
            bool: True if model change was successful
        """
        # Stop existing server if running
        self.shutdown()
        
        # Update model info
        self.model_path = model_path
        self.model_type = model_type
        
        # Start new server
        return self._start_local_server()
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Generate a response using the local LLM based on query and available context
        
        Args:
            query: User query
            context: List of context items
            
        Returns:
            str: Generated response
        """
        if not self._started:
            return self._fallback_response(query, context)
        
        # Format context
        context_text = self.format_context(context) if context else "No context available."
        
        # Create messages in ChatML format
        messages = [
            {"role": "system", "content": f"""You are MoJoAssistant, a helpful AI with a tiered memory system.

CONTEXT INFORMATION:
{context_text}

Please respond to the user's query based on the context provided.
If the context doesn't contain relevant information, respond based on your general knowledge.
Keep your response concise, relevant, and helpful."""},
            {"role": "user", "content": query}
        ]
        
        # Prepare request payload
        payload = {
            "model": os.path.basename(self.model_path) if self.model_path else "local-model",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": min(1024, self.context_length // 4),  # Use 1/4 of context for output
            "stream": False
        }
        
        # Make API request to local server
        try:
            response = requests.post(
                f"{self.server_url}/chat/completions",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                print(f"Local LLM API error: {response.status_code} - {response.text}")
                return self._fallback_response(query, context)
                
        except Exception as e:
            print(f"Error generating local LLM response: {e}")
            return self._fallback_response(query, context)
    
    def generate_response_stream(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Stream a response from the local LLM (alternative implementation)
        
        Args:
            query: User query
            context: List of context items
            
        Returns:
            str: Full generated response
        """
        if not self._started:
            return self._fallback_response(query, context)
        
        # Format context
        context_text = self.format_context(context) if context else "No context available."
        
        # Create messages in ChatML format
        messages = [
            {"role": "system", "content": f"""You are MoJoAssistant, a helpful AI with a tiered memory system.

CONTEXT INFORMATION:
{context_text}

Please respond to the user's query based on the context provided.
If the context doesn't contain relevant information, respond based on your general knowledge.
Keep your response concise, relevant, and helpful."""},
            {"role": "user", "content": query}
        ]
        
        # Prepare request payload
        payload = {
            "model": os.path.basename(self.model_path) if self.model_path else "local-model",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": min(1024, self.context_length // 4),
            "stream": True
        }
        
        # Make streaming API request to local server
        try:
            response = requests.post(
                f"{self.server_url}/chat/completions",
                json=payload,
                stream=True,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        line_text = line.decode('utf-8')
                        if line_text.startswith('data: ') and line_text != 'data: [DONE]':
                            try:
                                data = json.loads(line_text[6:])
                                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    full_response += content
                                    if self.verbose:
                                        print(content, end="", flush=True)
                            except json.JSONDecodeError:
                                pass
                
                if self.verbose:
                    print()  # Newline after streaming
                return full_response
            else:
                print(f"Local LLM API streaming error: {response.status_code}")
                return self._fallback_response(query, context)
                
        except Exception as e:
            print(f"Error streaming local LLM response: {e}")
            return self._fallback_response(query, context)
    
    def _fallback_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Provide a fallback response when LLM generation fails
        
        Args:
            query: User query
            context: Context information
            
        Returns:
            str: Fallback response
        """
        context_info = f"(with {len(context)} context items)" if context else "(without context)"
        return f"I'm sorry, I couldn't generate a proper response to your query {context_info}. The local language model appears to be unavailable. Please check the model configuration and try again."
    
    def shutdown(self) -> None:
        """
        Shutdown the local server if it was started by this interface
        """
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None
            self._started = False
            print("Local LLM server shut down")
    
    def __del__(self):
        """Clean up resources on destruction"""
        self.shutdown()

