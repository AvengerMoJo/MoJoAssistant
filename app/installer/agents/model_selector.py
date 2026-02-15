"""
Model Selector Agent - helps users choose and download LLM models.
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
import urllib.request
import urllib.error

from .base_agent import BaseSetupAgent


class ModelSelectorAgent(BaseSetupAgent):
    """Agent for selecting and downloading LLM models."""

    def load_context(self) -> Dict:
        """Load model catalog and agent prompt."""
        try:
            # Load model catalog
            catalog = self.load_json("model_catalog.json")

            # Load agent prompt
            prompt = self.load_prompt("model_selector.md")

            # Load relevant documentation
            docs = self.load_documentation([
                "docs/installation/MODEL_DOWNLOADER_GUIDE.md"
            ])

            self.context = {
                "catalog": catalog,
                "prompt": prompt,
                "documentation": docs,
                "models": catalog.get("models", []),
                "categories": catalog.get("categories", {}),
                "recommendations": catalog.get("use_case_recommendations", {})
            }

            return self.context

        except Exception as e:
            print(f"Error loading context: {e}")
            return {}

    def execute(self, system_info: Optional[Dict] = None, auto_default: bool = False) -> Dict:
        """
        Execute model selection and download.

        Args:
            system_info: Dictionary with system constraints (ram_mb, disk_mb, etc.)
            auto_default: If True, automatically use default model without asking

        Returns:
            Result dictionary
        """
        try:
            # Load context
            self.load_context()

            if not self.context.get("models"):
                return self.set_failure("Model catalog not loaded")

            # Get system info if not provided
            if system_info is None:
                system_info = self._detect_system_info()

            # Auto-select default if requested
            if auto_default:
                return self._install_default_model(system_info)

            # Use LLM to help user choose (if LLM available)
            if self.llm:
                return self._llm_guided_selection(system_info)
            else:
                # Fallback: rule-based selection
                return self._rule_based_selection(system_info)

        except Exception as e:
            self.set_failure(f"Model selection failed: {e}")
            return self.result

    def _detect_system_info(self) -> Dict:
        """Detect system RAM, disk space, etc."""
        import psutil

        # Get available RAM (in MB)
        ram_mb = psutil.virtual_memory().available // (1024 * 1024)

        # Get free disk space in cache directory
        cache_dir = self.expand_path("~/.cache/mojoassistant")
        cache_dir.mkdir(parents=True, exist_ok=True)
        disk_mb = psutil.disk_usage(str(cache_dir)).free // (1024 * 1024)

        return {
            "ram_mb": ram_mb,
            "disk_mb": disk_mb,
            "has_gpu": False  # TODO: Detect GPU
        }

    def _install_default_model(self, system_info: Dict) -> Dict:
        """Install the default model from catalog."""
        default_model = None
        for model in self.context["models"]:
            if model.get("default", False):
                default_model = model
                break

        if not default_model:
            # Fallback to first model
            default_model = self.context["models"][0]

        print(f"Installing default model: {default_model['name']}")
        return self._download_and_configure(default_model)

    def _llm_guided_selection(self, system_info: Dict) -> Dict:
        """Use LLM to guide user through model selection."""
        # Build context for LLM
        llm_context = f"""
{self.context['prompt']}

## Current System Information

- Available RAM: {system_info['ram_mb']} MB
- Free Disk Space: {system_info['disk_mb']} MB
- GPU Available: {system_info.get('has_gpu', False)}

## Available Models from Catalog

{self._format_catalog_for_llm()}

