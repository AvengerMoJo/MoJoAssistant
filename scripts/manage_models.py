#!/usr/bin/env python3
"""
Demo: Model Selector Agent

Shows how the model selector agent works to help users
download and configure LLM models.

Usage:
    python demo_model_selector.py                    # Interactive (with LLM if available)
    python demo_model_selector.py --auto-default     # Auto-install default model
    python demo_model_selector.py --model qwen3-1.7b-q5  # Install specific model
"""

import argparse
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.installer.agents.model_selector import ModelSelectorAgent


def main():
    parser = argparse.ArgumentParser(description="Model Selector Agent Demo")
    parser.add_argument(
        "--auto-default",
        action="store_true",
        help="Automatically install default model without prompting",
    )
    parser.add_argument(
        "--model", type=str, help="Install specific model by ID (e.g., qwen3-1.7b-q5)"
    )
    parser.add_argument(
        "--list", action="store_true", help="List available models from catalog"
    )
    parser.add_argument(
        "--search",
        type=str,
        metavar="QUERY",
        help="Search HuggingFace for a model and add it (e.g., 'gpt-oss-20b', 'llama 3.1')",
    )

    args = parser.parse_args()

    # Create agent (no LLM for now - will use rule-based fallback)
    agent = ModelSelectorAgent(llm=None, config_dir="config")

    # List models
    if args.list:
        print("\n" + "=" * 60)
        print("Available Models in Catalog")
        print("=" * 60 + "\n")

        agent.load_context()
        for model in agent.context["models"]:
            default_marker = " [DEFAULT]" if model.get("default") else ""
            print(f"📦 {model['name']}{default_marker}")
            print(f"   ID: {model['id']}")
            print(f"   Size: {model['size_mb']} MB")
            print(f"   RAM: {model['requirements']['ram_mb']} MB")
            print(f"   Speed: {model['performance']['speed']}")
            print(f"   Best for: {', '.join(model['recommended_for'])}")
            print()

        return

    # Search for model
    if args.search:
        result = agent.search_and_add_model(args.search, interactive=True)

        if result["success"]:
            print(f"\n✅ {result['message']}")
            if "model_path" in result.get("details", {}):
                print(f"   Path: {result['details']['model_path']}")
        else:
            print(f"\n❌ {result['message']}")
            sys.exit(1)

        return

    # Install specific model
    if args.model:
        print(f"\n🚀 Installing model: {args.model}\n")
        agent.load_context()
        result = agent.download_model_by_id(args.model)

        if result["success"]:
            print(f"\n✅ {result['message']}")
            print(f"   Model: {result['details']['model_name']}")
            print(f"   Path: {result['details']['model_path']}")
        else:
            print(f"\n❌ {result['message']}")
            sys.exit(1)

        return

    # Auto-install default
    if args.auto_default:
        print("\n🚀 Auto-installing default model...\n")
        result = agent.execute(auto_default=True)

        if result["success"]:
            print(f"\n✅ {result['message']}")
        else:
            print(f"\n❌ {result['message']}")
            sys.exit(1)

        return

    # Interactive mode
    print("\n" + "=" * 60)
    print("Model Selector Agent - Interactive Mode")
    print("=" * 60 + "\n")

    print("This demo will help you download and configure an LLM model.")
    print(
        "(Note: Full LLM-guided selection not implemented yet - using rule-based selection)\n"
    )

    # Execute agent
    result = agent.execute(auto_default=False)

    if result["success"]:
        print(f"\n✅ Success!")
        print(f"   {result['message']}")
        print(f"\n   Model path: {result['details']['model_path']}")
        print(f"   Config updated: config/llm_config.json")
    else:
        print(f"\n❌ Failed:")
        print(f"   {result['message']}")
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
