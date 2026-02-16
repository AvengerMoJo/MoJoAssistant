"""
MoJoAssistant Interactive CLI

This script provides an interactive command-line interface to test the
MoJoAssistant memory system with free-form conversations.
"""

import os
import argparse
import json
import datetime
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

# Ensure the app module can be found
sys.path.append(".")

from app.services.memory_service import MemoryService
from app.llm.llm_interface import create_llm_interface
from app.config.config_loader import load_embedding_config, get_env_config_help
from app.config.logging_config import (
    setup_logging,
    get_logger,
    log_cli_command,
    set_console_log_level,
)
from app.config import validate_runtime_config, get_config_validation_help


def clear_screen() -> None:
    """Clear the terminal screen"""
    os.system("cls" if os.name == "nt" else "clear")


def print_header() -> None:
    """Print the application header"""
    # clear_screen()
    print("=" * 60)
    print("                  MoJoAssistant Interactive CLI")
    print("=" * 60)
    print("Type your messages to interact with the assistant.")
    print("Hint: For multiline input, press Esc then Enter.")
    print("Special commands:")
    print("  /stats      - Display memory statistics")
    print("  /embed      - Show current embedding model info")
    print("  /embed NAME - Switch to a different embedding model")
    print("  /save FILE  - Save memory state to FILE")
    print("  /load FILE  - Load memory state from FILE")
    print("  /add FILE   - Add a document to knowledge base")
    print("  /end        - End current conversation")
    print("  /clear      - Clear the screen")
    print("  /export FMT - Export conversation history (json/markdown)")
    print("  /search QUERY - Search memory for relevant content")
    print("  /config KEY VALUE - Set runtime configuration")
    print("  /help       - Show this help message again")
    print("  /env        - Show environment variable configuration help")
    print("  /log LEVEL  - Set console log level (DEBUG, INFO, WARNING, ERROR)")
    print("  /validate   - Validate current configuration")
    print("  /exit       - Exit the application")
    print("=" * 60)
    print()


def save_memory_state(memory_service, filename: str, logger) -> None:
    """Save the current memory state"""
    try:
        memory_service.save_memory_state(filename)
        print(f"✅ Memory state saved to {filename}")
        log_cli_command("/save", filename, True, logger)
    except Exception as e:
        error_msg = f"❌ Error saving memory state: {e}"
        print(error_msg)
        logger.error(f"Failed to save memory state to {filename}: {e}")
        log_cli_command("/save", filename, False, logger)


def load_memory_state(memory_service, filename: str, logger) -> None:
    """Load a memory state from file"""
    try:
        if not os.path.exists(filename):
            print(f"❌ File not found: {filename}")
            log_cli_command("/load", filename, False, logger)
            return

        success = memory_service.load_memory_state(filename)
        if success:
            print(f"✅ Memory state loaded from {filename}")
            log_cli_command("/load", filename, True, logger)
        else:
            print(f"❌ Failed to load memory state from {filename}")
            log_cli_command("/load", filename, False, logger)
    except Exception as e:
        error_msg = f"❌ Error loading memory state: {e}"
        print(error_msg)
        logger.error(f"Failed to load memory state from {filename}: {e}")
        log_cli_command("/load", filename, False, logger)


def add_document(memory_service, filename: str, logger) -> None:
    """Add a document to the knowledge base"""
    try:
        if not os.path.exists(filename):
            print(f"❌ File not found: {filename}")
            log_cli_command("/add", filename, False, logger)
            return

        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            print(f"❌ File is empty: {filename}")
            log_cli_command("/add", filename, False, logger)
            return

        memory_service.add_to_knowledge_base(
            content,
            {"source": filename, "added_at": datetime.datetime.now().isoformat()},
        )
        print(f"✅ Document added to knowledge base: {filename}")
        log_cli_command("/add", filename, True, logger)

    except UnicodeDecodeError:
        print(f"❌ Cannot read file (encoding issue): {filename}")
        log_cli_command("/add", filename, False, logger)
    except Exception as e:
        error_msg = f"❌ Error adding document: {e}"
        print(error_msg)
        logger.error(f"Failed to add document {filename}: {e}")
        log_cli_command("/add", filename, False, logger)


