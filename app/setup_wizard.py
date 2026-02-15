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

