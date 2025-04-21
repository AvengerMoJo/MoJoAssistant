# MoJoAssistant Enhanced Embedding System

This document explains the enhanced embedding system in MoJoAssistant, which now uses high-quality bi-directional transformer models for semantic search and retrieval across the memory system.

## Overview

The memory system in MoJoAssistant has been enhanced with state-of-the-art embedding capabilities, using advanced bi-directional models like "nomic-ai/nomic-embed-text-v2-moe" and other Sentence Transformers models. This significantly improves the quality of context retrieval, semantic search, and overall assistant performance.

## Key Features

- **High-Quality Embeddings**: Default integration with "nomic-ai/nomic-embed-text-v2-moe", a powerful bi-directional embedding model
- **Multiple Backend Options**: Support for local HuggingFace models, API-based services (OpenAI, Cohere), local servers, and fallback random embeddings
- **Efficient Caching**: Automatic caching of embeddings to improve performance and reduce computation
- **Easy Configuration**: Simple JSON configuration to switch between different embedding models
- **Hardware Optimization**: Support for different devices (CPU/CUDA) based on available hardware
- **CLI Integration**: Commands to view and change embedding models during runtime

## Available Embedding Backends

1. **HuggingFace (`huggingface`)**: Uses sentence-transformers to load models directly
2. **Local Server (`local`)**: Connects to a local embedding server (e.g., FastEmbed)
3. **API (`api`)**: Integrates with cloud embedding services like OpenAI and Cohere
4. **Random (`random`)**: Provides deterministic pseudo-random embeddings as a fallback

## Recommended Models

| Model | Backend | Dimensions | Use Case |
|-------|---------|------------|----------|
| nomic-ai/nomic-embed-text-v2-moe | huggingface | 768 | High-quality semantic search (default) |
| BAAI/bge-small-en-v1.5 | huggingface | 384 | Faster, lower resource usage |
| text-embedding-3-small | api (OpenAI) | 1536 | Cloud-based, high quality |
| embed-english-v3.0 | api (Cohere) | 1024 | Alternative cloud option |

## Configuration

The embedding system can be configured using a JSON configuration file. Here's an example:

```json
{
  "embedding_models": {
    "default": {
      "backend": "huggingface",
      "model_name": "nomic-ai/nomic-embed-text-v2-moe",
      "embedding_dim": 768,
      "device": "cuda"
    },
    "fast": {
      "backend": "huggingface",
      "model_name": "BAAI/bge-small-en-v1.5",
      "embedding_dim": 384,
      "device": "cpu"
    }
  }
}
```

## Usage in Memory Manager

The enhanced embedding system is integrated throughout the memory tiers:

1. **Working Memory**: Provides current conversation context
2. **Active Memory**: Stores recent conversations with semantic search
3. **Archival Memory**: Long-term storage with vector-based retrieval
4. **Knowledge Manager**: Document storage and semantic search

## CLI Commands

When using the interactive CLI, the following commands are available for managing embeddings:

- `/embed` - Display information about the current embedding model
- `/embed NAME` - Switch to a different embedding model by name (from config)
- `/stats` - Display memory statistics including embedding information

## Code Example

Here's a simple example of initializing the memory manager with a specific embedding model:

```python
from app.memory.memory_manager import MemoryManager

# Initialize with default settings (will use nomic-ai/nomic-embed-text-v2-moe)
memory_manager = MemoryManager()

# Or specify a different model
memory_manager = MemoryManager(
    embedding_model="BAAI/bge-small-en-v1.5",
    embedding_backend="huggingface",
    embedding_device="cpu"
)

# Later, switch to a different model if needed
memory_manager.set_embedding_model(
    model_name="text-embedding-3-small",
    backend="api"
)
```

## Installation Requirements

The enhanced embedding system requires the following packages:

- sentence-transformers
- torch
- numpy
- requests

These are automatically included in the updated requirements.txt file.

## Performance Considerations

- Large embedding models may require significant RAM and/or GPU memory
- For resource-constrained environments, consider using smaller models like "BAAI/bge-small-en-v1.5"
- The caching system helps reduce computation for frequently embedded text
- If using a GPU, ensure the appropriate CUDA version is installed

## Future Enhancements

Planned improvements for the embedding system include:

1. **Chunking Strategies**: Improved document chunking for better semantic search
2. **Hybrid Search**: Combining embeddings with keyword-based retrieval
3. **Quantization Support**: Using model quantization for faster inference
4. **Ensemble Models**: Combining multiple embedding models for better results
5. **Custom Fine-tuning**: Support for fine-tuned domain-specific models
