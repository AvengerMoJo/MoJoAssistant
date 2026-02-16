"""
Environment Configurator Agent - guides users through .env setup.

This agent uses LLM to conversationally help users configure their
environment variables based on their use case.
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional

from .base_agent import BaseSetupAgent


class EnvConfiguratorAgent(BaseSetupAgent):
    """Agent for configuring .env file based on user needs."""

    # Minimal settings for different use cases
    TEMPLATES = {
        "local_only": {
            "DEBUG": "false",
            "LOG_LEVEL": "info",
            "MCP_PORT": "8765",
            "MCP_HOST": "localhost",
            "ENABLE_DREAMING": "true",
            "ENABLE_SCHEDULER": "true",
        },
        "cloud_ai": {
            "DEBUG": "false",
            "LOG_LEVEL": "info",
            "MCP_PORT": "8765",
            "MCP_HOST": "localhost",
            "DEFAULT_LLM_PROVIDER": "openai",  # User will specify
            "ENABLE_DREAMING": "true",
            "ENABLE_SCHEDULER": "true",
        },
        "github_integration": {
            "DEBUG": "false",
            "LOG_LEVEL": "info",
            "MCP_PORT": "8765",
            "MCP_HOST": "localhost",
            "ENABLE_OPENCODE": "true",
            "ENABLE_DREAMING": "true",
            "ENABLE_SCHEDULER": "true",
        },
    }

    # API key validation patterns
    API_KEY_PATTERNS = {
        "OPENAI_API_KEY": r"^sk-[A-Za-z0-9_-]{32,}$",
        "ANTHROPIC_API_KEY": r"^sk-ant-[A-Za-z0-9_-]{95,}$",
        "GOOGLE_API_KEY": r"^AIza[A-Za-z0-9_-]{35}$",
        "GITHUB_TOKEN": r"^(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}$",
    }

    def load_context(self) -> Dict:
        """Load agent prompt and templates."""
        try:
            # Load agent prompt
            prompt = self.load_prompt("env_configurator.md")

            # Load .env.example as reference
            env_example_path = Path(".env.example")
            env_example = ""
            if env_example_path.exists():
                with open(env_example_path, "r") as f:
                    env_example = f.read()

            self.context = {
                "prompt": prompt,
                "templates": self.TEMPLATES,
                "env_example": env_example,
                "validation_patterns": self.API_KEY_PATTERNS,
            }

            return self.context

        except Exception as e:
            print(f"Error loading context: {e}")
            return {}

    def execute(self, **kwargs) -> Dict:
        """
        Execute environment configuration.

        Args:
            interactive: If True, use LLM to guide user (default: True)
            use_case: Pre-selected use case (local_only, cloud_ai, github_integration)
            settings: Dict of specific settings to apply

        Returns:
            Result dictionary
        """
        interactive = kwargs.get("interactive", True)
        use_case = kwargs.get("use_case")
        settings = kwargs.get("settings", {})

        try:
            # Load context
            self.load_context()

            # Check if .env already exists
            env_path = Path(".env")
            if env_path.exists():
                print("\n⚠️  .env file already exists")
                if interactive:
                    response = (
                        input("Overwrite it? [y/N]: ").strip().lower()
                    )
                    if response not in ("y", "yes"):
                        self.set_success("Kept existing .env file")
                        return self.result

            # If use case specified, use non-interactive mode
            if use_case:
                return self._create_from_template(use_case, settings)

            # Interactive mode with LLM
            if interactive and self.llm:
                return self._llm_guided_configuration()
            else:
                # Fallback: simple prompt-based configuration
                return self._prompt_based_configuration()

        except Exception as e:
            self.set_failure(f"Environment configuration failed: {e}")
            return self.result

    def _create_from_template(self, use_case: str, additional_settings: Dict = None) -> Dict:
        """Create .env from a template."""
        if use_case not in self.TEMPLATES:
            self.set_failure(f"Unknown use case: {use_case}")
            return self.result

        # Start with template
        settings = self.TEMPLATES[use_case].copy()

        # Add any additional settings
        if additional_settings:
            settings.update(additional_settings)

        # Write .env file
        self._write_env_file(settings)

        self.set_success(
            f"Created .env file for {use_case}",
            use_case=use_case,
            settings=list(settings.keys()),
        )
        return self.result

    def _llm_guided_configuration(self) -> Dict:
        """Use LLM to guide user through configuration."""
        # This will be a full conversation flow
        # For now, placeholder - full implementation would involve
        # multi-turn conversation with the LLM

        print("\n🤖 LLM-guided configuration not yet implemented")
        print("   Falling back to prompt-based configuration...\n")

        return self._prompt_based_configuration()

    def _prompt_based_configuration(self) -> Dict:
        """Simple prompt-based configuration without LLM."""
        print("\n" + "=" * 60)
        print("Environment Configuration")
        print("=" * 60 + "\n")

        print("What will you use MoJoAssistant for?\n")
        print("  1. Local AI only (private, no internet needed)")
        print("  2. Local + Cloud AI (mix of both)")
        print("  3. Cloud AI only (OpenAI/Claude/etc.)")
        print("  4. GitHub integration")
        print("  5. Just trying it out\n")

        while True:
            choice = input("Pick a number (1-5): ").strip()
            if choice in ("1", "5"):
                return self._setup_local_only()
            elif choice == "2":
                return self._setup_mixed()
            elif choice == "3":
                return self._setup_cloud_only()
            elif choice == "4":
                return self._setup_github()
            else:
                print("Please enter a number between 1 and 5")

    def _setup_local_only(self) -> Dict:
        """Set up for local-only usage."""
        print("\n✓ Great! Setting up local-only mode.\n")
        print("  No API keys needed - complete privacy!")

        settings = self.TEMPLATES["local_only"].copy()
        self._write_env_file(settings)

        print("\n✓ Configuration saved!")

        self.set_success("Created local-only configuration", use_case="local_only")
        return self.result

    def _setup_mixed(self) -> Dict:
        """Set up for mixed local + cloud usage."""
        print("\n✓ Setting up mixed mode (local + cloud).\n")

        settings = self.TEMPLATES["cloud_ai"].copy()

        # Ask for API keys
        print("Which cloud provider do you want to use?\n")
        print("  1. OpenAI (ChatGPT)")
        print("  2. Anthropic (Claude)")
        print("  3. Google (Gemini)")
        print("  4. Multiple providers")
        print("  5. Skip for now\n")

        choice = input("Pick a number (1-5): ").strip()

        if choice == "1":
            self._configure_openai(settings)
        elif choice == "2":
            self._configure_anthropic(settings)
        elif choice == "3":
            self._configure_google(settings)
        elif choice == "4":
            self._configure_openai(settings)
            self._configure_anthropic(settings)
            self._configure_google(settings)
        # else skip

        self._write_env_file(settings)
        print("\n✓ Configuration saved!")

        self.set_success("Created mixed-mode configuration", use_case="cloud_ai")
        return self.result

    def _setup_cloud_only(self) -> Dict:
        """Set up for cloud-only usage."""
        return self._setup_mixed()  # Same process

    def _setup_github(self) -> Dict:
        """Set up GitHub integration."""
        print("\n✓ Setting up GitHub integration.\n")

        settings = self.TEMPLATES["github_integration"].copy()

        print("To use GitHub integration, you need a Personal Access Token.\n")
        print("Steps:")
        print("  1. Go to: https://github.com/settings/tokens")
        print("  2. Click 'Generate new token (classic)'")
        print("  3. Give it a name: 'MoJoAssistant'")
        print("  4. Select scopes: repo, user")
        print("  5. Generate and copy the token\n")

        token = input("Paste your GitHub token (or press Enter to skip): ").strip()

        if token:
            if self._validate_api_key("GITHUB_TOKEN", token):
                settings["GITHUB_TOKEN"] = token
                print("✓ GitHub token validated!")
            else:
                print("⚠️  Token format doesn't look right, but I'll save it anyway.")
                settings["GITHUB_TOKEN"] = token

        self._write_env_file(settings)
        print("\n✓ Configuration saved!")

        self.set_success("Created GitHub integration configuration", use_case="github_integration")
        return self.result

    def _configure_openai(self, settings: Dict):
        """Configure OpenAI API key."""
        print("\n📝 OpenAI Configuration")
        print("   Get your API key from: https://platform.openai.com/api-keys\n")

        api_key = input("OpenAI API key (or press Enter to skip): ").strip()

        if api_key:
            if self._validate_api_key("OPENAI_API_KEY", api_key):
                settings["OPENAI_API_KEY"] = api_key
                settings["DEFAULT_LLM_PROVIDER"] = "openai"
                print("✓ OpenAI API key saved!")
            else:
                print("⚠️  That doesn't look like a valid OpenAI key (should start with 'sk-')")
                confirm = input("Save it anyway? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    settings["OPENAI_API_KEY"] = api_key

    def _configure_anthropic(self, settings: Dict):
        """Configure Anthropic API key."""
        print("\n📝 Anthropic Configuration")
        print("   Get your API key from: https://console.anthropic.com/settings/keys\n")

        api_key = input("Anthropic API key (or press Enter to skip): ").strip()

        if api_key:
            if self._validate_api_key("ANTHROPIC_API_KEY", api_key):
                settings["ANTHROPIC_API_KEY"] = api_key
                if "DEFAULT_LLM_PROVIDER" not in settings:
                    settings["DEFAULT_LLM_PROVIDER"] = "anthropic"
                print("✓ Anthropic API key saved!")
            else:
                print("⚠️  That doesn't look like a valid Anthropic key (should start with 'sk-ant-')")
                confirm = input("Save it anyway? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    settings["ANTHROPIC_API_KEY"] = api_key

    def _configure_google(self, settings: Dict):
        """Configure Google API key."""
        print("\n📝 Google Configuration")
        print("   Get your API key from: https://makersuite.google.com/app/apikey\n")

        api_key = input("Google API key (or press Enter to skip): ").strip()

        if api_key:
            if self._validate_api_key("GOOGLE_API_KEY", api_key):
                settings["GOOGLE_API_KEY"] = api_key
                if "DEFAULT_LLM_PROVIDER" not in settings:
                    settings["DEFAULT_LLM_PROVIDER"] = "google"
                print("✓ Google API key saved!")
            else:
                print("⚠️  That doesn't look like a valid Google key")
                confirm = input("Save it anyway? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    settings["GOOGLE_API_KEY"] = api_key

    def _validate_api_key(self, key_name: str, value: str) -> bool:
        """Validate API key format."""
        pattern = self.context["validation_patterns"].get(key_name)
        if not pattern:
            return True  # No validation pattern, assume valid

        return bool(re.match(pattern, value))

    def _write_env_file(self, settings: Dict):
        """Write settings to .env file."""
        env_path = Path(".env")

        with open(env_path, "w") as f:
            f.write("# MoJoAssistant Configuration\n")
            f.write("# Generated by Environment Configurator Agent\n\n")

            # Group settings by category
            for key, value in sorted(settings.items()):
                f.write(f"{key}={value}\n")

        print(f"\n✓ Created {env_path}")

    def add_setting(self, key: str, value: str) -> bool:
        """
        Add or update a setting in .env file.

        Args:
            key: Environment variable name
            value: Environment variable value

        Returns:
            True if successful
        """
        env_path = Path(".env")

        if not env_path.exists():
            # Create new file
            self._write_env_file({key: value})
            return True

        # Read existing file
        with open(env_path, "r") as f:
            lines = f.readlines()

        # Update or append setting
        key_found = False
        new_lines = []

        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                key_found = True
            else:
                new_lines.append(line)

        if not key_found:
            new_lines.append(f"\n{key}={value}\n")

        # Write back
        with open(env_path, "w") as f:
            f.writelines(new_lines)

        return True
