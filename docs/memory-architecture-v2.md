# MoJoAssistant Memory Architecture (v2.1 - Parallel Optimized)

This document provides a detailed overview of the current memory system architecture in MoJoAssistant, which is centered around a **human-like multi-tiered design** with **parallel async retrieval** for optimal performance.

## Memory System Overview

The memory system is the core of MoJoAssistant, providing contextual awareness, long-term knowledge retention, and **lightning-fast parallel information retrieval**. It is designed to be modular and scalable, leveraging state-of-the-art sentence-transformer models for semantic search across all memory tiers.

### 🧠 **Human-Like Memory Architecture**
Our system mimics the human brain's memory structure with **parallel activation** of all memory tiers:

```
┌─────────────────────────────────────────────────────┐
│  Working Memory (Current Attention)                 │
│  ↓ Always active - immediate context               │
└─────────────────────────────────────────────────────┘
              ↓ (parallel retrieval)
┌─────────────────────────────────────────────────────┐
│  Active Memory (Recent Recall)                      │
│  ↓ Fast semantic retrieval from recent conversations│
└─────────────────────────────────────────────────────┘
              ↓ (parallel retrieval)
┌─────────────────────────────────────────────────────┐
│  Archival Memory (Long-term Storage)                │
│  ↓ Deep semantic search through conversation history│
└─────────────────────────────────────────────────────┘
              ↓ (parallel retrieval)
┌─────────────────────────────────────────────────────┐
│  Knowledge Base (Factual Memory)                    │
│  ↓ Document search and retrieval                   │
└─────────────────────────────────────────────────────┘

All tiers searched IN PARALLEL → LLM integrates results
```

### ⚡ **Performance Breakthrough**
- **3-4x faster retrieval** through parallel async architecture
- **Before**: Sequential search (400ms total)
- **After**: Parallel search (~100ms total)
- **Graceful fallback** chain ensures reliability

## Core Components

### 1. Memory Service (`app/services/memory_service.py`)

The `MemoryService` is the main entry point for all memory operations. It now features **parallel async retrieval** as its core innovation:

**Key Features:**
- **Parallel Context Retrieval**: `get_context_for_query()` uses `asyncio.gather()` to search all tiers simultaneously
- **Thread Pool Execution**: CPU-intensive embedding operations run in `ThreadPoolExecutor`
- **Graceful Fallback**: Automatic fallback to sequential retrieval if parallel fails
- **Performance Logging**: Real-time monitoring of retrieval speed improvements
- **Memory Tier Management**: Orchestrates flow between Working → Active → Archival → Knowledge Base

**Parallel Retrieval Architecture:**
```python
# Before (Sequential): 400ms total
working_results = search_working_memory(query)      # 100ms
active_results = search_active_memory(query)        # 100ms
archival_results = search_archival_memory(query)    # 100ms
knowledge_results = search_knowledge_base(query)    # 100ms

# After (Parallel): ~100ms total
results = await asyncio.gather(
    search_working_memory_async(query),
    search_active_memory_async(query),
    search_archival_memory_async(query),
    search_knowledge_base_async(query)
)  # All execute simultaneously
```

### 2. Hybrid Memory Service (`app/services/hybrid_memory_service.py`)

**Next-Generation Multi-Model Memory** with parallel retrieval across multiple embedding models:

**Advanced Features:**
- **Parallel Multi-Model Search**: Searches multiple embedding models simultaneously (bge-m3, gemma, etc.)
- **Model Diversity**: Each model captures different semantic aspects for richer context
- **Result Deduplication**: Intelligent merging of results from different models
- **Automatic Fallback**: Parallel → Sequential → Single-model graceful degradation
- **Performance Monitoring**: Real-time metrics for multi-model retrieval speed

**Multi-Model Parallel Architecture:**
```python
# Parallel search across all available models
tasks = []
for model_key in ['bge-m3:1024', 'gemma:768', 'gemma:256']:
    if model_key in self.embedding_models:
        tasks.append(self._search_multi_model_async(query, model_key))

# Execute all model searches in parallel
results = await asyncio.gather(*tasks)
# Merge, deduplicate, and rank results
```

### 3. Embedding System (`app/memory/simplified_embeddings.py`)

A crucial component of the memory architecture is the embedding system. It uses high-quality bi-directional transformer models to convert text into numerical vectors, enabling semantic search.

**Key Features:**
- **Multiple Backends:** Supports local HuggingFace models, API-based services (OpenAI, Cohere), and local embedding servers
- **Flexible Configuration:** Embedding models can be easily configured and switched via a JSON file
- **Caching:** Caches generated embeddings to improve performance and reduce redundant computations
- **Thread-Safe Operations:** Optimized for parallel execution in multi-threaded environments

## Memory Tiers

The memory is structured into four distinct tiers, each serving a specific purpose:

### 1. Working Memory (`app/memory/working_memory.py`)

*   **Purpose:** Holds the context of the immediate, ongoing conversation.
*   **Functionality:** Stores the most recent user queries and assistant responses. This tier ensures that the assistant can follow the current conversational thread. It operates on raw text and is typically cleared after each session.

### 2. Active Memory (`app/memory/active_memory.py`)

