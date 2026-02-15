"""
Model Selector Agent - helps users choose and download LLM models.

Robust download features:
- Uses huggingface_hub library for automatic resume support
- Checks HuggingFace cache before re-downloading
- Supports HF_ENDPOINT for mirror sites (e.g., https://hf-mirror.com for China)
- Smart existing file detection with size verification
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

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
            docs = self.load_documentation(
                ["docs/installation/MODEL_DOWNLOADER_GUIDE.md"]
            )

            self.context = {
                "catalog": catalog,
                "prompt": prompt,
                "documentation": docs,
                "models": catalog.get("models", []),
                "categories": catalog.get("categories", {}),
                "recommendations": catalog.get("use_case_recommendations", {}),
                "download_settings": catalog.get("download_settings", {}),
                "mirror_config": catalog.get("mirror_config", {}),
            }

            return self.context

        except Exception as e:
            print(f"Error loading context: {e}")
            self.context = {}
            return self.context

    def execute(self, **kwargs) -> Dict:
        """
        Execute model selection and download.

        Args:
            system_info: Dictionary with system constraints (ram_mb, disk_mb, etc.)
            auto_default: If True, automatically use default model without asking

        Returns:
            Result dictionary
        """
        system_info = kwargs.get("system_info")
        auto_default = kwargs.get("auto_default", False)

        try:
            # Load context
            self.load_context()

            if not self.context.get("models"):
                self.set_failure("Model catalog not loaded")
                return self.result

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
            "has_gpu": False,  # TODO: Detect GPU
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
{self.context["prompt"]}

## Current System Information

- Available RAM: {system_info["ram_mb"]} MB
- Free Disk Space: {system_info["disk_mb"]} MB
- GPU Available: {system_info.get("has_gpu", False)}

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

            # Check if already downloaded in MoJo cache
            if model_path.exists():
                file_size_mb = model_path.stat().st_size // (1024 * 1024)
                expected_size_mb = model["size_mb"]

                # Allow 15% variance for different quantizations
                size_diff = abs(file_size_mb - expected_size_mb) / expected_size_mb
                if size_diff < 0.15:
                    print(f"✓ Model already downloaded: {model_path}")
                    print(f"  Size: {file_size_mb} MB")
                else:
                    print(
                        f"⚠️  Existing file size mismatch ({file_size_mb} vs {expected_size_mb} MB)"
                    )
                    print(f"   Re-downloading...")
                    model_path.unlink()

            # Download if needed
            if not model_path.exists():
                print(f"\n📥 Downloading {model['name']}...")
                print(f"   Repository: {model['huggingface_repo']}")
                print(f"   File: {model['filename']}")

                # Check for mirror configuration
                self._check_mirror_configuration()

                # Try to use huggingface_hub first (better resume support)
                download_success = self._download_with_hf_hub(model, model_path)

                if not download_success:
                    # Fallback to direct URL download
                    print("\n   Falling back to direct download...")
                    download_success = self._download_with_progress(
                        model["download_url"], model_path, model["size_mb"]
                    )

                if not download_success:
                    self.set_failure(f"Failed to download {model['name']}")
                    return self.result

                print(f"\n✓ Download complete!")

            # Update llm_config.json
            self._update_llm_config(model, model_path)

            self.set_success(
                f"Successfully installed {model['name']}",
                model_id=model["id"],
                model_path=str(model_path),
                model_name=model["name"],
            )

            return self.result

        except Exception as e:
            self.set_failure(f"Download/configuration failed: {e}")
            return self.result

    def _check_mirror_configuration(self):
        """Check and display mirror configuration for users."""
        hf_endpoint = os.environ.get("HF_ENDPOINT", "")
        default_endpoint = self.context.get("download_settings", {}).get(
            "hf_endpoint", "https://huggingface.co"
        )

        if hf_endpoint:
            print(f"   Using mirror: {hf_endpoint}")
            if "hf-mirror.com" in hf_endpoint:
                print("   (China mirror detected - downloads may be faster)")
        elif default_endpoint != "https://huggingface.co":
            print(f"   Using configured endpoint: {default_endpoint}")

    def _download_with_hf_hub(self, model: Dict, dest: Path) -> bool:
        """
        Download using huggingface_hub library (with resume support).

        Args:
            model: Model dictionary
            dest: Destination path

        Returns:
            True if successful, False otherwise
        """
        try:
            from huggingface_hub import hf_hub_download
            from huggingface_hub.constants import HF_HUB_CACHE

            repo_id = model["huggingface_repo"]
            filename = model["filename"]

            print(f"\n   Using huggingface_hub (with resume support)...")

            # First, check if already in HF cache
            try:
                cached_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_files_only=True,  # Don't download, just check cache
                )
                if cached_path and Path(cached_path).exists():
                    print(f"   ✓ Found in HuggingFace cache")
                    print(f"   Copying to MoJo cache...")
                    import shutil

                    shutil.copy2(cached_path, dest)
                    return True
            except Exception:
                # Not in cache, proceed with download
                pass

            # Download using hf_hub_download (handles resume automatically)
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(dest.parent),
                local_dir_use_symlinks=False,
            )  # type: ignore

            # If downloaded to different path, move to expected location
            if Path(downloaded_path) != dest:
                Path(downloaded_path).rename(dest)

            return True

        except ImportError:
            print("   huggingface_hub not installed, using fallback...")
            return False
        except Exception as e:
            print(f"   huggingface_hub download failed: {e}")
            return False

    def _download_with_progress(
        self, url: str, dest: Path, expected_size_mb: int
    ) -> bool:
        """
        Download file with progress bar using urllib (fallback method).

        Args:
            url: Download URL
            dest: Destination path
            expected_size_mb: Expected file size in MB

        Returns:
            True if successful, False otherwise
        """
        import urllib.request
        import urllib.error

        # Check for partial download
        partial_file = dest.with_suffix(dest.suffix + ".part")
        if partial_file.exists():
            print(f"   Resuming partial download...")

        def show_progress(block_num, block_size, total_size):
            """Callback for showing download progress."""
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 // total_size)
                mb_downloaded = downloaded // (1024 * 1024)
                mb_total = total_size // (1024 * 1024)

                bar_length = 40
                filled = int(bar_length * percent // 100)
                bar = "█" * filled + "░" * (bar_length - filled)

                print(
                    f"\r   [{bar}] {percent}% ({mb_downloaded}/{mb_total} MB)",
                    end="",
                    flush=True,
                )

        try:
            # Set up request with headers
            headers = {"User-Agent": "MoJoAssistant/1.0"}

            req = urllib.request.Request(url, headers=headers)

            # Download to partial file first
            download_target = partial_file if partial_file.exists() else dest

            urllib.request.urlretrieve(url, download_target, reporthook=show_progress)
            print()  # New line after progress bar

            # If we downloaded to partial file, move to final location
            if download_target == partial_file:
                partial_file.rename(dest)

            return True

        except urllib.error.URLError as e:
            print(f"\n   ✗ Download failed: {e}")

            # Provide helpful message for connection issues
            if "Name or service not known" in str(e) or "getaddrinfo" in str(e):
                print("\n   💡 Tip: If you're in China, try setting HF_ENDPOINT:")
                print("      export HF_ENDPOINT=https://hf-mirror.com")
                print("      Then run this command again.")

            return False
        except Exception as e:
            print(f"\n   ✗ Download error: {e}")
            return False

    def _update_llm_config(self, model: Dict, model_path: Path):
        """Update llm_config.json with the new model."""
        try:
            # Load existing config or create new one
            try:
                llm_config = self.load_json("llm_config.json")
            except FileNotFoundError:
                llm_config = {"local_models": {}, "task_assignments": {}}

            # Add model to config
            model_key = model["id"]
            llm_config["local_models"][model_key] = {
                "type": "llama",
                "path": str(model_path),
                "context_length": model["capabilities"]["context_length"],
                "temperature": 0.7,
                "max_tokens": 2048,
                "recommended_for": model["recommended_for"],
            }

            # Set as default for common tasks if it's the default model
            if model.get("default", False):
                llm_config["task_assignments"] = {
                    "interactive_cli": model_key,
                    "dreaming_chunking": model_key,
                    "dreaming_synthesis": model_key,
                    "default": model_key,
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
        # Make sure context is loaded
        if not self.context:
            self.load_context()

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

    def check_model_in_cache(self, model_id: str) -> Optional[Path]:
        """
        Check if a model is already downloaded (in MoJo or HF cache).

        Args:
            model_id: Model ID from catalog

        Returns:
            Path to model file if found, None otherwise
        """
        # Make sure context is loaded
        if not self.context:
            self.load_context()

        # Find model in catalog
        model = None
        for m in self.context["models"]:
            if m["id"] == model_id:
                model = m
                break

        if not model:
            return None

    def search_and_add_model(self, query: str, interactive: bool = True) -> Dict:
        """
        Search HuggingFace for a model matching the query and add it to catalog.

        Args:
            query: Search query (e.g., "gpt-oss-20b", "openai small model")
            interactive: If True, ask user to select from results

        Returns:
            Result dictionary
        """
        print(f"\n🔍 Searching HuggingFace for: '{query}'")
        print("   Looking for GGUF format models...\n")

        try:
            from huggingface_hub import HfApi

            api = HfApi()

            # Search for models matching query, then filter for GGUF
            models = list(
                api.list_models(
                    search=query,
                    limit=20,
                )
            )

            # Filter for GGUF models (check tags or gguf boolean field)
            gguf_models = []
            for m in models:
                if getattr(m, "gguf", False):
                    gguf_models.append(m)
                elif m.tags and ("gguf" in m.tags or "GGUF" in m.tags):
                    gguf_models.append(m)

            if not gguf_models:
                print(f"❌ No GGUF models found for '{query}'")
                print("\n💡 Tips:")
                print(
                    "   - Try a more specific name (e.g., 'gpt-oss-20b' instead of 'openai')"
                )
                print("   - Check the model name on HuggingFace")
                print("   - Make sure the model has GGUF format files")
                self.set_failure(f"No models found for: {query}")
                return self.result

            # Filter and format results
            print(f"✓ Found {len(gguf_models)} GGUF models:\n")
            valid_models = []

            for i, model in enumerate(gguf_models, 1):
                model_info = self._get_model_info(model.modelId)
                if model_info:
                    valid_models.append(model_info)
                    print(f"  {i}. {model_info['name']}")
                    print(f"     Repo: {model_info['repo']}")
                    print(f"     Size: {model_info.get('size_mb', 'Unknown')} MB")
                    print(f"     Tags: {', '.join(model_info.get('tags', [])[:3])}")
                    print()

            if not valid_models:
                print("❌ No valid GGUF models with downloadable files found")
                self.set_failure("No valid models found")
                return self.result

            if interactive:
                # Ask user to select
                while True:
                    try:
                        choice = input(
                            "Select a model (number) or 'q' to quit: "
                        ).strip()
                        if choice.lower() == "q":
                            self.set_failure("Cancelled by user")
                            return self.result

                        idx = int(choice) - 1
                        if 0 <= idx < len(valid_models):
                            selected = valid_models[idx]
                            break
                        else:
                            print(
                                f"   Please enter a number between 1 and {len(valid_models)}"
                            )
                    except ValueError:
                        print("   Please enter a valid number or 'q'")

                print(f"\n✓ Selected: {selected['name']}")

                # Confirm addition
                confirm = (
                    input("\nAdd this model to catalog and download? [Y/n]: ")
                    .strip()
                    .lower()
                )
                if confirm and confirm not in ("y", "yes"):
                    self.set_failure("Cancelled by user")
                    return self.result

                # Add to catalog and download
                return self._add_model_to_catalog_and_download(selected)
            else:
                # Auto-select first valid model
                return self._add_model_to_catalog_and_download(valid_models[0])

        except ImportError:
            print("❌ huggingface_hub not installed")
            print("   Install with: pip install huggingface-hub")
            self.set_failure("huggingface_hub not installed")
            return self.result
        except Exception as e:
            print(f"❌ Search failed: {e}")
            self.set_failure(f"Search failed: {e}")
            return self.result

    def _get_model_info(self, repo_id: str) -> Optional[Dict]:
        """Get information about a model from HuggingFace."""
        try:
            from huggingface_hub import model_info, list_repo_files
            from huggingface_hub.errors import EntryNotFoundError

            info = model_info(repo_id)

            # Find GGUF files in repo
            files = list_repo_files(repo_id)
            gguf_files = [f for f in files if f.endswith(".gguf")]

            if not gguf_files:
                return None

            # Prefer Q4_K_M or Q5_K_M quantizations
            preferred_file = None
            for pref in ["Q4_K_M", "Q5_K_M", "Q4_K_S", "Q5_K_S", "Q4_0"]:
                for f in gguf_files:
                    if pref in f:
                        preferred_file = f
                        break
                if preferred_file:
                    break

            if not preferred_file:
                preferred_file = gguf_files[0]  # Take first available

            # Try to get file size
            size_mb = 0
            try:
                from huggingface_hub import get_hf_file_metadata

                file_metadata = get_hf_file_metadata(
                    f"https://huggingface.co/{repo_id}/resolve/main/{preferred_file}"
                )
                if file_metadata.size:
                    size_mb = file_metadata.size // (1024 * 1024)
            except Exception:
                # Estimate from filename or use default
                if "1.5" in repo_id or "1.7" in repo_id:
                    size_mb = 1200
                elif "3" in repo_id:
                    size_mb = 2000
                elif "7" in repo_id:
                    size_mb = 4500
                elif "20" in repo_id:
                    size_mb = 12000
                else:
                    size_mb = 2000  # default estimate

            # Extract model name from repo
            name = repo_id.split("/")[-1].replace("-GGUF", "").replace("_GGUF", "")
            name = name.replace("-", " ").replace("_", " ")

            # Generate ID
            model_id = name.lower().replace(" ", "-").replace(".", "")[:30]

            return {
                "name": name,
                "repo": repo_id,
                "filename": preferred_file,
                "size_mb": size_mb,
                "tags": info.tags[:5] if info.tags else [],
                "id": model_id,
            }

        except Exception as e:
            return None

    def _add_model_to_catalog_and_download(self, model_info: Dict) -> Dict:
        """Add a model to the catalog and download it."""
        try:
            # Load current catalog
            catalog = self.load_json("model_catalog.json")

            # Create model entry
            new_model = {
                "id": model_info["id"],
                "name": model_info["name"],
                "type": "gguf",
                "huggingface_repo": model_info["repo"],
                "filename": model_info["filename"],
                "download_url": f"https://huggingface.co/{model_info['repo']}/resolve/main/{model_info['filename']}",
                "size_mb": model_info["size_mb"],
                "sha256": None,
                "requirements": {
                    "ram_mb": model_info["size_mb"] * 2,  # Rough estimate
                    "disk_mb": model_info["size_mb"] + 200,
                    "gpu": False,
                },
                "capabilities": {
                    "context_length": 8192,  # Default, should detect from model card
                    "multilingual": "multilingual" in model_info.get("tags", []),
                    "coding": any(
                        tag in model_info.get("tags", [])
                        for tag in ["code", "coding", "programming"]
                    ),
                    "vision": "vision" in model_info.get("tags", []),
                    "function_calling": False,  # Hard to detect automatically
                },
                "performance": {
                    "speed": "medium",
                    "quality": "good",
                    "tokens_per_second_cpu": "10-15",
                },
                "recommended_for": ["general chat", "custom model"],
                "category": "custom",
            }

            # Check if model already exists
            existing_idx = None
            for i, m in enumerate(catalog["models"]):
                if m["id"] == new_model["id"]:
                    existing_idx = i
                    break

            if existing_idx is not None:
                # Update existing
                catalog["models"][existing_idx] = new_model
                print(f"✓ Updated existing model entry: {new_model['id']}")
            else:
                # Add new
                catalog["models"].append(new_model)
                print(f"✓ Added new model to catalog: {new_model['id']}")

            # Save catalog
            self.save_json("model_catalog.json", catalog)

            # Reload context
            self.load_context()

            # Download the model
            print(f"\n📥 Downloading {new_model['name']}...")
            return self._download_and_configure(new_model)

        except Exception as e:
            self.set_failure(f"Failed to add model: {e}")
            return self.result

        # Check MoJo cache
        cache_dir = self.expand_path(
            self.context["catalog"]["download_settings"]["default_cache_dir"]
        )
        model_path = cache_dir / model["filename"]

        if model_path.exists():
            file_size_mb = model_path.stat().st_size // (1024 * 1024)
            expected_size_mb = model["size_mb"]
            size_diff = abs(file_size_mb - expected_size_mb) / expected_size_mb

            if size_diff < 0.15:
                return model_path

        # Check HuggingFace cache
        try:
            from huggingface_hub import hf_hub_download

            cached_path = hf_hub_download(
                repo_id=model["huggingface_repo"],
                filename=model["filename"],
                local_files_only=True,
            )
            if cached_path and Path(cached_path).exists():
                return Path(cached_path)
        except Exception:
            pass

        return None
