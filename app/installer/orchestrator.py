"""
Smart Installer Orchestrator

Coordinates setup agents to guide users through installation.
Runs agents in sequence:
  1. Model Selector - Download LLM
  2. Env Configurator - Configure .env
  3. (Future) Config Validator - Validate setup
  4. (Future) Test Runner - Verify everything works
"""

import os
import sys
from pathlib import Path
from typing import Optional

from .agents.model_selector import ModelSelectorAgent
from .agents.env_configurator import EnvConfiguratorAgent
from .bootstrap_llm import BootstrapLLM


class SmartInstaller:
    """Orchestrates the installation process using agents."""

    def __init__(self, quiet: bool = True):
        """
        Initialize the installer.

        Args:
            quiet: If True, suppress LLM debug output
        """
        self.quiet = quiet
        self.agents = {}
        self.llm = None  # Bootstrap LLM for powering agents
        self.llm_started = False

    def run(self, interactive: bool = True, auto_defaults: bool = False):
        """
        Run the full installation process.

        Args:
            interactive: If True, ask user questions
            auto_defaults: If True, use all defaults without asking

        Returns:
            True if successful, False otherwise
        """
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          MoJoAssistant Smart Installer                        ║
║                                                              ║
║  AI-powered setup that configures everything for you        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """)

        try:
            # Step 1: Pre-flight checks
            print("🔍 Running pre-flight checks...")
            if not self._check_prerequisites():
                return False

            print("✓ Prerequisites OK\n")

            # Step 2: Model selection (no LLM needed yet)
            if not self._run_model_selector(interactive, auto_defaults):
                return False

            # Step 3: Start Bootstrap LLM (after model is downloaded)
            if interactive and not auto_defaults:
                print("\n🧠 Starting AI assistant for guided setup...")
                self.llm = BootstrapLLM()
                self.llm_started = self.llm.start(quiet=self.quiet)
                if self.llm_started:
                    print("  ✓ AI assistant ready\n")
                else:
                    print("  ℹ️  Using rule-based setup (AI not available)\n")

            # Step 4: Environment configuration (with AI if available)
            if not self._run_env_configurator(interactive, auto_defaults):
                return False

            # Step 5: Validate configuration
            print("\n🧪 Validating configuration...")
            if not self._validate_setup():
                print("⚠️  Some validation checks failed, but you can continue.")
                if interactive:
                    response = input("Continue anyway? [Y/n]: ").strip().lower()
                    if response and response not in ("y", "yes"):
                        return False

            # Success!
            print("\n" + "=" * 60)
            print("✅ Setup Complete!")
            print("=" * 60)
            print("\nYou can now:")
            print("  • Run interactive CLI:  python app/interactive-cli.py")
            print("  • Start MCP server:     python unified_mcp_server.py --mode stdio")
            print("\nHave fun with MoJoAssistant! 🚀")
            print()

            return True

        except KeyboardInterrupt:
            print("\n\n⚠️  Setup cancelled by user")
            return False
        except Exception as e:
            print(f"\n❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Clean up LLM server if we started one
            if self.llm and self.llm_started:
                print("\n🛑 Stopping AI assistant...")
                self.llm.stop()

    def _check_prerequisites(self) -> bool:
        """Check basic prerequisites."""
        # Check Python version
        if sys.version_info < (3, 9):
            print(f"❌ Python 3.9+ required (you have {sys.version_info.major}.{sys.version_info.minor})")
            return False

        # Check we're in the right directory
        if not Path("app/interactive-cli.py").exists():
            print("❌ Please run this from the MoJoAssistant root directory")
            return False

        return True

    def _run_model_selector(self, interactive: bool, auto_defaults: bool) -> bool:
        """Run the model selector agent."""
        print("\n📦 Step 1: Model Selection")
        print("-" * 60)

        # Check if model already exists
        llm_config_path = Path("config/llm_config.json")
        model_exists = False
        existing_model_id = None

        if llm_config_path.exists():
            import json
            try:
                with open(llm_config_path) as f:
                    config = json.load(f)

                for model_id, model_config in config.get("local_models", {}).items():
                    model_path = Path(model_config.get("path", "")).expanduser()
                    if model_path.exists():
                        model_exists = True
                        existing_model_id = model_id
                        print(f"✓ Found existing model: {model_id}")
                        break

            except Exception as e:
                print(f"⚠️  Error reading config: {e}")

        # If model exists and we're in auto mode, just use it
        if model_exists and auto_defaults:
            return True

        # If model exists and we're interactive, skip (user can change manually later)
        if model_exists and not auto_defaults:
            print("  (To change models later, run: python demo_model_selector.py)\n")
            return True

        # No model exists - need to download one
        print("\nNo model found. Let's download one!\n")

        # Create agent
        agent = ModelSelectorAgent(llm=None, config_dir="config")

        if auto_defaults:
            # Use default model
            print("Using default recommended model...\n")
            result = agent.execute(auto_default=True)
        else:
            # Interactive: offer default or search
            print("Choose an option:")
            print("  1. Use recommended model (Qwen3-1.7B - fast, general purpose)")
            print("  2. Search HuggingFace for a specific model")
            print()

            choice = input("Your choice [1-2]: ").strip()

            if choice == "2":
                # Search option
                print()
                query = input("Search for (e.g., 'llama 3.1', 'qwen coder', 'phi-3'): ").strip()
                if not query:
                    print("No search query provided, using default model...")
                    result = agent.execute(auto_default=True)
                else:
                    result = agent.search_and_add_model(query, interactive=True)
            else:
                # Default option (choice == "1" or anything else)
                print("\nUsing recommended model...\n")
                result = agent.execute(auto_default=True)

        if not result["success"]:
            print(f"❌ Model selection failed: {result['message']}")
            return False

        print(f"\n✓ {result['message']}")
        return True

    def _run_env_configurator(self, interactive: bool, auto_defaults: bool) -> bool:
        """Run the environment configurator agent."""
        print("\n⚙️  Step 2: Environment Configuration")
        print("-" * 60)

        # Check if .env already exists
        env_path = Path(".env")
        if env_path.exists():
            print("✓ .env file found")

            if interactive and not auto_defaults:
                response = input("Reconfigure .env? [y/N]: ").strip().lower()
                if response not in ("y", "yes"):
                    return True
            else:
                return True

        # Run env configurator agent (pass LLM if we have one)
        agent = EnvConfiguratorAgent(llm=self.llm if self.llm_started else None, config_dir="config")

        if auto_defaults:
            result = agent.execute(interactive=False, use_case="local_only")
        else:
            result = agent.execute(interactive=True)

        if not result["success"]:
            print(f"❌ Environment configuration failed: {result['message']}")
            return False

        print(f"✓ {result['message']}")
        return True

    def _validate_setup(self) -> bool:
        """Validate the setup."""
        checks_passed = 0
        checks_total = 0

        # Check 1: llm_config.json exists
        checks_total += 1
        if Path("config/llm_config.json").exists():
            print("  ✓ LLM configuration found")
            checks_passed += 1
        else:
            print("  ✗ LLM configuration missing")

        # Check 2: .env exists
        checks_total += 1
        if Path(".env").exists():
            print("  ✓ Environment file found")
            checks_passed += 1
        else:
            print("  ✗ Environment file missing")

        # Check 3: At least one model exists
        checks_total += 1
        try:
            import json
            with open("config/llm_config.json") as f:
                config = json.load(f)

            for model_id, model_config in config.get("local_models", {}).items():
                model_path = Path(model_config.get("path", "")).expanduser()
                if model_path.exists():
                    print(f"  ✓ Model file found: {model_id}")
                    checks_passed += 1
                    break
            else:
                print("  ✗ No model files found")
        except Exception as e:
            print(f"  ✗ Could not verify model: {e}")

        print(f"\n  Passed {checks_passed}/{checks_total} checks")

        return checks_passed == checks_total


def run_smart_installer(interactive: bool = True, auto_defaults: bool = False) -> int:
    """
    Run the smart installer.

    Args:
        interactive: If True, ask user questions
        auto_defaults: If True, use all defaults

    Returns:
        0 if successful, 1 if failed
    """
    installer = SmartInstaller(quiet=True)
    success = installer.run(interactive=interactive, auto_defaults=auto_defaults)
    return 0 if success else 1
