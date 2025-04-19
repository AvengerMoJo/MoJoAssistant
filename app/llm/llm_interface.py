"""
LLM Interface Module for MoJoAssistant

This module provides a flexible interface for interacting with various LLM backends.
It can be easily extended to support multiple LLM providers and models.
"""

from typing import Dict, List, Any, Optional, Union
from langchain.llms import GPT4All
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

class LLMInterface:
    """
    Flexible LLM interface that can be extended to support multiple models
    """
    def __init__(self, 
                 model_path: str = None,
                 model_type: str = "gptj", 
                 n_threads: int = 6,
                 verbose: bool = True):
        """
        Initialize the LLM interface
        
        Args:
            model_path: Path to the model file
            model_type: Model backend type (gptj, llama, etc.)
            n_threads: Number of threads to use
            verbose: Whether to enable verbose output
        """
        self.model_path = model_path
        self.model_type = model_type
        self.n_threads = n_threads
        self.verbose = verbose
        self.callbacks = [StreamingStdOutCallbackHandler()]
        self.llm = None
        
        if model_path:
            self.initialize_model()
    
    def initialize_model(self) -> bool:
        """
        Initialize the LLM with the specified parameters
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.llm = GPT4All(
                model=self.model_path, 
                backend=self.model_type, 
                n_threads=self.n_threads, 
                callbacks=self.callbacks, 
                verbose=self.verbose
            )
            print(f"LLM initialized with model: {self.model_path}")
            return True
        except Exception as e:
            print(f"Error initializing LLM: {e}")
            self.llm = None
            return False
    
    def set_model(self, model_path: str, model_type: str = "gptj") -> bool:
        """
        Change the active model
        
        Args:
            model_path: Path to the new model file
            model_type: Model backend type
            
        Returns:
            bool: True if model change was successful
        """
        self.model_path = model_path
        self.model_type = model_type
        return self.initialize_model()
    
    def format_context(self, context: List[Dict[str, Any]]) -> str:
        """
        Format context information for inclusion in prompts
        
        Args:
            context: List of context items
            
        Returns:
            str: Formatted context text
        """
        if not context:
            return "No previous context available."
        
        context_items = []
        for item in context:
            source = item.get('source', 'unknown')
            
            # Handle different types of content
            content = item.get('content', '')
            if not isinstance(content, str):
                # Try to convert to string or extract text
                try:
                    if hasattr(content, 'content'):
                        # Handle message objects
                        content = content.content
                    elif hasattr(content, 'text'):
                        content = content.text
                    else:
                        content = str(content)
                except:
                    content = "Complex content object"
            
            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
                
            context_items.append(f"- From {source}: {content}")
        
        return "\n".join(context_items)
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Generate a response using the LLM based on query and available context
        
        Args:
            query: User query
            context: List of context items
            
        Returns:
            str: Generated response
        """
        if self.llm is None:
            return self._fallback_response(query, context)
        
        # Format context
        context_text = self.format_context(context) if context else "No context available."
        
        # Create prompt template
        template = """
You are MoJoAssistant, a helpful AI with a tiered memory system.

CONTEXT INFORMATION:
{context}

USER QUERY:
{query}

Please respond to the user's query based on the context provided.
If the context doesn't contain relevant information, respond based on your general knowledge.
Keep your response concise, relevant, and helpful.

YOUR RESPONSE:
"""
        
        prompt = PromptTemplate(
            template=template,
            input_variables=["context", "query"]
        )
        
        # Create chain and run
        chain = LLMChain(llm=self.llm, prompt=prompt)
        try:
            result = chain.run(context=context_text, query=query)
            return result.strip()
        except Exception as e:
            print(f"Error generating response: {e}")
            return self._fallback_response(query, context)
    
    def _fallback_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Provide a fallback response when LLM generation fails
        
        Args:
            query: User query
            context: Context information
            
        Returns:
            str: Fallback response
        """
        context_info = f"(with {len(context)} context items)" if context else "(without context)"
        return f"I'm sorry, I couldn't generate a proper response to your query {context_info}. My language model appears to be unavailable. Please check the model configuration and try again."


# Factory function to create LLM interface with different models
def create_llm_interface(model_name: str = "default") -> LLMInterface:
    """
    Factory function to create an LLM interface with a specific model
    
    Args:
        model_name: Name of the model configuration to use
        
    Returns:
        LLMInterface: Configured LLM interface
    """
    # Model configurations
    model_configs = {
        "default": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin",
            "type": "gptj"
        },
        "llama": {
            "path": "/home/alex/.cache/gpt4all/ggml-model-gpt4all-llama-q4_0.bin",
            "type": "llama"
        },
        # Add more models as needed
    }
    
    # Get config or use default
    config = model_configs.get(model_name, model_configs["default"])
    
    # Create and return interface
    return LLMInterface(
        model_path=config["path"],
        model_type=config["type"]
    )
