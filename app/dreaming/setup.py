"""
Dreaming Setup & Model Installer

Downloads and validates Qwen2.5-Coder-1.7B model for dreaming tasks.
Checks for existing LLM servers (LMStudio, Ollama, etc.)

File: app/dreaming/setup.py
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from tqdm import tqdm


MODELS = {
    "qwen-coder": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q5_k_m.gguf",
        "filename": "qwen2.5-coder-1.5b-instruct-q5_k_m.gguf",
        "description": "Qwen2.5-Coder-1.7B - Code-focused, fast, good for development tasks"
    },
    "qwen3": {
        "url": "https://huggingface.co/Qwen/Qwen2-1.5B-Instruct-GGUF/resolve/main/qwen2-1_5b-instruct-q5_k_m.gguf",
        "filename": "qwen2-1.5b-instruct-q5_k_m.gguf",
        "description": "Qwen2-1.5B - General purpose, better for conversation"
    }
}

DEFAULT_MODEL_URL = MODELS["qwen-coder"]["url"]
DEFAULT_MODEL_NAME = MODELS["qwen-coder"]["filename"]
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mojoassistant" / "models"


class ModelInstaller:
    """Download and validate LLM models for dreaming"""

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize installer

        Args:
            cache_dir: Directory to cache models
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def check_system(self) -> Dict[str, Any]:
        """
        Check what LLM infrastructure is available

        Returns:
            Dict with availability info
        """
        result = {
            "local_models": {},
            "servers": {},
            "recommendations": []
        }

        # Check for LMStudio
        lmstudio_available, lmstudio_info = self._check_lmstudio()
        if lmstudio_available:
            result["servers"]["lmstudio"] = lmstudio_info
            result["recommendations"].append(
                "✓ LMStudio detected - You can use models loaded in LMStudio"
            )

        # Check for Ollama
        ollama_available, ollama_info = self._check_ollama()
        if ollama_available:
            result["servers"]["ollama"] = ollama_info
            result["recommendations"].append(
                f"✓ Ollama detected - Available models: {', '.join(ollama_info.get('models', []))}"
            )

        # Check for local model files
        if self._check_local_model():
            result["local_models"]["qwen-coder"] = {
                "path": str(self.cache_dir / DEFAULT_MODEL_NAME),
                "status": "ready"
            }
            result["recommendations"].append(
                "✓ Qwen2.5-Coder-1.7B model found locally"
            )
        else:
            result["recommendations"].append(
                "✗ Qwen2.5-Coder-1.7B not found - Run 'python -m app.dreaming.setup install' to download"
            )

        # Check for llama-cpp-python
        try:
            import llama_cpp
            result["runtime"] = {
                "llama_cpp_python": {
                    "available": True,
                    "version": llama_cpp.__version__
                }
            }
            result["recommendations"].append(
                "✓ llama-cpp-python installed"
            )
        except ImportError:
            result["runtime"] = {
                "llama_cpp_python": {
                    "available": False
                }
            }
            result["recommendations"].append(
                "✗ llama-cpp-python not installed - Run 'pip install llama-cpp-python'"
            )

        return result

    def _check_lmstudio(self) -> Tuple[bool, Dict[str, Any]]:
        """Check if LMStudio is running"""
        try:
            response = requests.get(
                "http://localhost:1234/v1/models",
                timeout=2
            )
            if response.status_code == 200:
                models = response.json()
                return True, {
                    "url": "http://localhost:1234/v1",
                    "status": "running",
                    "models": [m.get("id") for m in models.get("data", [])]
                }
        except:
            pass

        return False, {}

    def _check_ollama(self) -> Tuple[bool, Dict[str, Any]]:
        """Check if Ollama is running"""
        try:
            response = requests.get(
                "http://localhost:11434/api/tags",
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name") for m in data.get("models", [])]
                return True, {
                    "url": "http://localhost:11434",
                    "status": "running",
                    "models": models
                }
        except:
            pass

        return False, {}

    def _check_local_model(self) -> bool:
        """Check if Qwen model is already downloaded"""
        model_path = self.cache_dir / DEFAULT_MODEL_NAME
        return model_path.exists() and model_path.stat().st_size > 100_000_000  # > 100MB

    def download_model(
        self,
        model_name: str = "qwen-coder",
        url: str = None,
        filename: str = None
    ) -> bool:
        """
        Download model from URL with progress bar

        Args:
            model_name: Model key from MODELS dict (qwen-coder or qwen3)
            url: Download URL (overrides model_name)
            filename: Local filename (overrides model_name)

        Returns:
            True if successful
        """
        # Get model info from MODELS dict if not overridden
        if url is None or filename is None:
            if model_name not in MODELS:
                print(f"Unknown model: {model_name}")
                print(f"Available models: {', '.join(MODELS.keys())}")
                return False

            model_info = MODELS[model_name]
            url = url or model_info["url"]
            filename = filename or model_info["filename"]

        model_path = self.cache_dir / filename

        if model_path.exists():
            print(f"✓ Model already exists at: {model_path}")
            return True

        print(f"Downloading {filename} (~1.2 GB)...")
        print(f"From: {url}")
        print(f"To: {model_path}")
        print()

        try:
            # Stream download with progress bar
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            with open(model_path, 'wb') as f, tqdm(
                desc=filename,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

            print(f"\n✓ Model downloaded successfully: {model_path}")
            return True

        except Exception as e:
            print(f"\n✗ Error downloading model: {e}")
            if model_path.exists():
                model_path.unlink()  # Clean up partial download
            return False

    def validate_model(self, model_path: Optional[Path] = None) -> bool:
        """
        Validate that model works with llama-cpp-python

        Args:
            model_path: Path to model file

        Returns:
            True if model works
        """
        if model_path is None:
            model_path = self.cache_dir / DEFAULT_MODEL_NAME

        if not model_path.exists():
            print(f"✗ Model not found: {model_path}")
            return False

        print(f"Validating model: {model_path}")

        try:
            from llama_cpp import Llama

            # Try to load model
            print("  Loading model...")
            llm = Llama(
                model_path=str(model_path),
                n_ctx=2048,
                n_threads=2,
                verbose=False
            )

            # Try a simple generation
            print("  Testing generation...")
            response = llm.create_chat_completion(
                messages=[
                    {"role": "user", "content": "Say 'test' in JSON: {\"result\": \"test\"}"}
                ],
                max_tokens=50,
                temperature=0.1
            )

            output = response["choices"][0]["message"]["content"]
            print(f"  Model response: {output[:100]}...")

            # Check if we got valid output
            if "test" in output.lower():
                print("✓ Model validation successful!")
                return True
            else:
                print("✗ Model generated unexpected output")
                return False

        except ImportError:
            print("✗ llama-cpp-python not installed")
            print("  Install with: pip install llama-cpp-python")
            return False

        except Exception as e:
            print(f"✗ Model validation failed: {e}")
            return False


def main():
    """Main CLI interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description="MoJo Assistant Dreaming Setup"
    )
    parser.add_argument(
        "command",
        choices=["check", "install", "validate"],
        help="Command to run"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen-coder",
        choices=list(MODELS.keys()),
        help="Model to download (default: qwen-coder)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Model cache directory"
    )

    args = parser.parse_args()

    installer = ModelInstaller(cache_dir=args.cache_dir)

    if args.command == "check":
        print("=" * 70)
        print("MoJo Assistant Dreaming - System Check")
        print("=" * 70)
        print()

        result = installer.check_system()

        print("LLM Servers:")
        if result["servers"]:
            for name, info in result["servers"].items():
                print(f"  • {name}: {info['status']} at {info['url']}")
                if info.get("models"):
                    print(f"    Models: {', '.join(info['models'])}")
        else:
            print("  (none detected)")
        print()

        print("Local Models:")
        if result["local_models"]:
            for name, info in result["local_models"].items():
                print(f"  • {name}: {info['status']} at {info['path']}")
        else:
            print("  (none installed)")
        print()

        print("Recommendations:")
        for rec in result["recommendations"]:
            print(f"  {rec}")
        print()

    elif args.command == "install":
        model_info = MODELS.get(args.model, MODELS["qwen-coder"])

        print("=" * 70)
        print(f"Installing {model_info['description']}")
        print("=" * 70)
        print()

        success = installer.download_model(model_name=args.model)

        if success:
            print()
            print("=" * 70)
            print("Installation Complete!")
            print("=" * 70)
            print()
            print(f"Model: {model_info['filename']}")
            print(f"Path: {installer.cache_dir / model_info['filename']}")
            print()
            print("Next steps:")
            print("1. Run validation: python -m app.dreaming.setup validate")
            print("2. Model is ready to use!")
        else:
            sys.exit(1)

    elif args.command == "validate":
        print("=" * 70)
        print("Validating Model")
        print("=" * 70)
        print()

        success = installer.validate_model()

        if success:
            print()
            print("✓ Model is ready for use!")
        else:
            print()
            print("✗ Validation failed - see errors above")
            sys.exit(1)


if __name__ == "__main__":
    main()
