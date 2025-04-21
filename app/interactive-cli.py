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
from app.memory.memory_manager import MemoryManager

# Import the new LLM interface
sys.path.append('.')  # Ensure the app module can be found
from app.llm.llm_interface import create_llm_interface

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    """Print the application header"""
    clear_screen()
    print("=" * 60)
    print("                  MoJoAssistant Interactive CLI")
    print("=" * 60)
    print("Type your messages to interact with the assistant.")
    print("Special commands:")
    print("  /stats      - Display memory statistics")
    print("  /save FILE  - Save memory state to FILE")
    print("  /load FILE  - Load memory state from FILE")
    print("  /add FILE   - Add a document to knowledge base")
    print("  /end        - End current conversation")
    print("  /clear      - Clear the screen")
    print("  /exit       - Exit the application")
    print("=" * 60)
    print()

def save_memory_state(memory_manager, filename):
    """Save the current memory state"""
    try:
        memory_manager.save_memory_state(filename)
        print(f"Memory state saved to {filename}")
    except Exception as e:
        print(f"Error saving memory state: {e}")

def load_memory_state(memory_manager, filename):
    """Load a memory state from file"""
    try:
        if os.path.exists(filename):
            success = memory_manager.load_memory_state(filename)
            if success:
                print(f"Memory state loaded from {filename}")
            else:
                print(f"Failed to load memory state from {filename}")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error loading memory state: {e}")

def add_document(memory_manager, filename):
    """Add a document to the knowledge base"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                content = f.read()
                memory_manager.add_to_knowledge_base(
                    content, 
                    {"source": filename, "added_at": datetime.datetime.now().isoformat()}
                )
                print(f"Added document {filename} to knowledge base")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error adding document: {e}")

def display_memory_stats(memory_manager):
    """Display current memory statistics"""
    print("\n===== MEMORY STATISTICS =====")
    print(f"Working Memory: {len(memory_manager.working_memory.get_messages())} messages")
    print(f"Active Memory: {len(memory_manager.active_memory.pages)} pages")
    
    # Add more detailed stats as needed
    print("\nWorking Memory Messages:")
    for i, msg in enumerate(memory_manager.working_memory.get_messages()):
        speaker = "User" if msg.type.lower() in ["user", "human"] else "Assistant"
        print(f"  {i+1}. {speaker}: {msg.content[:50]}...")
    
    print("\nActive Memory Pages:")
    for i, page in enumerate(memory_manager.active_memory.pages):
        print(f"  {i+1}. {page.page_type} (ID: {page.id[:8]}..., Accessed: {page.access_count} times)")
    
    print("================================\n")

def handle_command(cmd, memory_manager):
    """Handle special CLI commands"""
    parts = cmd.split()
    cmd_root = parts[0].lower()
    
    if cmd_root == "/stats":
        display_memory_stats(memory_manager)
        return True
    
    elif cmd_root == "/save":
        if len(parts) > 1:
            save_memory_state(memory_manager, parts[1])
        else:
            print("Usage: /save FILENAME")
        return True
    
    elif cmd_root == "/load":
        if len(parts) > 1:
            load_memory_state(memory_manager, parts[1])
        else:
            print("Usage: /load FILENAME")
        return True
    
    elif cmd_root == "/add":
        if len(parts) > 1:
            add_document(memory_manager, parts[1])
        else:
            print("Usage: /add FILENAME")
        return True
    
    elif cmd_root == "/end":
        memory_manager.end_conversation()
        print("Current conversation ended and stored in memory.")
        return True
    
    elif cmd_root == "/clear":
        clear_screen()
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

    args = parser.parse_args()
    
    # Initialize memory manager and LLM
    memory_manager = MemoryManager()
    llm_interface = create_llm_interface(config_file=args.config, model_name=args.model)

    # Load memory state if specified
    if args.load:
        load_memory_state(memory_manager, args.load)
    
    print_header()
    running = True
    
    try:
        while running:
            # Get user input
            user_input = input("> ").strip()
            
            # Handle special commands
            if user_input.startswith("/"):
                result = handle_command(user_input, memory_manager)
                if result is False:  # Exit command
                    running = False
                    print("Saving final memory state to 'final_state.json'...")
                    save_memory_state(memory_manager, "final_state.json")
                    print("Goodbye!")
                continue
            
            # Skip empty input
            if not user_input:
                continue
            
            # Add user message to memory
            memory_manager.add_user_message(user_input)
            
            # Get context for this query
            context = memory_manager.get_context_for_query(user_input)
            
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
            memory_manager.add_assistant_message(response)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user. Saving memory state...")
        save_memory_state(memory_manager, "interrupt_state.json")
        print("Goodbye!")
    
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        print("Attempting to save memory state before exit...")
        try:
            save_memory_state(memory_manager, "error_state.json")
        except:
            print("Could not save memory state.")
        print("Exiting...")

if __name__ == "__main__":
    main()
