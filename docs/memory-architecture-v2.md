# MoJoAssistant Memory Architecture (v2)

This document provides a detailed overview of the current memory system architecture in MoJoAssistant, which is centered around a multi-tiered design and a powerful embedding-based retrieval system.

## Memory System Overview

The memory system is the core of MoJoAssistant, providing contextual awareness, long-term knowledge retention, and efficient information retrieval. It is designed to be modular and scalable, leveraging state-of-the-art sentence-transformer models for semantic search across all memory tiers. The central component is the `MemoryManager`, which orchestrates the flow of information between the different memory layers.

## Core Components

### 1. Memory Manager (`app/memory/memory_manager.py`)

The `MemoryManager` is the main entry point for all memory operations. It initializes and manages the different memory tiers and handles the core logic for storing and retrieving information. It is also responsible for managing the embedding models.

### 2. Embedding System (`app/memory/simplified_embeddings.py`)

A crucial component of the memory architecture is the embedding system. It uses high-quality bi-directional transformer models to convert text into numerical vectors, enabling semantic search.

**Key Features:**

*   **Multiple Backends:** Supports local HuggingFace models, API-based services (OpenAI, Cohere), and local embedding servers.
*   **Flexible Configuration:** Embedding models can be easily configured and switched via a JSON file.
*   **Caching:** Caches generated embeddings to improve performance and reduce redundant computations.

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

## Information Flow

1.  A new user query enters the **Working Memory**.
2.  The `MemoryManager` searches **Active Memory**, **Archival Memory**, and the **Knowledge Manager** for relevant context using semantic search on the embedded query.
3.  The retrieved context is combined with the Working Memory to form the final prompt for the LLM.
4.  After the interaction, the new conversation turn is added to Working Memory.
5.  As conversations age or the context window shifts, information is migrated from Working Memory to Active Memory, and eventually to Archival Memory.

This tiered approach ensures that the most relevant information is always readily available while maintaining a comprehensive long-term memory.
