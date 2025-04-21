# MoJoAssistant

A personal AI assistant framework with tiered memory management, contextual awareness, and modular capabilities.

## Project Overview

MoJoAssistant is a versatile AI assistant platform that combines multiple LLM interaction patterns, a tiered memory system, and tool integration to create a robust personal assistant. Unlike standard AI chat interfaces, MoJoAssistant maintains context awareness across sessions, can focus on specific tasks while retaining the broader conversation context, and provides a sandbox environment for processing and managing information.

## Memory Architecture

The core innovation of MoJoAssistant is its three-tiered memory system, inspired by human memory models and systems like MemGPT:

### 1. Working Memory (Short-term)
- Implemented in `app/memory/working_memory.py`
- Maintains the current conversation context
- Stores recent message exchanges
- Automatically manages token limits
- When capacity is reached, older messages are "paged out" to Active Memory

### 2. Active Memory (Mid-term)
- Implemented in `app/memory/active_memory.py`
- Stores recent but not immediate conversation context
- Uses a paging system similar to computer memory management
- Pages contain groups of messages moved from Working Memory
- Uses access patterns to determine what to keep or archive
- Limited to a configurable number of pages (default: 20)

### 3. Archival Memory (Long-term)
- Implemented in `app/memory/archival_memory.py`
- Persistent storage of historical conversations and knowledge
- Uses vector embeddings for semantic similarity search
- Enables retrieval of relevant past information based on queries
- Stores conversation summaries and important extracted information

### 4. Knowledge Manager
- Implemented in `app/memory/knowledge_manager.py`
- Stores external documents and structured knowledge
- Chunks documents and uses embeddings for semantic retrieval
- Complements the conversation memory with factual information

## Memory Flow and Operation

1. **Current Conversation**: Messages are stored in Working Memory
2. **Memory Paging**: When Working Memory fills up, oldest messages are moved to Active Memory
3. **Context Retrieval**: When a query is received, the system:
   - Checks Working Memory for immediate context
   - Searches Active Memory for recent relevant pages
   - Searches Archival Memory for historical relevant information
   - Searches Knowledge Manager for relevant documents
   - Ranks and combines this context for the LLM

4. **End of Conversation**: 
   - Complete conversations are summarized
   - Moved to Active and Archival Memory for future reference
   - Working Memory is cleared for the next conversation

## LLM Integration

MoJoAssistant supports multiple LLM backends through a unified interface:

### 1. Local Models
- Uses `LocalLLMInterface` in `app/llm/local_llm_interface.py`
- Supports various model types (LLaMA, GPT4All, Mistral, etc.)
- Can connect to a local model server or start one automatically

### 2. API-based Models
- Uses `APILLMInterface` in `app/llm/api_llm_interface.py`
- Supports OpenAI, Claude, DeepSeek, etc.
- Normalizes different API formats to a consistent interface

### Memory-LLM Interaction

1. When a user query is received:
   - The Memory Manager retrieves relevant context from all memory tiers
   - Context is formatted and provided to the LLM along with the query
   - The LLM generates a response based on the query and context
   - The response and query are added to Working Memory

2. For different LLM types:
   - **Local models**: Context is formatted into a prompt with system instructions
   - **API models**: Context is formatted according to each API's message structure
   - All models receive the same context information, just in different formats

## Setting Up and Running

### Prerequisites
- Python 3.8+
- LLM backend (either local model or API access)
- Required packages: see `requirements.txt`

### Installation

1. Clone the repository
```bash
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Run the interactive CLI
```bash
python app/interactive-cli.py
```

### Configuration

MoJoAssistant can be configured in several ways:

1. **LLM Configuration**:
   - Create a JSON configuration file (see examples in `config/`)
   - Specify local model paths or API keys
   - Pass the config file using `--config` parameter

2. **Memory Settings**:
   - Working Memory size can be adjusted in `memory_manager.py`
   - Active Memory page count can be configured
   - Embedding model for vector search can be changed

3. **CLI Commands**:
   - `/stats` - Display memory statistics
   - `/save FILE` - Save memory state
   - `/load FILE` - Load memory state
   - `/add FILE` - Add document to knowledge base
   - `/end` - End current conversation
   - `/clear` - Clear screen
   - `/exit` - Exit application

## Use Cases

1. **Personal Assistant**:
   - Maintains conversation context over multiple sessions
   - Remembers user preferences and previous interactions
   - Can access personal knowledge repositories

2. **Research Helper**:
   - Integrates document knowledge with conversational memory
   - Retrieves relevant information based on queries
   - Maintains context across research sessions

3. **Educational Tool**:
   - Tracks learning progress across sessions
   - Recalls previously discussed topics when relevant
   - Provides consistent tutoring experience

## Future Enhancements

1. **Memory Improvements**:
   - Enhanced summarization capabilities
   - Structured knowledge extraction
   - Hierarchical memory organization

2. **Agent Capabilities**:
   - Task planning and decomposition
   - Tool selection and orchestration
   - Self-reflection capabilities

3. **User Experience**:
   - Web interface
   - Voice interaction
   - Multi-modal input/output

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.