*   **Purpose:** Stores recent conversations for semantic retrieval.
*   **Functionality:** When a conversation is complete, its content is moved from Working Memory to Active Memory. Here, the conversational turns are embedded and stored. This allows the assistant to recall information from recent but not immediate conversations based on semantic similarity to the current query.

### 3. Archival Memory (`app/memory/archival_memory.py`)

*   **Purpose:** Provides long-term, persistent storage for all conversations.
*   **Functionality:** Over time, information from Active Memory is moved to Archival Memory. This tier stores the full history of interactions in an embedded format, allowing the assistant to retrieve relevant information from its entire history. This is the assistant's long-term memory.

### 4. Knowledge Manager (`app/memory/knowledge_manager.py`)

*   **Purpose:** Stores and manages external documents and knowledge sources.
*   **Functionality:** This tier allows you to load external documents (e.g., text files, PDFs) into the assistant's memory. The documents are chunked, embedded, and stored for semantic search. This enables the assistant to answer questions based on a specific knowledge base.

## Information Flow (Parallel Optimized)

### 🚀 **Parallel Retrieval Process**

1. **Query Processing**: A new user query enters **Working Memory**
2. **Parallel Memory Activation**: The `MemoryService` **simultaneously** searches all memory tiers:
   ```python
   # All tiers search in parallel (like human brain activation)
   working_results, active_results, archival_results, knowledge_results = await asyncio.gather(
       search_working_memory_async(query_embedding),
       search_active_memory_async(query_embedding),
       search_archival_memory_async(query, max_items),
       search_knowledge_base_async(query, max_items)
   )
   ```
3. **Intelligent Merging**: Results from all tiers are combined and ranked by relevance
4. **Context Formation**: The retrieved context is combined with Working Memory to form the final prompt
5. **Memory Updates**: New conversation turns are added to Working Memory
6. **Background Consolidation**: Information migrates through tiers (Working → Active → Archival)

### 🧠 **Human-Like Memory Behavior**

- **Immediate Recall**: Working Memory provides instant access to current conversation
- **Recent Memory**: Active Memory quickly surfaces recent relevant conversations
- **Deep Memory**: Archival Memory performs semantic search through entire history
- **Factual Knowledge**: Knowledge Base retrieves relevant documents and facts
- **Memory Promotion**: Highly relevant archival memories get promoted back to Active Memory

### ⚡ **Performance Benefits**

- **3-4x Speed Improvement**: Parallel execution reduces retrieval time from ~400ms to ~100ms
- **Better Context Quality**: Multiple memory tiers provide richer, more diverse context
- **Scalable Architecture**: Performance improvements increase with more memory tiers
- **Reliability**: Graceful fallback ensures system never fails due to one tier

This **parallel-optimized tiered approach** ensures that the most relevant information is always readily available while maintaining lightning-fast access to comprehensive long-term memory.

## Technical Implementation Details

### Async/Await Architecture

The parallel retrieval system leverages Python's `asyncio` and `concurrent.futures.ThreadPoolExecutor`:

```python
async def _get_context_parallel(self, query: str, max_items: int) -> List[Dict[str, Any]]:
    """Parallel async context retrieval from all memory tiers"""
    query_embedding = self.embedding.get_text_embedding(query, prompt_name='query')

    # Create tasks for parallel execution
    tasks = [
        self._search_working_memory_async(query_embedding),
        self._search_active_memory_async(query_embedding),
        self._search_archival_memory_async(query, max_items),
        self._search_knowledge_base_async(query, max_items)
    ]

    # Execute all searches in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Merge and return results...
```

### Thread Safety and Error Handling

- **ThreadPoolExecutor**: CPU-intensive embedding operations run in separate threads
- **Exception Handling**: `return_exceptions=True` prevents single-tier failures from breaking the entire system
- **Graceful Degradation**: Automatic fallback to sequential retrieval if parallel fails
- **Performance Monitoring**: Real-time logging of retrieval times and speedup metrics

### Multi-Model Optimization (HybridMemoryService)

The hybrid service extends parallel retrieval to multiple embedding models:

- **Model Diversity**: Different models (bge-m3, gemma) capture different semantic aspects
- **Result Deduplication**: Content-based deduplication prevents redundant results
- **Weighted Scoring**: Results weighted by model reliability and relevance

## Future Roadmap: Towards AGI-Level Memory

### Phase 1: ✅ **Parallel Retrieval** (Completed)
- [x] Async parallel search across all memory tiers
- [x] Multi-model parallel support in HybridMemoryService
- [x] Performance monitoring and graceful fallbacks

### Phase 2: 🚧 **LLM-Guided Retrieval Strategy**
- [ ] LLM analyzes query to determine optimal memory search strategy
- [ ] Dynamic weighting of memory tiers based on query type
- [ ] Adaptive top-k selection per tier

### Phase 3: 🔮 **Memory Consolidation ("Dreaming")**
- [ ] Background async consolidation service
- [ ] Automatic summarization of old conversations
- [ ] Cross-tier relationship building and pattern detection
- [ ] Memory compression and optimization

### Phase 4: 🎯 **Associative Memory Networks**
- [ ] Memory linking system (like human associative recall)
- [ ] Cross-tier connection building
- [ ] Activation spreading for related memory retrieval
- [ ] Contextual memory activation patterns

This roadmap transforms MoJoAssistant from a fast retrieval system into a **computational model of human memory** - the foundation for true AGI-level conversational intelligence.