Now help the user choose and download the right model for their needs.
"""

        # Start conversation with LLM
        response = self.chat(llm_context)
        print(response)

        # Interactive loop - let LLM handle the conversation
        # The LLM should call download_model() when ready
        # For now, this is a placeholder for the full implementation

        # TODO: Implement full LLM conversation loop with tool calling
        # The LLM should be able to:
        # - Ask user questions
        # - Present model options
        # - Call download_model(model_id) when user decides

        return self.result

    def _rule_based_selection(self, system_info: Dict) -> Dict:
        """
        Simple rule-based model selection without LLM.
        Useful as fallback when no LLM is available yet.
        """
        ram_mb = system_info["ram_mb"]
        disk_mb = system_info["disk_mb"]

        # Filter models that fit constraints
        suitable_models = []
        for model in self.context["models"]:
            req_ram = model["requirements"]["ram_mb"]
            req_disk = model["requirements"]["disk_mb"]

            # Add 20% safety margin for RAM
            if req_ram * 1.2 < ram_mb and req_disk < disk_mb:
                suitable_models.append(model)

        if not suitable_models:
            self.set_failure("No models fit your system constraints")
            return self.result

        # Pick the default or smallest model
        chosen = suitable_models[0]
        for model in suitable_models:
            if model.get("default", False):
                chosen = model
                break

        print(f"\nSelected model: {chosen['name']}")
        print(f"  Size: {chosen['size_mb']} MB")
        print(f"  RAM needed: {chosen['requirements']['ram_mb']} MB")

        return self._download_and_configure(chosen)

    def _download_and_configure(self, model: Dict) -> Dict:
        """
        Download a model and configure MoJoAssistant to use it.

        Args:
            model: Model dictionary from catalog

        Returns:
            Result dictionary
        """
        try:
            # Prepare download path
            cache_dir = self.expand_path(
                self.context["catalog"]["download_settings"]["default_cache_dir"]
            )
            cache_dir.mkdir(parents=True, exist_ok=True)

            model_path = cache_dir / model["filename"]

            # Check if already downloaded
            if model_path.exists():
                file_size_mb = model_path.stat().st_size // (1024 * 1024)
                expected_size_mb = model["size_mb"]

                # Allow 10% variance
                if abs(file_size_mb - expected_size_mb) / expected_size_mb < 0.1:
                    print(f"✓ Model already downloaded: {model_path}")
                else:
                    print(f"⚠️  Existing file size mismatch, re-downloading...")
                    model_path.unlink()

            # Download if needed
            if not model_path.exists():
                print(f"Downloading {model['name']}...")
                print(f"  From: {model['download_url']}")
                print(f"  To: {model_path}")

                self._download_with_progress(model["download_url"], model_path, model["size_mb"])

                print(f"✓ Download complete!")

            # Update llm_config.json
            self._update_llm_config(model, model_path)

            self.set_success(
                f"Successfully installed {model['name']}",
                model_id=model["id"],
                model_path=str(model_path),
                model_name=model["name"]
            )

            return self.result

        except Exception as e:
            self.set_failure(f"Download/configuration failed: {e}")
            return self.result

    def _download_with_progress(self, url: str, dest: Path, expected_size_mb: int):
        """Download file with progress bar."""

        def show_progress(block_num, block_size, total_size):
            """Callback for showing download progress."""
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 // total_size)
                mb_downloaded = downloaded // (1024 * 1024)
                mb_total = total_size // (1024 * 1024)

                bar_length = 40
                filled = int(bar_length * percent // 100)
                bar = '█' * filled + '░' * (bar_length - filled)

                print(f"\r  [{bar}] {percent}% ({mb_downloaded}/{mb_total} MB)", end='', flush=True)

        try:
            urllib.request.urlretrieve(url, dest, reporthook=show_progress)
            print()  # New line after progress bar
        except urllib.error.URLError as e:
            raise RuntimeError(f"Download failed: {e}")

    def _update_llm_config(self, model: Dict, model_path: Path):
        """Update llm_config.json with the new model."""
        try:
            # Load existing config or create new one
            try:
                llm_config = self.load_json("llm_config.json")
            except FileNotFoundError:
                llm_config = {
                    "local_models": {},
                    "task_assignments": {}
                }

            # Add model to config
            model_key = model["id"]
            llm_config["local_models"][model_key] = {
                "type": "llama",
                "path": str(model_path),
                "context_length": model["capabilities"]["context_length"],
                "temperature": 0.7,
                "max_tokens": 2048,
                "recommended_for": model["recommended_for"]
            }

            # Set as default for common tasks if it's the default model
            if model.get("default", False):
                llm_config["task_assignments"] = {
                    "interactive_cli": model_key,
                    "dreaming_chunking": model_key,
                    "dreaming_synthesis": model_key,
                    "default": model_key
                }

            # Save config
            self.save_json("llm_config.json", llm_config)
            print(f"✓ Updated llm_config.json")

        except Exception as e:
            raise RuntimeError(f"Config update failed: {e}")

    def _format_catalog_for_llm(self) -> str:
        """Format model catalog for LLM consumption."""
        lines = []
        for model in self.context["models"]:
            lines.append(f"### {model['name']} ({model['id']})")
            lines.append(f"- Size: {model['size_mb']} MB")
            lines.append(f"- RAM needed: {model['requirements']['ram_mb']} MB")
            lines.append(f"- Speed: {model['performance']['speed']}")
            lines.append(f"- Best for: {', '.join(model['recommended_for'])}")
            lines.append(f"- Default: {model.get('default', False)}")
            lines.append("")

        return "\n".join(lines)

    def download_model_by_id(self, model_id: str) -> Dict:
        """
        Public method to download a specific model by ID.
        Can be called by LLM or other agents.
        """
        # Find model in catalog
        model = None
        for m in self.context["models"]:
            if m["id"] == model_id:
                model = m
                break

        if not model:
            self.set_failure(f"Model not found in catalog: {model_id}")
            return self.result

        return self._download_and_configure(model)
