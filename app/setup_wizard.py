#!/usr/bin/env python3
"""
MoJoAssistant AI Setup Wizard

Conversational setup wizard that uses Qwen3 1.7B to guide users through
configuration with access to all documentation.

This wizard:
- Works like interactive-cli chat interface
- Has continuous conversation with AI
- LLM naturally asks questions based on context
- No rigid question sequences
- Full documentation access for intelligent responses
"""

import asyncio
import sys
import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory


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
        """Load minimal documentation - full docs exceed context window"""
        print("\n📚 Preparing knowledge base...")

        # Don't load full docs - they're too big for 2K context
        # Just provide essential info in system prompt
        docs_context = """
Key Features:
- Memory & Dreaming: A→B→C→D pipeline for conversation consolidation
- Scheduler: Background task automation
- MCP Tools: 30+ tools for Claude Desktop integration
- OpenCode Manager: Remote development environments
- Local LLM: CPU-only inference with llama.cpp

Configuration Options:
- Local models: qwen-coder (code) or qwen3 (chat)
- MCP Mode: STDIO (Claude Desktop) or HTTP (web/mobile)
- API Keys: Optional for OpenAI, Anthropic features
"""

        print(f"✓ Knowledge base ready")
        return docs_context

    async def get_user_input(self) -> str:
        """Get user input with proper encoding handling"""
        try:
            response = input("\n> ")
            # Decode if bytes received (handle encoding issues)
            if isinstance(response, bytes):
                response = response.decode("utf-8")
            return response
        except UnicodeDecodeError:
            # If encoding fails, return raw bytes
            response = input("\n> ")
            if isinstance(response, bytes):
                try:
                    return response.decode("utf-8")
                except:
                    return response.decode("latin-1", errors="replace")
            return response
        except Exception as e:
            print(f"\nError getting input: {e}")
            return ""

    async def start_setup(self) -> bool:
        """Start the conversational setup flow"""
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          MoJoAssistant AI Setup Wizard                        ║
║                                                              ║
║  I'll help you configure MoJoAssistant through conversation  ║
║  Ask me questions, and I'll explain your options!            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

        # Load documentation
        docs = await self.load_documentation()

        # Add minimal system prompt to fit in 2K context
        context = f"""You are the MoJoAssistant Setup Wizard. Help users configure the system through friendly conversation.

Ask what they want to use MoJoAssistant for, then recommend:
- Qwen2.5-Coder (fast, coding) or Qwen3 (better chat)
- MCP STDIO mode (for Claude Desktop) or HTTP (for web)
- Optional: API keys, dreaming schedule

Keep responses SHORT (2-3 sentences). When done, say "ready to generate config"."""
        self.conversation_history.append({"role": "system", "content": context})

        # Use simple hardcoded greeting to save tokens
        print(f"\n🤖 Ready!")
        welcome = "Hi! I'll help you set up MoJoAssistant. What would you like to use it for - coding, chat, or both?"

        await self.add_message(f"Assistant: {welcome}")
        print(f"\n🤖 {welcome}")

        # Chat loop
        try:
            history = FileHistory(".mojo_setup_history")
            session = PromptSession(history=history)

            max_rounds = 20  # Limit to prevent infinite loops
            round_num = 0

            while round_num < max_rounds:
                round_num += 1
                print(f"\n{'─' * 60}")
                print(f"Round {round_num}/{max_rounds}")

                # Get user input
                user_input = await self.get_user_input()

                if not user_input.strip():
                    # Empty input, just ask again
                    continue

                # Add user message to history
                await self.add_message(f"User: {user_input}")

                # Get AI response - use sliding window to fit in 2K context
                # Keep only system prompt + last 4 messages + current query
                messages = []

                # Always include system prompt (first message)
                if self.conversation_history and self.conversation_history[0].get("role") == "system":
                    messages.append(self.conversation_history[0])

                # Keep last 4 conversation turns (8 messages = 4 user + 4 assistant)
                recent_history = self.conversation_history[-8:] if len(self.conversation_history) > 8 else self.conversation_history[1:]

                for msg in recent_history:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")

                    # Clean up prefixes from our internal format
                    if content.startswith("User: "):
                        role = "user"
                        content = content[6:]
                    elif content.startswith("Assistant: "):
                        role = "assistant"
                        content = content[11:]

                    # Skip if already system message
                    if role != "system":
                        messages.append({"role": role, "content": content})

                # Add current user query
                messages.append({"role": "user", "content": user_input})

                # Call LLM with sliding window
                ai_response = self.llm.generate_chat_response(messages)

                if not ai_response:
                    print(
                        "❌ AI couldn't generate a response. Let me try a different approach."
                    )
                    ai_response = "I apologize, but I'm having trouble responding. Let's continue our conversation."

                # Add AI response to history
                await self.add_message(f"Assistant: {ai_response}")

                # Print AI response
                print(f"\n🤖 {ai_response}")

                # Check if setup is complete
                if await self.check_setup_complete(user_input, ai_response):
                    print("\n" + "=" * 60)
                    print("✓ Setup complete!")
                    print("=" * 60)
                    await self.generate_config()
                    return True

        except KeyboardInterrupt:
            print("\n\n⚠️  Setup interrupted by user")
            print("You can continue by running the CLI normally")
            return False
        except Exception as e:
            print(f"\n\n❌ Error during setup: {e}")
            import traceback

            traceback.print_exc()
            return False

        return False

    async def check_setup_complete(self, user_input: str, ai_response: str) -> bool:
        """Check if setup is complete based on conversation"""
        # Simple heuristics:
        # - If user says they're done or asks to finish
        # - If AI indicates we have enough information

        user_lower = user_input.lower()
        response_lower = ai_response.lower()

        # Check for completion indicators
        completion_indicators = [
            "complete",
            "done",
            "finish",
            "all set",
            "good",
            "thanks",
            "ready",
        ]

        if any(indicator in user_lower for indicator in completion_indicators):
            print("\n👍 You're all set!")
            return True

        if any(indicator in response_lower for indicator in completion_indicators):
            print("\n✓ Setup complete!")
            return True

        return False

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
        print(f"\n✓ Setup wizard complete!")
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
            env += f"""# Local LLM Configuration
# Available models configured in config/llm_config.json:
#   - qwen-coder-small: Qwen2.5-Coder-1.7B (code-focused, fast)
#   - qwen3-1.7b: Qwen3-1.7B (general purpose, multilingual)
LLM_PROVIDER=local
LLM_MODEL=qwen-coder-small
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
        """Generate LLM configuration based on user conversation"""
        llm_choice = self.setup_data.get("llm_choice", "")

        # Default: include both models so user can switch between them
        config = {
            "comment": "MoJoAssistant LLM Configuration - Generated by AI Setup Wizard",
            "local_models": {
                "qwen-coder-small": {
                    "type": "llama",
                    "description": "Qwen2.5-Coder-1.7B - Fast, CPU-only, code-focused",
                    "path": str(Path.home() / ".cache/mojoassistant/models/qwen2.5-coder-1.5b-instruct-q5_k_m.gguf"),
                    "context_length": 32768,
                    "temperature": 0.1,
                    "recommended_for": ["dreaming", "chunking", "code_assistance"]
                },
                "qwen3-1.7b": {
                    "type": "llama",
                    "description": "Qwen3-1.7B - Latest, best for conversation, multilingual",
                    "path": str(Path.home() / ".cache/mojoassistant/models/qwen3-1.7b-q8_0.gguf"),
                    "context_length": 32768,
                    "temperature": 0.7,
                    "recommended_for": ["chat", "general_tasks", "multilingual", "setup_wizard"]
                }
            },
            "task_assignments": {
                "interactive_cli": "qwen-coder-small",  # Default to coder for CLI
                "dreaming_chunking": "qwen-coder-small",
                "dreaming_synthesis": "qwen-coder-small",
                "default": "qwen-coder-small"
            },
            "default_interface": "qwen-coder-small"
        }

        # If user specifically chose Qwen3, make it default
        if "qwen3" in llm_choice.lower():
            config["default_interface"] = "qwen3-1.7b"
            config["task_assignments"]["interactive_cli"] = "qwen3-1.7b"
            config["task_assignments"]["default"] = "qwen3-1.7b"

        # If user wants API models, add them too
        if "api" in llm_choice.lower() or "openai" in llm_choice.lower():
            if "api_models" not in config:
                config["api_models"] = {}
            config["api_models"]["openai"] = {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "description": "OpenAI GPT-4 mini - Fast, affordable API model"
            }

        return config

    async def add_message(self, message: str):
        """Add message to conversation history"""
        self.conversation_history.append({"role": "assistant", "content": message})


async def main():
    """Main entry point"""
    print("=" * 70)
    print("MoJoAssistant AI Setup Wizard")
    print("=" * 70)

    # Change to project root directory
    os.chdir(project_root)

    # Import after greeting
    from app.llm.local_llm_interface import LocalLLMInterface

    print("\n🤖 Initializing AI assistant...")
    print("📊 Detecting available models...")

    try:
        # Check which models are available
        cache_dir = Path.home() / ".cache/mojoassistant/models"
        qwen_coder_path = cache_dir / "qwen2.5-coder-1.5b-instruct-q5_k_m.gguf"
        qwen3_path = cache_dir / "qwen3-1.7b-q8_0.gguf"

        # Prefer Qwen3 for conversation (latest, best at chat)
        if qwen3_path.exists():
            model_path = qwen3_path
            model_name = "Qwen3-1.7B (Latest, best for conversation)"
        elif qwen_coder_path.exists():
            model_path = qwen_coder_path
            model_name = "Qwen2.5-Coder-1.5B (Code-focused)"
        else:
            print(f"  ⚠️  No models found in {cache_dir}")
            print("  Please ensure the installer downloaded models correctly")
            print("  Run: python -m app.dreaming.setup install")
            return 1

        print(f"  Using: {model_name}")
        print(f"  Starting local model server...")

        # Create simple local interface directly
        llm = LocalLLMInterface(
            model_path=str(model_path),
            model_type="llama",  # Use llama_cpp.server
            server_port=8080,  # Use different port to avoid conflicts
            context_length=32768,
            verbose=True
        )

        wizard = SetupWizard(llm)

        try:
            success = await wizard.start_setup()
            return 0 if success else 1
        except KeyboardInterrupt:
            print("\n\n✗ Setup interrupted by user")
            return 1
        except Exception as e:
            print(f"\n✗ Error during setup: {e}")
            import traceback

            traceback.print_exc()
            return 1

    except ImportError as e:
        print(f"Warning: Could not import setup components: {e}")
        print("Setup wizard requires LLM to work properly")
        print("Please install LLM or provide correct configuration")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
