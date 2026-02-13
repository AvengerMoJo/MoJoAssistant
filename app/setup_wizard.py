#!/usr/bin/env python3
"""
MoJoAssistant AI Setup Wizard

Conversational setup wizard that uses Qwen3 1.7B to guide users through
configuration with access to all documentation.

This wizard:
- Reads all documentation files
- Asks questions one-by-one
- Fills out .env file based on answers
- Handles complex scenarios (MCP modes, passwords, OpenCode, etc.)
"""

import asyncio
import sys
import os
import json
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class SetupWizard:
    """AI-powered setup wizard with documentation knowledge"""

    def __init__(self, llm):
        """Initialize wizard with LLM interface"""
        self.llm = llm
        self.conversation_history = []
        self.setup_data = {}

        # Documentation files to load
        self.docs_to_load = [
            "README.md",
            "app/mcp/opencode/README.md",
            "app/mcp/opencode/CONFIGURATION.md",
            "app/mcp/opencode/ARCHITECTURE_N_TO_1.md",
        ]

    async def load_documentation(self) -> str:
        """Load all documentation into context"""
        print("\n📚 Loading documentation knowledge base...")
        docs_context = ""

        for doc_path in self.docs_to_load:
            if os.path.exists(doc_path):
                try:
                    with open(doc_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        # Truncate if too long
                        if len(content) > 10000:
                            content = content[:10000] + "\n... [truncated]"
                        docs_context += f"\n\n=== {doc_path} ===\n{content}"
                        print(f"  ✅ Loaded: {doc_path}")
                except Exception as e:
                    print(f"  ⚠️  Failed to load {doc_path}: {e}")

        print(f"\n✓ Loaded {len(self.docs_to_load)} documentation files")
        return docs_context

    async def start_setup(self) -> bool:
        """Start the conversational setup flow"""
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          MoJoAssistant AI Setup Wizard                        ║
║                                                              ║
║  I'll help you configure MoJoAssistant using Qwen3 1.7B      ║
║                                                              ║
║  I have access to all documentation to answer your questions  ║
║  about MoJoAssistant, OpenCode Manager, and configuration    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

        # Load documentation
        docs = await self.load_documentation()

        # Start conversational flow
        conversation = [
            "Welcome to MoJoAssistant setup!",
            "I'm your AI setup assistant. I'll ask you questions one-by-one",
            "and configure everything for you based on your answers.",
            "",
            "First, tell me: What do you want to use MoJoAssistant for?",
        ]

        # Run conversation loop
        answer = None
        for message in conversation:
            await self.add_message(message)
            print(f"\n🤖 {message}")
            answer = await self.get_user_input()
            await self.add_message(f"User: {answer}")
            print(f"\n✓ Got: {answer}")
            await asyncio.sleep(0.5)

        # Analyze response and ask next questions
        if answer:
            await self.ask_for_use_case(answer, docs)
        else:
            await self.ask_for_use_case("No specific use case provided", docs)
        await self.ask_for_llm_preference(docs)
        await self.ask_for_mcp_mode(docs)
        await self.ask_for_passwords(docs)
        await self.ask_for_opencode(docs)
        await self.ask_for_advanced_options(docs)

        # Generate configuration
        print("\n" + "=" * 60)
        print("✓ Setup complete! Generating configuration...")
        print("=" * 60)

        await self.generate_config()

        return True

    async def ask_for_use_case(self, first_answer: str, docs: str):
        """Ask about the user's use case"""
        response = await self.llm.generate_response(first_answer, docs)
        if response:
            await self.add_message(response)
            print(f"\n{response}")

            self.setup_data["priorities"] = response
        else:
            self.setup_data["priorities"] = "Balanced approach"

    async def ask_for_llm_preference(self, docs: str):
        """Ask about LLM preferences"""
        prompt = f"""What LLM would you like to use? I have these options:

 1. Local Qwen3 1.7B (free, private, no API needed)
 2. OpenAI GPT-4 (paid, high quality)
 3. Anthropic Claude (paid, high quality)
 4. Local model (you have, no API needed)

 Tell me your preference."""

        response = await self.llm.generate_response(prompt, docs)
        await self.add_message(response)
        print(f"\n{response}")

        self.setup_data["llm_choice"] = response

    async def ask_for_mcp_mode(self, docs: str):
        """Ask about MCP mode"""
        prompt = f"""How do you want to connect AI clients?

 1. STDIO mode (e.g., Claude Desktop, chatmcp)
    - Local connection, no network
    - Simple setup
    - Recommended for desktop apps

 2. HTTP Stream mode (e.g., web apps, browser extensions)
    - Network connection
    - More flexible
    - Requires HTTP server

 Tell me your preference."""

        response = await self.llm.generate_response(prompt, docs)
        await self.add_message(response)
        print(f"\n{response}")

        self.setup_data["mcp_mode"] = response

    async def ask_for_passwords(self, docs: str):
        """Ask about password configuration"""
        prompt = f"""Security: What password do you want to use?

 1. Generate a strong random password (recommended)
    - I'll generate one for you
    - Changes regularly
    - No copy-paste needed

 2. Use a specific password
    - You provide the password
    - You manage it
    - You can change it later"""

        response = await self.llm.generate_response(prompt, docs)
        await self.add_message(response)
        print(f"\n{response}")

        self.setup_data["password_choice"] = response

    async def ask_for_opencode(self, docs: str):
        """Ask about OpenCode Manager"""
        prompt = f"""Do you want to set up OpenCode Manager for AI coding agents?

 1. Yes, set up OpenCode Manager
    - Manage AI coding projects
    - SSH key management
    - Multiple AI agent orchestration

 2. No, skip OpenCode Manager
    - Skip for now
    - Set up later

 3. Maybe, ask me more"""

        response = await self.llm.generate_response(prompt, docs)
        await self.add_message(response)
        print(f"\n{response}")

        self.setup_data["opencode_choice"] = response

    async def ask_for_advanced_options(self, docs: str):
        """Ask about advanced options"""
        prompt = f"""Additional features to enable:

 1. Dreaming (memory consolidation)
    - Automatic nightly memory consolidation
    - Improves search accuracy
    - 3 AM schedule

 2. Scheduler (background tasks)
    - Background job execution
    - Recurring tasks
    - Resource management

 3. Both dreaming and scheduler

 4. None (basic setup)"""

        response = await self.llm.generate_response(prompt, docs)
        await self.add_message(response)
        print(f"\n{response}")

        self.setup_data["features"] = response

    async def generate_config(self):
        """Generate configuration based on setup data"""
        print("\n\n📝 Generating configuration files...")
        await asyncio.sleep(0.5)

        # Generate .env content
        env_content = self._generate_env_content()

        # Save .env
        env_file = Path(".env")
        with open(env_file, "w") as f:
            f.write(env_content)
        print(f"  ✓ Created: {env_file}")

        # Generate LLM config
        llm_config = self._generate_llm_config()
        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)
        llm_config_file = config_dir / "llm_config.json"
        with open(llm_config_file, "w") as f:
            f.write(json.dumps(llm_config, indent=2))
        print(f"  ✓ Created: {llm_config_file}")

        # Generate memory directory
        memory_dir = Path.home() / ".memory"
        memory_dir.mkdir(exist_ok=True)
        (memory_dir / "conversations").mkdir(exist_ok=True)
        (memory_dir / "dreams").mkdir(exist_ok=True)
        (memory_dir / "embeddings").mkdir(exist_ok=True)
        print(f"  ✓ Created: {memory_dir}/")

        # Print summary
        print("\n" + "=" * 60)
        print("Configuration Generated!")
        print("=" * 60)
        print(f"\nUse case: {self.setup_data.get('use_case', 'N/A')}")
        print(f"LLM: {self.setup_data.get('llm_choice', 'N/A')}")
        print(f"MCP Mode: {self.setup_data.get('mcp_mode', 'N/A')}")
        print(f"OpenCode: {self.setup_data.get('opencode_choice', 'N/A')}")
        print(f"Features: {self.setup_data.get('features', 'N/A')}")

        print("\n✓ Setup wizard complete!")
        print("\nNext steps:")
        print("  1. Review the .env file")
        print("  2. Adjust any settings if needed")
        print("  3. Run: python app/interactive-cli.py")
        print("  4. Or: ./run_cli.sh")

        return True

    def _generate_env_content(self) -> str:
        """Generate .env content based on setup data"""
        # Default values
        llm_choice = self.setup_data.get("llm_choice", "Local Qwen3 1.7B")
        mcp_mode = self.setup_data.get("mcp_mode", "STDIO mode")
        opencode = self.setup_data.get("opencode_choice", "No, skip OpenCode Manager")

        # Determine actual settings
        if "local" in llm_choice.lower():
            llm_type = "local"
            embedding_backend = "huggingface"
        else:
            llm_type = "api"
            embedding_backend = "openai"

        if "http" in mcp_mode.lower():
            mcp_mode_value = "http"
        else:
            mcp_mode_value = "stdio"

        # Generate password
        if "generate" in self.setup_data.get("password_choice", "").lower():
            import secrets

            password = secrets.token_urlsafe(32)
            bearer_token = secrets.token_urlsafe(32)
        else:
            # Generate placeholder
            password = "auto-generated-changed-me"
            bearer_token = "auto-generated-changed-me"

        # Build env content
        env = f"""# MoJoAssistant Configuration
# Generated by AI Setup Wizard on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
CORS_ORIGINS=*
LOG_LEVEL=INFO
LOG_CONSOLE=true
ENVIRONMENT=development
DEBUG=false

# =============================================================================
# MCP CONFIGURATION
# =============================================================================
MCP_API_KEY={bearer_token}
MCP_REQUIRE_AUTH=true
"""

        if mcp_mode_value == "http":
            env += f"""# MCP in HTTP mode for web integration
MCP_SERVER_PORT=3005
"""
        else:
            env += f"""# MCP in STDIO mode for Claude Desktop
"""

        env += f"""# =============================================================================
# LLM CONFIGURATION
# =============================================================================
"""

        if llm_type == "local":
            env += f"""# Local LLM (Qwen3 1.7B)
LOCAL_MODEL_PATH=~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_BACKEND={embedding_backend}
"""
        else:
            # API mode (placeholder for API keys)
            env += f"""# API LLM (OpenAI/Anthropic)
# Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_BACKEND=openai
"""

        env += f"""# =============================================================================
# MEMORY CONFIGURATION
# =============================================================================
MEMORY_DATA_DIR=~/.memory
DREAMING_ENABLED=true
DREAMING_SCHEDULE=0 3 * * *

# =============================================================================
# SCHEDULER CONFIGURATION
# =============================================================================
SCHEDULER_ENABLED=true
SCHEDULER_TICK_INTERVAL=60
"""

        if "opencode" in opencode.lower() and "yes" in opencode.lower():
            env += """# =============================================================================
# OPENCODE MANAGER
# =============================================================================
OPENCODE_MCP_TOOL_PATH=auto-detected
OPENCODE_BIN=auto-detected
"""

        env += """# =============================================================================
# Generated by MoJoAssistant AI Setup Wizard
# Date: {}""".format(datetime.now().strftime("%Y-%m-%d"))

        return env

    def _generate_llm_config(self) -> Dict[str, Any]:
        """Generate LLM configuration"""
        llm_choice = self.setup_data.get("llm_choice", "Local Qwen3 1.7B")

        if "local" in llm_choice.lower():
            return {
                "local_models": {
                    "qwen3-1.7b": {
                        "path": "~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B",
                        "type": "qwen",
                        "n_threads": 4,
                        "timeout": 60,
                    }
                },
                "default_interface": "qwen3-1.7b",
            }
        else:
            # API mode config (placeholder)
            return {
                "api_models": {
                    "openai": {
                        "provider": "openai",
                        "api_key": "YOUR_OPENAI_API_KEY",
                        "model": "gpt-4o-mini",
                    }
                },
                "default_interface": "openai",
            }

    async def add_message(self, message: str):
        """Add message to conversation history"""
        self.conversation_history.append({"role": "assistant", "content": message})

    async def get_user_input(self) -> str:
        """Get user input"""
        try:
            response = input("\nYour answer: ")
            # Decode if bytes received (handle encoding issues)
            if isinstance(response, bytes):
                response = response.decode("utf-8")
            return response
        except UnicodeDecodeError:
            # If encoding fails, return raw bytes
            response = input("\nYour answer: ")
            if isinstance(response, bytes):
                try:
                    return response.decode("utf-8")
                except:
                    return response.decode("latin-1", errors="replace")
            return response
        except Exception as e:
            print(f"\nError getting input: {e}")
            return ""


async def main():
    """Main entry point"""
    print("=" * 70)
    print("MoJoAssistant AI Setup Wizard")
    print("=" * 70)

    # Import after greeting
    from app.llm.llm_interface import LLMInterface

    print("\n🤖 Initializing AI assistant...")
    print("📊 Loading documentation knowledge base...")

    try:
        llm = LLMInterface()
        if "local" in str(llm).lower():
            llm.set_active_interface("qwen3-1.7b")
    except Exception as e:
        print(f"Warning: Could not initialize LLM: {e}")
        print("Setup wizard requires LLM to work properly")
        print("Please install LLM or provide correct configuration")
        return 1

    wizard = SetupWizard(llm)

    try:
        await wizard.start_setup()
        return 0
    except KeyboardInterrupt:
        print("\n\n✗ Setup interrupted by user")
        return 1
    except Exception as e:
        print(f"\n✗ Error during setup: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
