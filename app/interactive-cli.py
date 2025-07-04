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
sys.path.append('.')  

from app.services.memory_service import MemoryService
from app.llm.llm_interface import create_llm_interface

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
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
    print("  /help       - Show this help message again")
    print("  /exit       - Exit the application")
    print("=" * 60)
    print()

def load_embedding_config(config_file="config/embedding_config.json"):
    """Load embedding model configuration"""
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                return json.load(f)
        else:
            # Create default config if it doesn't exist
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            default_config = {
                "embedding_models": {
                    "default": {
                        "backend": "huggingface",
                        "model_name": "nomic-ai/nomic-embed-text-v2-moe"
                    },
                    "fallback": {
                        "backend": "random",
                        "embedding_dim": 768
                    }
                }
            }
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config
    except Exception as e:
        print(f"Error loading embedding config: {e}")
        return {"embedding_models": {"fallback": {"backend": "random"}}}

def save_memory_state(memory_service, filename):
    """Save the current memory state"""
    try:
        memory_service.save_memory_state(filename)
        print(f"Memory state saved to {filename}")
    except Exception as e:
        print(f"Error saving memory state: {e}")

def load_memory_state(memory_service, filename):
    """Load a memory state from file"""
    try:
        if os.path.exists(filename):
            success = memory_service.load_memory_state(filename)
            if success:
                print(f"Memory state loaded from {filename}")
            else:
                print(f"Failed to load memory state from {filename}")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error loading memory state: {e}")

