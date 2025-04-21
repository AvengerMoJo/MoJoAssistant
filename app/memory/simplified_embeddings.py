"""
Enhanced Embeddings Interface for MoJoAssistant

This module provides a generic embeddings interface that can work with different backends
including direct integration with SentenceTransformers for high-quality embeddings.
"""

from typing import List, Dict, Any, Optional, Union
import os
import json
import hashlib
import requests
import math
import random
import importlib
import numpy as np
from sentence_transformers import SentenceTransformer

class SimpleEmbedding:
    """
    Enhanced embedding implementation that supports multiple backends:
    1. HuggingFace models via sentence-transformers (local)
    2. Local server (e.g., FastEmbed, sentence-transformers server)
    3. Remote API (OpenAI, Cohere, etc.)
    4. Fallback random embeddings when no backend is available
    
    Includes efficient caching for performance.
    """
    
    def __init__(self, 
                 backend: str = "huggingface", 
                 model_name: str = "nomic-ai/nomic-embed-text-v2-moe",
                 api_key: str = None,
                 server_url: str = "http://localhost:8080/embed",
                 embedding_dim: int = 768,
                 cache_dir: str = ".embedding_cache",
                 device: str = None):
        """
        Initialize the embedding interface
        
        Args:
            backend: Backend type ('huggingface', 'local', 'api', 'random')
            model_name: Name of the embedding model
            api_key: API key for remote services
            server_url: URL for local embedding server
            embedding_dim: Dimension of embedding vectors
            cache_dir: Directory to store embedding cache
            device: Device to run model on ('cpu', 'cuda', etc.)
        """
        self.backend = backend
        self.model_name = model_name
        self.api_key = api_key
        self.server_url = server_url
        self.embedding_dim = embedding_dim
        self.device = device
        self.model = None
        
        # Set up caching
        self.cache_dir = cache_dir
        self.cache = {}
        self._init_cache()
        
        # Initialize the model if using HuggingFace
        if self.backend == "huggingface":
            self._initialize_huggingface_model()
    
    def _initialize_huggingface_model(self) -> None:
        """Initialize the HuggingFace model using sentence-transformers"""
        try:
            print(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True)
            
            # Set device if specified
            if self.device:
                self.model.to(self.device)
                
            # Update embedding dimension based on the model
            self.embedding_dim = self.model.get_sentence_embedding_dimension()
            print(f"Model loaded with embedding dimension: {self.embedding_dim}")
            
        except Exception as e:
            print(f"Error initializing HuggingFace model: {e}")
            # print("Falling back to random embeddings")
            # self.backend = "random"
    
    def _init_cache(self) -> None:
        """Initialize the embedding cache"""
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_file = os.path.join(self.cache_dir, f"{self.model_name.replace('/', '_')}_cache.json")
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    self.cache = json.load(f)
                print(f"Loaded {len(self.cache)} cached embeddings")
            except Exception as e:
                print(f"Error loading embedding cache: {e}")
                self.cache = {}
    
    def _save_cache(self) -> None:
        """Save the embedding cache to disk"""
        cache_file = os.path.join(self.cache_dir, f"{self.model_name.replace('/', '_')}_cache.json")
        
        try:
            # Only save if we have a reasonable number of items
            if len(self.cache) > 0 and len(self.cache) < 10000:
                with open(cache_file, 'w') as f:
                    json.dump(self.cache, f)
        except Exception as e:
            print(f"Error saving embedding cache: {e}")
    
    def _get_cache_key(self, text: str) -> str:
        """Generate a cache key for a text string"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def get_text_embedding(self, text: str) -> List[float]:
        """
        Get embedding vector for a text string
        
        Args:
            text: Input text to embed
            
        Returns:
            List[float]: Embedding vector
        """
        # Check cache first
        cache_key = self._get_cache_key(text)
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        embedding = []
        
        # Generate embedding based on backend
        if self.backend == "huggingface":
            embedding = self._get_huggingface_embedding(text)
        elif self.backend == "local":
            embedding = self._get_local_embedding(text)
        elif self.backend == "api":
            embedding = self._get_api_embedding(text)
        else:
            # Fallback to random embedding
            embedding = self._get_random_embedding(text)
        
        # Cache the result
        self.cache[cache_key] = embedding
        
        # Periodically save cache
        if len(self.cache) % 100 == 0:
            self._save_cache()
            
        return embedding
    
    def _get_huggingface_embedding(self, text: str) -> List[float]:
        """
        Get embedding from HuggingFace model
        
        Args:
            text: Input text
            
        Returns:
            List[float]: Embedding vector
        """
        try:
            if self.model is None:
                return self._get_random_embedding(text)
                
            # Generate embedding from model
            embedding = self.model.encode(text)
            
            # Convert to list of floats
            if isinstance(embedding, np.ndarray):
                return embedding.tolist()
            return list(embedding)
            
        except Exception as e:
            print(f"Error getting HuggingFace embedding: {e}")
            return self._get_random_embedding(text)
    
    def get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get embedding vectors for a batch of texts
        
        Args:
            texts: List of input texts to embed
            
        Returns:
            List[List[float]]: List of embedding vectors
        """
        # Filter out texts that are already cached
        uncached_texts = []
        uncached_indices = []
        
        results = [None] * len(texts)
        
        # Check cache first for each text
        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            if cache_key in self.cache:
                results[i] = self.cache[cache_key]
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
        
        # If all texts were cached, return the results
        if not uncached_texts:
            return results
        
        # Generate embeddings for uncached texts
        if self.backend == "huggingface":
            embeddings = self._get_huggingface_batch_embeddings(uncached_texts)
        elif self.backend == "local":
            embeddings = self._get_local_batch_embeddings(uncached_texts)
        elif self.backend == "api":
            embeddings = self._get_api_batch_embeddings(uncached_texts)
        else:
            embeddings = [self._get_random_embedding(text) for text in uncached_texts]
        
        # Update cache and results
        for i, embedding in zip(uncached_indices, embeddings):
            cache_key = self._get_cache_key(texts[i])
            self.cache[cache_key] = embedding
            results[i] = embedding
        
        # Save cache periodically
        if sum(1 for text in uncached_texts) > 50:
            self._save_cache()
        
        return results
    
    def _get_huggingface_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get batch embeddings from HuggingFace model
        
        Args:
            texts: List of input texts
            
        Returns:
            List[List[float]]: List of embedding vectors
        """
        try:
            if self.model is None:
                return [self._get_random_embedding(text) for text in texts]
                
            # Generate embeddings from model
            embeddings = self.model.encode(texts)
            
            # Convert to list of lists
            if isinstance(embeddings, np.ndarray):
                return embeddings.tolist()
            return [list(emb) for emb in embeddings]
            
        except Exception as e:
            print(f"Error getting HuggingFace batch embeddings: {e}")
            return [self._get_random_embedding(text) for text in texts]
    
    def _get_local_embedding(self, text: str) -> List[float]:
        """
        Get embedding from local server
        
        Args:
            text: Input text
            
        Returns:
            List[float]: Embedding vector
        """
        try:
            # Try to use local embedding server
            response = requests.post(
                self.server_url,
                json={"text": text},
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                if "embedding" in result:
                    return result["embedding"]
                elif "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
            
            # If server fails, fall back to random embedding
            print("Local embedding server failed, using fallback")
            return self._get_random_embedding(text)
            
        except Exception as e:
            print(f"Error getting local embedding: {e}")
            return self._get_random_embedding(text)
    
    def _get_local_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get batch embeddings from local server
        
        Args:
            texts: List of input texts
            
        Returns:
            List[List[float]]: List of embedding vectors
        """
        try:
            # Try to use local embedding server for batch
            response = requests.post(
                self.server_url,
                json={"texts": texts},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if "embeddings" in result:
                    return result["embeddings"]
                elif "data" in result:
                    return [item["embedding"] for item in result["data"]]
            
            # If batch request fails, try individual requests
            return [self._get_local_embedding(text) for text in texts]
            
        except Exception as e:
            print(f"Error getting batch local embeddings: {e}")
            return [self._get_random_embedding(text) for text in texts]
    
    def _get_api_embedding(self, text: str) -> List[float]:
        """
        Get embedding from remote API
        
        Args:
            text: Input text
            
        Returns:
            List[float]: Embedding vector
        """
        try:
            headers = {
                "Content-Type": "application/json"
            }
            
            # Configure API request based on provider
            if "openai" in self.model_name.lower():
                # OpenAI embedding API
                headers["Authorization"] = f"Bearer {self.api_key}"
                response = requests.post(
                    "https://api.openai.com/v1/embeddings",
                    headers=headers,
                    json={
                        "input": text,
                        "model": self.model_name
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result["data"][0]["embedding"]
                    
            elif "cohere" in self.model_name.lower():
                # Cohere embedding API
                headers["Authorization"] = f"Bearer {self.api_key}"
                response = requests.post(
                    "https://api.cohere.ai/v1/embed",
                    headers=headers,
                    json={
                        "texts": [text],
                        "model": self.model_name
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result["embeddings"][0]
            
            else:
                # Generic API format
                payload = {
                    "text": text,
                    "model": self.model_name
                }
                
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                response = requests.post(
                    self.server_url,
                    headers=headers,
                    json=payload,
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if "embedding" in result:
                        return result["embedding"]
                    elif "data" in result and len(result["data"]) > 0:
                        return result["data"][0]["embedding"]
            
            # Fallback to random if API fails
            print(f"API embedding failed with status {response.status_code}, using fallback")
            return self._get_random_embedding(text)
            
        except Exception as e:
            print(f"Error getting API embedding: {e}")
            return self._get_random_embedding(text)
    
    def _get_api_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get batch embeddings from remote API
        
        Args:
            texts: List of input texts
            
        Returns:
            List[List[float]]: List of embedding vectors
        """
        try:
            headers = {"Content-Type": "application/json"}
            
            # Configure API request based on provider
            if "openai" in self.model_name.lower():
                # OpenAI embedding API
                headers["Authorization"] = f"Bearer {self.api_key}"
                response = requests.post(
                    "https://api.openai.com/v1/embeddings",
                    headers=headers,
                    json={
                        "input": texts,
                        "model": self.model_name
                    },
                    timeout=20
                )
                
                if response.status_code == 200:
                    result = response.json()
                    # Sort by index since OpenAI may return out of order
                    embeddings = sorted(result["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in embeddings]
                    
            elif "cohere" in self.model_name.lower():
                # Cohere embedding API
                headers["Authorization"] = f"Bearer {self.api_key}"
                response = requests.post(
                    "https://api.cohere.ai/v1/embed",
                    headers=headers,
                    json={
                        "texts": texts,
                        "model": self.model_name
                    },
                    timeout=20
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result["embeddings"]
            
            else:
                # Generic API format
                payload = {
                    "texts": texts,
                    "model": self.model_name
                }
                
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                response = requests.post(
                    self.server_url,
                    headers=headers,
                    json=payload,
                    timeout=20
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if "embeddings" in result:
                        return result["embeddings"]
                    elif "data" in result:
                        return [item["embedding"] for item in result["data"]]
            
            # If batch fails, try individual requests
            return [self._get_api_embedding(text) for text in texts]
            
        except Exception as e:
            print(f"Error getting API batch embeddings: {e}")
            return [self._get_random_embedding(text) for text in texts]
    
    def _get_random_embedding(self, text: str) -> List[float]:
        """
        Generate a deterministic pseudo-random embedding vector based on text hash
        
        Args:
            text: Input text
            
        Returns:
            List[float]: Pseudo-random embedding vector
        """
        # Create a deterministic seed based on the text
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        seed = int(text_hash, 16) % (2**32)
        
        # Set random seed for reproducibility
        random.seed(seed)
        
        # Generate a random vector
        vector = [random.normalvariate(0, 1) for _ in range(self.embedding_dim)]
        
        # Normalize to unit length (cosine similarity space)
        magnitude = math.sqrt(sum(x * x for x in vector))
        if magnitude > 0:
            vector = [x / magnitude for x in vector]
            
        return vector
        
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current embedding model"""
        return {
            "backend": self.backend,
            "model_name": self.model_name,
            "embedding_dim": self.embedding_dim,
            "cache_size": len(self.cache),
            "device": self.device if hasattr(self, 'device') else None
        }
        
    def change_model(self, model_name: str, backend: str = None) -> bool:
        """
        Change the embedding model
        
        Args:
            model_name: New model name
            backend: New backend type (or None to keep current)
            
        Returns:
            bool: True if successful
        """
        try:
            old_model_name = self.model_name
            self.model_name = model_name
            
            if backend:
                self.backend = backend
                
            # Reinitialize if using HuggingFace
            if self.backend == "huggingface":
                self.model = None
                self._initialize_huggingface_model()
                
            # Re-initialize cache for new model
            self._init_cache()
            
            print(f"Changed embedding model from {old_model_name} to {self.model_name}")
            return True
        except Exception as e:
            print(f"Error changing embedding model: {e}")
            return False
