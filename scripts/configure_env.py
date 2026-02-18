#!/usr/bin/env python3
"""
Demo: Environment Configurator Agent

Shows how the env configurator helps users set up their .env file.

Usage:
    python demo_env_configurator.py              # Interactive setup
    python demo_env_configurator.py --local-only # Quick local-only setup
    python demo_env_configurator.py --cloud      # Cloud AI setup
    python demo_env_configurator.py --github     # GitHub integration
"""

import argparse
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.installer.agents.env_configurator import EnvConfiguratorAgent


def main():
    parser = argparse.ArgumentParser(description="Environment Configurator Demo")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Quick setup for local-only usage",
    )
    parser.add_argument(
        "--cloud", action="store_true", help="Setup with cloud AI providers"
    )
    parser.add_argument(
        "--github", action="store_true", help="Setup with GitHub integration"
    )
    parser.add_argument(
        "--show-current",
        action="store_true",
        help="Show current .env settings",
    )

    args = parser.parse_args()

    # Create agent
    agent = EnvConfiguratorAgent(llm=None, config_dir="config")

    # Show current settings
    if args.show_current:
        env_path = Path(".env")
        if not env_path.exists():
            print("❌ No .env file found")
            return

        print("\n" + "=" * 60)
        print("Current .env Settings")
        print("=" * 60 + "\n")

        with open(env_path, "r") as f:
            for line in f:
                if line.strip() and not line.strip().startswith("#"):
                    # Mask API keys
                    if "KEY" in line or "TOKEN" in line or "SECRET" in line:
                        key, value = line.strip().split("=", 1)
                        if value and value != "":
                            masked = value[:8] + "..." if len(value) > 8 else "***"
                            print(f"{key}={masked}")
                        else:
                            print(line.strip())
                    else:
                        print(line.strip())

        return

    # Quick setup modes
    if args.local_only:
        print("\n🚀 Quick setup: Local-only mode\n")
        result = agent.execute(interactive=False, use_case="local_only")
    elif args.cloud:
        print("\n🚀 Quick setup: Cloud AI mode\n")
        result = agent.execute(interactive=True, use_case=None)
    elif args.github:
        print("\n🚀 Quick setup: GitHub integration\n")
        result = agent.execute(interactive=True, use_case=None)
    else:
        # Interactive mode
        print("\n" + "=" * 60)
        print("Environment Configurator - Interactive Mode")
        print("=" * 60 + "\n")
        result = agent.execute(interactive=True)

    # Show result
    if result["success"]:
        print(f"\n✅ {result['message']}")
        if "use_case" in result.get("details", {}):
            print(f"   Use case: {result['details']['use_case']}")
    else:
        print(f"\n❌ {result['message']}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
