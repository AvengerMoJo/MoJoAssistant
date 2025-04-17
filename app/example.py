from app.memory.memory_manager import MemoryManager

# Example usage

def example_usage():
    """
    Example of how to use the MemoryManager
    """
    memory_manager = MemoryManager()
    
    # User interaction 1
    user_query = "Hello, can you help me with Python programming?"
    assistant_response = "Of course! I'd be happy to help with Python programming. What specific aspect do you need assistance with?"
    
    memory_manager.add_user_message(user_query)
    memory_manager.add_assistant_message(assistant_response)
    
    # User interaction 2
    user_query = "I'm trying to understand how to use decorators in Python"
    
    # Get context for this query
    context = memory_manager.get_context_for_query(user_query)
    print(f"Retrieved {len(context)} context items")
    
    # Generate response (in a real system, this would go to an LLM)
    assistant_response = "Decorators are a powerful feature in Python that allow you to modify the behavior of functions or methods..."
    
    # Update memory with the new interaction
    memory_manager.update_memory_from_response(user_query, assistant_response)
    
    # Add some knowledge to the system
    python_doc = """
    Decorators in Python are functions that modify the functionality of other functions.
    They follow the @decorator syntax and are a form of metaprogramming.
    Common examples include @classmethod, @staticmethod, and @property.
    """
    memory_manager.add_to_knowledge_base(python_doc, {"topic": "Python", "subtopic": "Decorators"})
    
    # End the conversation and store it
    memory_manager.end_conversation()
    
    # Save memory state
    memory_manager.save_memory_state("memory_state.json")
    
    print("Memory management demonstration completed")


if __name__ == "__main__":
    example_usage()