def display_memory_stats(memory_service, logger) -> None:
    """Display current memory statistics"""
    try:
        stats = memory_service.get_memory_stats()
        print("\n===== MEMORY STATISTICS =====")
        print(
            f"Working Memory: {stats['working_memory']['messages']} messages ({stats['working_memory']['tokens']}/{stats['working_memory']['max_tokens']} tokens)"
        )
        print(
            f"Active Memory: {stats['active_memory']['pages']}/{stats['active_memory']['max_pages']} pages"
        )
        print(f"Archival Memory: {stats['archival_memory']['items']} items")
        print(f"Knowledge Base: {stats['knowledge_base']['items']} items")

        embed_info = stats["embedding"]
        print(
            f"\nEmbedding Model: {embed_info['model_name']} (Backend: {embed_info['backend']})"
        )
        print(f"Embedding Dimension: {embed_info['embedding_dim']}")
        print(f"Embedding Cache Size: {embed_info['cache_size']} items")

        print("================================\n")
        log_cli_command("/stats", "", True, logger)
    except Exception as e:
        print(f"❌ Error retrieving memory statistics: {e}")
        logger.error(f"Failed to display memory stats: {e}")
        log_cli_command("/stats", "", False, logger)


def change_embedding_model(
    memory_service, model_name: str, embedding_config: dict, logger
) -> None:
    """Change the embedding model"""
    try:
        if model_name not in embedding_config["embedding_models"]:
            available_models = ", ".join(embedding_config["embedding_models"].keys())
            print(f"❌ Unknown embedding model: {model_name}")
            print(f"📋 Available models: {available_models}")
            log_cli_command("/embed", model_name, False, logger)
            return

        config = embedding_config["embedding_models"][model_name]
        success = memory_service.set_embedding_model(
            model_name=config.get("model_name", model_name),
            backend=config.get("backend"),
            device=config.get("device"),
        )

        if success:
            print(f"✅ Switched to embedding model: {model_name}")
            log_cli_command("/embed", model_name, True, logger)
        else:
            print(f"❌ Failed to switch to embedding model: {model_name}")
            log_cli_command("/embed", model_name, False, logger)

    except Exception as e:
        print(f"❌ Error changing embedding model: {e}")
        logger.error(f"Failed to change embedding model to {model_name}: {e}")
        log_cli_command("/embed", model_name, False, logger)


import datetime
from pathlib import Path


