#!/usr/bin/env python
"""
Launch the MoJoAssistant Discord community bot.

Setup:
  1. Create a bot at https://discord.com/developers/applications
  2. Enable "Message Content Intent" in the Bot settings
  3. Copy the bot token to .env: DISCORD_BOT_TOKEN=<token>
  4. Invite the bot to your server (needs Send Messages + Read Message History)
  5. Run: venv/bin/python scripts/run_discord_bot.py

The bot only responds when @mentioned (set DISCORD_MENTION_ONLY=false to change).
"""
import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.community.discord_gateway import DiscordCommunityConfig, run_bot

if __name__ == "__main__":
    try:
        config = DiscordCommunityConfig.from_env()
    except ValueError as e:
        print(f"Error: {e}")
        print("Set DISCORD_BOT_TOKEN in your .env file and try again.")
        sys.exit(1)

    print(f"Starting community bot (role={config.role_id}, mention_only={config.mention_only})")
    run_bot(config)