def add_document(memory_service, filename):
    """Add a document to the knowledge base"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                content = f.read()
                memory_service.add_to_knowledge_base(
                    content, 
                    {"source": filename, "added_at": datetime.datetime.now().isoformat()}
                )
                print(f"Added document {filename} to knowledge base")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error adding document: {e}")

def display_memory_stats(memory_service):
    """Display current memory statistics"""
    stats = memory_service.get_memory_stats()
    print("\n===== MEMORY STATISTICS =====")
    print(f"Working Memory: {stats['working_memory']['messages']} messages ({stats['working_memory']['tokens']}/{stats['working_memory']['max_tokens']} tokens)")
    print(f"Active Memory: {stats['active_memory']['pages']}/{stats['active_memory']['max_pages']} pages")
    print(f"Archival Memory: {stats['archival_memory']['items']} items")
    print(f"Knowledge Base: {stats['knowledge_base']['items']} items")
    
    embed_info = stats['embedding']
    print(f"\nEmbedding Model: {embed_info['model_name']} (Backend: {embed_info['backend']})")
    print(f"Embedding Dimension: {embed_info['embedding_dim']}")
    print(f"Embedding Cache Size: {embed_info['cache_size']} items")
    
    print("================================\n")

def display_embedding_info(memory_service):
    """Display information about the current embedding model"""
    embed_info = memory_service.get_embedding_info()
    print("\n===== EMBEDDING MODEL INFORMATION =====")
    print(f"Model Name: {embed_info['model_name']}")
    print(f"Backend: {embed_info['backend']}")
    print(f"Embedding Dimension: {embed_info['embedding_dim']}")
    print(f"Cache Size: {embed_info['cache_size']} items")
    print(f"Device: {embed_info['device'] or 'not specified'}")
    print("========================================\n")

def change_embedding_model(memory_service, model_name, embedding_config):
    """Change the embedding model"""
    if model_name not in embedding_config["embedding_models"]:
        print(f"Unknown embedding model: {model_name}")
        print(f"Available models: {', '.join(embedding_config['embedding_models'].keys())}")
        return
    
    config = embedding_config["embedding_models"][model_name]
    success = memory_service.set_embedding_model(
        model_name=config.get("model_name", model_name),
        backend=config.get("backend"),
        device=config.get("device")
    )
    
    if success:
        print(f"Switched to embedding model: {model_name}")
    else:
        print(f"Failed to switch to embedding model: {model_name}")

def handle_command(cmd, memory_service, embedding_config):
    """Handle special CLI commands"""
    parts = cmd.split()
    cmd_root = parts[0].lower()
    
    if cmd_root == "/stats":
        display_memory_stats(memory_service)
        return True
    
    elif cmd_root == "/embed":
        if len(parts) > 1:
            change_embedding_model(memory_service, parts[1], embedding_config)
        else:
            display_embedding_info(memory_service)
        return True
    
    elif cmd_root == "/save":
        if len(parts) > 1:
            save_memory_state(memory_service, parts[1])
        else:
            print("Usage: /save FILENAME")
        return True
    
    elif cmd_root == "/load":
        if len(parts) > 1:
            load_memory_state(memory_service, parts[1])
        else:
            print("Usage: /load FILENAME")
        return True
    
    elif cmd_root == "/add":
        if len(parts) > 1:
            add_document(memory_service, parts[1])
        else:
            print("Usage: /add FILENAME")
        return True
    
    elif cmd_root == "/end":
        memory_service.end_conversation()
        print("Current conversation ended and stored in memory.")
        return True
    
    elif cmd_root == "/clear":
        clear_screen()
        return True
    
    elif cmd_root == "/help":
        print_header()
        return True

    elif cmd_root == "/exit":
        return False
    
    return None  # Not a command

def main():
    """Main CLI application"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MoJoAssistant Interactive CLI")
    parser.add_argument("--model", help="Name of the LLM model configuration to use", default="default")
    parser.add_argument("--load", help="Load memory state from file on startup")
    parser.add_argument("--config", help="Path to LLM configuration file")
    parser.add_argument("--embedding", help="Name of the embedding model configuration to use", default="default")
    parser.add_argument("--embedding-config", help="Path to embedding configuration file", 
                       default="config/embedding_config.json")

    args = parser.parse_args()
    
    # Load embedding configuration
    embedding_config = load_embedding_config(args.embedding_config)
    
    # Get embedding model configuration
    embed_model_name = args.embedding
    if embed_model_name not in embedding_config["embedding_models"]:
        print(f"Warning: Embedding model '{embed_model_name}' not found in config, using default")
        embed_model_name = "default"
        if embed_model_name not in embedding_config["embedding_models"]:
            embed_model_name = next(iter(embedding_config["embedding_models"].keys()))
    
    embed_config = embedding_config["embedding_models"][embed_model_name]
    
    # Initialize memory service with the selected embedding model
    memory_service = MemoryService(
        data_dir=embedding_config.get("memory_settings", {}).get("data_directory", ".memory"),
        embedding_model=embed_config.get("model_name", embed_model_name),
        embedding_backend=embed_config.get("backend", "huggingface"),
        embedding_device=embed_config.get("device"),
        config=embedding_config.get("memory_settings", {})
    )
    
    # Initialize LLM interface
    llm_interface = create_llm_interface(config_file=args.config, model_name=args.model)

    # Load memory state if specified
    if args.load:
        load_memory_state(memory_service, args.load)
    
    print_header()
    running = True
    
    # Create a history object
    history = FileHistory('.mojo_history')
    session = PromptSession(history=history)

    try:
        while running:
            # Get user input
            user_input = session.prompt("> ", multiline=True).strip()
            
            # Handle special commands
            if user_input.startswith("/"):
                result = handle_command(user_input, memory_service, embedding_config)
                if result is False:  # Exit command
                    running = False
                    print("Saving final memory state to 'final_state.json'...")
                    save_memory_state(memory_service, "final_state.json")
                    print("Goodbye!")
                continue
            
            # Skip empty input
            if not user_input:
                continue
            
            # Add user message to memory
            memory_service.add_user_message(user_input)
            
            # Get context for this query
            context = memory_service.get_context_for_query(user_input)
            
            # If we found context, show a small indicator
            if context:
                print(f"[Found {len(context)} relevant context items]")
            
            # Generate response
            print("\nAssistant is thinking...")
            response = llm_interface.generate_response(user_input, context)
            
            # Sometimes the LLM adds "Assistant:" or similar prefixes - remove them
            response = response.replace("Assistant:", "").replace("AI:", "").strip()
            
            print(f"\nAssistant: {response}\n")
            
            # Add assistant message to memory
            memory_service.add_assistant_message(response)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user. Saving memory state...")
        save_memory_state(memory_service, "interrupt_state.json")
        print("Goodbye!")
    
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        print("Attempting to save memory state before exit...")
        try:
            save_memory_state(memory_service, "error_state.json")
        except:
            print("Could not save memory state.")
        print("Exiting...")

if __name__ == "__main__":
    main()