def save_export(content: str, format_type: str) -> None:
    """Save exported content to file"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_export_{timestamp}.{format_type}"

    with open(filename, "w") as f:
        f.write(content)

    print(f"✅ Export saved to {filename}")


def display_embedding_info(memory_service, logger) -> None:
    """Display current embedding model information"""
    try:
        embed_info = memory_service.get_embedding_info()
        print(f"\n===== EMBEDDING MODEL INFO =====")
        print(f"Model: {embed_info['model_name']}")
        print(f"Backend: {embed_info['backend']}")
        print(f"Dimensions: {embed_info['embedding_dim']}")
        print(f"Device: {embed_info.get('device', 'N/A')}")
        print(f"Cache Size: {embed_info['cache_size']} items")
        print("=" * 33)
        log_cli_command("/embed", "", True, logger)
    except Exception as e:
        print(f"❌ Error retrieving embedding info: {e}")
        logger.error(f"Failed to display embedding info: {e}")
        log_cli_command("/embed", "", False, logger)


def search_memory(memory_service, query: str, logger) -> None:
    """Search memory for relevant content"""
    try:
        if not query.strip():
            print("❌ Usage: /search QUERY")
            log_cli_command("/search", "", False, logger)
            return

        results = memory_service.search_memory(query)

        if not results:
            print(f"🔍 No results found for query: '{query}'")
            log_cli_command("/search", query, True, logger)
            return

        print(f"\n===== SEARCH RESULTS FOR: '{query}' =====")
        for i, result in enumerate(results, 1):
            print(f"\n[{i}] {result.get('title', 'Untitled')}")
            print(f"    Type: {result.get('type', 'unknown')}")
            print(f"    Relevance: {result.get('relevance_score', 'N/A')}")
            if "content" in result:
                content = result["content"]
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"    Content: {content}")
            if "metadata" in result and result["metadata"]:
                print(f"    Metadata: {result['metadata']}")

        print(f"\n📊 Found {len(results)} results")
        print("=" * 50)
        log_cli_command("/search", query, True, logger)

    except Exception as e:
        print(f"❌ Error searching memory: {e}")
        logger.error(f"Failed to search memory for query '{query}': {e}")
        log_cli_command("/search", query, False, logger)


def handle_runtime_config(memory_service, key: str, value: str, logger) -> None:
    """Handle runtime configuration changes"""
    try:
        if not key or not value:
            print("❌ Usage: /config KEY VALUE")
            print("Available keys: max_tokens, max_pages, search_limit")
            log_cli_command("/config", f"{key} {value}", False, logger)
            return

        # Map configuration keys to actual configuration parameters
        config_mapping = {
            "max_tokens": "working_memory_max_tokens",
            "max_pages": "active_memory_max_pages",
            "search_limit": "archival_memory_search_limit",
        }

        if key not in config_mapping:
            available_keys = ", ".join(config_mapping.keys())
            print(f"❌ Unknown config key: {key}")
            print(f"📋 Available keys: {available_keys}")
            log_cli_command("/config", f"{key} {value}", False, logger)
            return

        # Convert value to appropriate type
        config_value = None
        try:
            if key in ["max_tokens", "max_pages", "search_limit"]:
                config_value = int(value)
                if config_value <= 0:
                    print("❌ Value must be a positive integer")
                    log_cli_command("/config", f"{key} {value}", False, logger)
                    return
        except ValueError:
            print("❌ Value must be a number")
            log_cli_command("/config", f"{key} {value}", False, logger)
            return

        # Apply configuration change
        config_key = config_mapping[key]
        success = memory_service.update_runtime_config(config_key, config_value)

        if success:
            print(f"✅ Updated {key} to {config_value}")
            log_cli_command("/config", f"{key} {value}", True, logger)
        else:
            print(f"❌ Failed to update {key}")
            log_cli_command("/config", f"{key} {value}", False, logger)

    except Exception as e:
        print(f"❌ Error updating configuration: {e}")
        logger.error(f"Failed to update config {key} to {value}: {e}")
        log_cli_command("/config", f"{key} {value}", False, logger)


def handle_command(
    cmd: str, memory_service, embedding_config: dict, logger
) -> bool | None:
    """Handle special CLI commands"""
    parts = cmd.split()
    cmd_root = parts[0].lower()

    if cmd_root == "/stats":
        display_memory_stats(memory_service, logger)
        return True

    elif cmd_root == "/embed":
        if len(parts) > 1:
            change_embedding_model(memory_service, parts[1], embedding_config, logger)
        else:
            display_embedding_info(memory_service, logger)
        return True

    elif cmd_root == "/save":
        if len(parts) > 1:
            save_memory_state(memory_service, parts[1], logger)
        else:
            print("❌ Usage: /save FILENAME")
            log_cli_command("/save", "", False, logger)
        return True

    elif cmd_root == "/load":
        if len(parts) > 1:
            load_memory_state(memory_service, parts[1], logger)
        else:
            print("❌ Usage: /load FILENAME")
            log_cli_command("/load", "", False, logger)
        return True

    elif cmd_root == "/add":
        if len(parts) > 1:
            add_document(memory_service, parts[1], logger)
        else:
            print("❌ Usage: /add FILENAME")
            log_cli_command("/add", "", False, logger)
        return True

    elif cmd_root == "/dream":
        try:
            conversation_id = parts[1] if len(parts) > 1 else None
            task_ids = memory_service.trigger_dreaming(conversation_id)
            if task_ids:
                print(f"✅ Triggered {len(task_ids)} dreaming tasks")
                for tid in task_ids:
                    print(f"   - {tid}")
                log_cli_command("/dream", str(task_ids), True, logger)
            else:
                print("ℹ️  No new dreaming tasks created (maybe already scheduled?)")
                log_cli_command("/dream", "no_tasks", True, logger)
        except Exception as e:
            print(f"❌ Error triggering dreaming: {e}")
            logger.error(f"Failed to trigger dreaming: {e}")
            log_cli_command("/dream", "", False, logger)
        return True

    elif cmd_root == "/scheduler":
        try:
            status = memory_service.scheduler.get_status()
            print("\n===== SCHEDULER STATUS =====")
            print(f"Running: {status['running']}")
            print(f"Tick Count: {status['tick_count']}")

            if status["current_task"]:
                print(
                    f"Current Task: {status['current_task']['id']} ({status['current_task']['type']})"
                )
            else:
                print("Current Task: None")

            print(f"Queue: {status['queue']['total']} tasks")
            for status_key, count in status["queue"]["by_status"].items():
                print(f"  - {status_key}: {count}")

            print("==========================\n")
            log_cli_command("/scheduler", "", True, logger)
        except Exception as e:
            print(f"❌ Error getting scheduler status: {e}")
            logger.error(f"Failed to get scheduler status: {e}")
            log_cli_command("/scheduler", "", False, logger)
        return True

    elif cmd_root == "/end":
        try:
            memory_service.end_conversation()
            print("✅ Current conversation ended and stored in memory.")
            log_cli_command("/end", "", True, logger)
        except Exception as e:
            print(f"❌ Error ending conversation: {e}")
            logger.error(f"Failed to end conversation: {e}")
            log_cli_command("/end", "", False, logger)
        return True

    elif cmd_root == "/clear":
        clear_screen()
        log_cli_command("/clear", "", True, logger)
        return True

    elif cmd_root == "/help":
        print_header()
        log_cli_command("/help", "", True, logger)
        return True

    elif cmd_root == "/env":
        print(get_env_config_help())
        log_cli_command("/env", "", True, logger)
        return True

    elif cmd_root == "/log":
        if len(parts) > 1:
            try:
                level = parts[1].upper()
                if level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                    set_console_log_level(level)
                    print(f"✅ Console log level set to {level}")
                    log_cli_command("/log", level, True, logger)
                else:
                    print(
                        "❌ Invalid log level. Use: DEBUG, INFO, WARNING, ERROR, CRITICAL"
                    )
                    log_cli_command("/log", parts[1], False, logger)
            except Exception as e:
                print(f"❌ Error setting log level: {e}")
                log_cli_command("/log", parts[1], False, logger)
        else:
            print("❌ Usage: /log LEVEL (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
            log_cli_command("/log", "", False, logger)
        return True

    elif cmd_root == "/validate":
        try:
            is_valid = validate_runtime_config(embedding_config)
            if is_valid:
                print("✅ Configuration validation passed")
                log_cli_command("/validate", "", True, logger)
            else:
                print("❌ Configuration validation failed (check logs for details)")
                print("\n" + get_config_validation_help())
                log_cli_command("/validate", "", False, logger)
        except Exception as e:
            print(f"❌ Error during validation: {e}")
            logger.error(f"Configuration validation error: {e}")
            log_cli_command("/validate", "", False, logger)
        return True

    elif cmd_root == "/export":
        if len(parts) < 2:
            print("❌ Usage: /export [json|markdown]")
            log_cli_command("/export", "", False, logger)
            return True

        format_type = parts[1].lower()

        # Get working memory from memory service
        try:
            working_memory = memory_service.get_working_memory()

            if format_type == "json":
                content = working_memory.export_to_json()
                save_export(content, "json")
                log_cli_command("/export", "json", True, logger)
            elif format_type == "markdown":
                content = working_memory.export_to_markdown()
                save_export(content, "md")
                log_cli_command("/export", "markdown", True, logger)
            else:
                print("❌ Error: Format must be 'json' or 'markdown'")
                log_cli_command("/export", parts[1], False, logger)

        except Exception as e:
            print(f"❌ Error during export: {e}")
            logger.error(f"Failed to export conversation history: {e}")
            log_cli_command("/export", format_type, False, logger)

        return True

    elif cmd_root == "/search":
        if len(parts) > 1:
            query = " ".join(parts[1:])  # Join all parts after /search
            search_memory(memory_service, query, logger)
        else:
            print("❌ Usage: /search QUERY")
            log_cli_command("/search", "", False, logger)
        return True

    elif cmd_root == "/config":
        if len(parts) >= 3:
            key = parts[1]
            value = " ".join(parts[2:])  # Join remaining parts as value
            handle_runtime_config(memory_service, key, value, logger)
        else:
            print("❌ Usage: /config KEY VALUE")
            print("Available keys: max_tokens, max_pages, search_limit")
            log_cli_command("/config", "", False, logger)
        return True

    elif cmd_root == "/exit":
        return False

    return None  # Not a command


import asyncio
from datetime import datetime
from typing import Optional
from pathlib import Path


def run_setup_wizard():
    """Run smart installer with agents"""
    from app.installer.orchestrator import run_smart_installer
    return run_smart_installer(interactive=True, auto_defaults=False)


def main() -> int:
    """Main CLI application"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MoJoAssistant Interactive CLI")
    parser.add_argument(
        "--model", help="Name of the LLM model configuration to use", default="default"
    )
    parser.add_argument("--load", help="Load memory state from file on startup")
    parser.add_argument("--config", help="Path to LLM configuration file")
    parser.add_argument(
        "--embedding",
        help="Name of the embedding model configuration to use",
        default="default",
    )
    parser.add_argument(
        "--embedding-config",
        help="Path to embedding configuration file",
        default="config/embedding_config.json",
    )
    parser.add_argument(
        "--scheduler", help="Enable background scheduler (true/false)", default="true"
    )
    parser.add_argument(
        "--log-level",
        help="Logging level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument("--log-file", help="Log file path (optional)")
    parser.add_argument(
        "--setup", action="store_true", help="Run setup wizard with AI guidance"
    )

    args = parser.parse_args()

    # Run setup wizard if requested
    if args.setup:
        return run_setup_wizard()

    # Initialize logging
    setup_logging(log_level=args.log_level, log_file=args.log_file)
    logger = get_logger(__name__)
    logger.info("Starting MoJoAssistant Interactive CLI")

    try:
        # Load embedding configuration
        embedding_config = load_embedding_config(args.embedding_config)

        # Get embedding model configuration
        embed_model_name = args.embedding
        if embed_model_name not in embedding_config["embedding_models"]:
            print(
                f"⚠️  Warning: Embedding model '{embed_model_name}' not found in config, using default"
            )
            logger.warning(
                f"Embedding model '{embed_model_name}' not found, using default"
            )
            embed_model_name = "default"
            if embed_model_name not in embedding_config["embedding_models"]:
                embed_model_name = next(
                    iter(embedding_config["embedding_models"].keys())
                )

        embed_config = embedding_config["embedding_models"][embed_model_name]

        # Initialize memory service with the selected embedding model
        memory_service = MemoryService(
            data_dir=embedding_config.get("memory_settings", {}).get(
                "data_directory", ".memory"
            ),
            embedding_model=embed_config.get("model_name", embed_model_name),
            embedding_backend=embed_config.get("backend", "huggingface"),
            embedding_device=embed_config.get("device"),
            config=embedding_config.get("memory_settings", {}),
        )

        # Initialize LLM interface
        llm_interface = create_llm_interface(args.config, args.model)

        # Start scheduler if enabled
        if args.scheduler.lower() == "true":
            try:
                memory_service.start_scheduler()
                logger.info("Background scheduler started")
            except Exception as e:
                logger.error(f"Failed to start scheduler: {e}")
                print(f"⚠️  Warning: Failed to start scheduler: {e}")

        # Load initial memory state if specified
        if args.load:
            if os.path.exists(args.load):
                success = memory_service.load_memory_state(args.load)
                if success:
                    print(f"✅ Loaded memory state from {args.load}")
                    logger.info(f"Loaded initial memory state from {args.load}")
                else:
                    print(f"❌ Failed to load memory state from {args.load}")
                    logger.error(
                        f"Failed to load initial memory state from {args.load}"
                    )
            else:
                print(f"❌ Memory state file not found: {args.load}")
                logger.error(f"Memory state file not found: {args.load}")

        print_header()
        running = True

        # Create a history object
        history = FileHistory(".mojo_history")
        session: PromptSession = PromptSession(history=history)

        while running:
            try:
                # Get user input
                user_input = session.prompt("> ", multiline=True).strip()

                # Handle special commands
                if user_input.startswith("/"):
                    result = handle_command(
                        user_input, memory_service, embedding_config, logger
                    )
                    if result is False:  # Exit command
                        running = False
                        print("💾 Saving final memory state to 'final_state.json'...")
                        save_memory_state(memory_service, "final_state.json", logger)
                        print("👋 Goodbye!")
                        logger.info("CLI session ended by user")
                    continue

                # Skip empty input
                if not user_input:
                    continue

                # Add user message to memory
                memory_service.add_user_message(user_input)
                logger.debug(f"User input: {user_input[:100]}...")

                # Get context for this query
                context = memory_service.get_context_for_query(user_input)

                # If we found context, show a small indicator
                if context:
                    print(f"🔍 [Found {len(context)} relevant context items]")
                    logger.debug(f"Retrieved {len(context)} context items for query")

                # Generate response
                print("\n🤔 Assistant is thinking...")
                response = llm_interface.generate_response(user_input, context)

                # Clean up response (remove common prefixes)
                response = response.replace("Assistant:", "").replace("AI:", "").strip()

                # Display response
                print(f"\n🤖 Assistant: {response}\n")

                # Add assistant response to memory
                memory_service.add_assistant_message(response)

            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted by user. Saving state...")
                save_memory_state(memory_service, "interrupt_state.json", logger)
                logger.info("CLI session interrupted by user")
                break
            except EOFError:
                print("\n\n👋 Goodbye!")
                save_memory_state(memory_service, "final_state.json", logger)
                logger.info("CLI session ended (EOF)")
                break
            except Exception as e:
                print(f"\n❌ An error occurred: {e}")
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                save_memory_state(memory_service, "error_state.json", logger)

    except Exception as e:
        print(f"❌ Failed to initialize MoJoAssistant: {e}")
        logger.error(f"Failed to initialize application: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
