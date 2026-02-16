"""
Bootstrap LLM - Minimal LLM for installer agents.

Starts an LLM quietly (no debug output) to power the installer agents.
Falls back through multiple options:
  1. Existing Ollama/LMStudio server
  2. Downloaded local model (quiet mode)
  3. Simple rule-based fallback
"""

import os
import sys
import subprocess
import time
import requests
from pathlib import Path
from typing import Optional, Dict


class BootstrapLLM:
    """Minimal LLM interface for installer agents."""

    def __init__(self):
        """Initialize bootstrap LLM."""
        self.llm_type = None
        self.server_process = None
        self.base_url = None
        self.model_name = None

    def start(self, quiet: bool = True) -> bool:
        """
        Start an LLM (trying multiple methods).

        Args:
            quiet: If True, suppress all LLM debug output

        Returns:
            True if successful, False otherwise
        """
        if quiet:
            print("🤖 Starting AI assistant (quiet mode)...")
        else:
            print("🤖 Starting AI assistant...")

        # Try Ollama first (external)
        if self._try_ollama():
            print("  ✓ Using Ollama")
            return True

        # Try LMStudio (external)
        if self._try_lmstudio():
            print("  ✓ Using LM Studio")
            return True

        # Try local model with llama-cpp-python
        if self._try_local_model(quiet=quiet):
            print("  ✓ Using local model")
            return True

        # No LLM available
        print("  ⚠️  No LLM available - falling back to rule-based mode")
        return False

    def _try_ollama(self) -> bool:
        """Try to connect to Ollama."""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                if models:
                    self.llm_type = "ollama"
                    self.base_url = "http://localhost:11434"
                    self.model_name = models[0].get("name", "llama2")
                    return True
        except Exception:
            pass
        return False

    def _try_lmstudio(self) -> bool:
        """Try to connect to LM Studio."""
        try:
            response = requests.get("http://localhost:1234/v1/models", timeout=2)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                if models:
                    self.llm_type = "lmstudio"
                    self.base_url = "http://localhost:1234/v1"
                    self.model_name = models[0].get("id", "local-model")
                    return True
        except Exception:
            pass
        return False

    def _try_local_model(self, quiet: bool = True) -> bool:
        """Try to start local model with llama-cpp-python."""
        # Check if model exists
        model_path = self._find_local_model()
        if not model_path:
            return False

        try:
            # Start llama-cpp-python server in quiet mode
            cmd = [
                sys.executable,
                "-m",
                "llama_cpp.server",
                "--model",
                str(model_path),
                "--port",
                "8765",
                "--chat_format",
                "chatml",
            ]

            if quiet:
                # Redirect stdout and stderr to suppress output
                self.server_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:
                self.server_process = subprocess.Popen(cmd)

            # Wait for server to start
            for i in range(30):  # 30 second timeout
                try:
                    response = requests.get("http://localhost:8765/v1/models", timeout=1)
                    if response.status_code == 200:
                        self.llm_type = "local"
                        self.base_url = "http://localhost:8765/v1"
                        self.model_name = model_path.stem
                        return True
                except Exception:
                    time.sleep(1)

            # Server didn't start in time
            self.stop()
            return False

        except Exception as e:
            return False

    def _find_local_model(self) -> Optional[Path]:
        """Find a local GGUF model to use."""
        # Check if llm_config.json exists
        llm_config_path = Path("config/llm_config.json")
        if llm_config_path.exists():
            import json

            try:
                with open(llm_config_path) as f:
                    config = json.load(f)

                # Find first working model
                for model_id, model_config in config.get("local_models", {}).items():
                    model_path = Path(model_config.get("path", "")).expanduser()
                    if model_path.exists():
                        return model_path
            except Exception:
                pass

        # Check cache directory
        cache_dir = Path("~/.cache/mojoassistant/models").expanduser()
        if cache_dir.exists():
            gguf_files = list(cache_dir.glob("*.gguf"))
            if gguf_files:
                return gguf_files[0]

        return None

    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """
        Send a message to the LLM and get response.

        Args:
            message: User message
            system_prompt: Optional system prompt

        Returns:
            LLM response
        """
        if not self.llm_type:
            raise RuntimeError("LLM not started")

        try:
            if self.llm_type == "ollama":
                return self._chat_ollama(message, system_prompt)
            elif self.llm_type in ("lmstudio", "local"):
                return self._chat_openai_compatible(message, system_prompt)
            else:
                raise RuntimeError(f"Unknown LLM type: {self.llm_type}")
        except Exception as e:
            raise RuntimeError(f"Chat failed: {e}")

    def _chat_ollama(self, message: str, system_prompt: Optional[str] = None) -> str:
        """Chat with Ollama."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        response = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model_name, "messages": messages, "stream": False},
            timeout=60,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Ollama error: {response.status_code}")

        return response.json().get("message", {}).get("content", "")

    def _chat_openai_compatible(
        self, message: str, system_prompt: Optional[str] = None
    ) -> str:
        """Chat with OpenAI-compatible API (LMStudio, llama-cpp-python)."""
        messages = []
        if system_prompt:
            # Keep system prompt short to avoid token limits
            messages.append({"role": "system", "content": system_prompt[:500]})
        messages.append({"role": "user", "content": message})

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json={
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 300,
                },
                timeout=60,
            )

            if response.status_code != 200:
                # Print error details for debugging
                try:
                    error_data = response.json()
                    raise RuntimeError(f"API error {response.status_code}: {error_data}")
                except:
                    raise RuntimeError(f"API error: {response.status_code} - {response.text}")

            result = response.json()
            return result["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Request failed: {e}")

    def stop(self):
        """Stop the LLM server if we started one."""
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass
            finally:
                self.server_process = None

    def __enter__(self):
        """Context manager entry."""
        self.start(quiet=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
