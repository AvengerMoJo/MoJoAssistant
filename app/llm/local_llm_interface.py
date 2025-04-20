"""
Enhanced LLM Interface Module for MoJoAssistant

This module provides a flexible interface for interacting with various LLM backends,
supporting both local models (via GPT4All) and remote API-based models.
"""

from typing import Dict, List, Any, Optional, Union
import os
import json
import requests
from abc import ABC, abstractmethod

# For local models
from langchain.llms import GPT4All
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

from app.llm.llm_base import BaseLLMInterface

class LocalLLMInterface(BaseLLMInterface):
    """
    Interface for local LLM models using GPT4All
    """
    def __init__(self, 
                 model_path: str = None,
                 model_type: str = "gptj", 
                 n_threads: int = 6,
                 verbose: bool = True):
        """
        Initialize the local LLM interface
        
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
            print(f"Local LLM initialized with model: {self.model_path}")
            return True
        except Exception as e:
            print(f"Error initializing local LLM: {e}")
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
    
    def generate_response(self, query: str, context: List[Dict[str, Any]] = None) -> str:
        """
        Generate a response using the local LLM based on query and available context
        
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

