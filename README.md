# MoJoAssistant

A personal AI assistant framework with advanced memory management, contextual awareness, and modular capabilities.

## Project Overview

MoJoAssistant is a versatile AI assistant platform that combines multiple LLM interaction patterns, memory systems, and tool integration to create a robust personal assistant. Unlike standard AI chat interfaces, MoJoAssistant maintains context awareness across sessions, can focus on specific tasks while retaining the broader conversation context, and provides a sandbox environment for processing and managing information.

## Architecture

### Core Components

1. **Memory Management System**
   - Hybrid architecture combining LangChain, LlamaIndex, and MemGPT-inspired approaches
   - Tiered memory storage (Working, Active, Archival)
   - Context pagination and memory swapping
   - Memory retrieval with relevance scoring and semantic search
   - Cross-referencing between conversation memory and knowledge

2. **Agent Framework**
   - Task planning and decomposition using LangChain agents
   - Tool selection and orchestration
   - Plan execution with feedback loops
   - Zero-shot and few-shot reasoning capabilities

3. **Knowledge Integration**
   - Document indexing and retrieval using LlamaIndex
   - Information extraction and structuring
   - Knowledge graph for relationship tracking
   - Versioning system for information updates

4. **Interface Layer**
   - CLI interaction
   - API endpoints for external integration
   - Conversation history visualization
   - Query and response formatting

## Memory Architecture

MoJoAssistant uses a hybrid memory management approach:

### Memory Tiers

1. **Working Memory**
   - LangChain's ConversationBufferMemory for immediate context
   - Handles current conversation state
   - Short-term retention with full context

2. **Active Memory**
   - MemGPT-inspired paging system for recent sessions
   - Memory swapping between working and archival storage
   - Context compression and summarization
   - Maintains recent conversation history with pagination

3. **Archival Memory**
   - Vector database (Qdrant/Milvus) for semantic storage
   - Long-term retention with metadata and embedding-based retrieval
   - Structured conversation summaries and entities
   - Automatic relevance scoring for memory retrieval

### Memory Manager

The unified Memory Manager handles:
- Cross-tier memory operations (promotion/demotion)
- Context windowing and pagination
- Embedding generation and semantic search
- Memory compression and summarization
- Entity and relationship tracking
- Integration with LlamaIndex document knowledge

## Implementation Roadmap

### Phase 1: Foundation Setup
- [x] Basic conversation interfaces
- [x] Simple memory storage
- [x] Local LLM integration (GPT4All)
- [ ] Core conversation loop with state persistence
- [ ] Basic error handling and logging

### Phase 2: Memory Architecture
- [ ] Implement tiered memory system (Working, Active, Archival)
- [ ] Build unified Memory Manager interface
- [ ] Implement MemGPT-inspired pagination system
- [ ] Set up vector database for Archival memory
- [ ] Create memory serialization format
- [ ] Develop relevance-based retrieval system
- [ ] Add conversation summarization capabilities

### Phase 3: Agent Capabilities
- [ ] Integrate LangChain agent framework
- [ ] Add tool integration system
- [ ] Create plan monitoring and correction mechanisms
- [ ] Develop structured output parsing
- [ ] Add self-reflection capabilities

### Phase 4: Knowledge Management
- [ ] Implement LlamaIndex for document storage and retrieval
- [ ] Create knowledge graph structure
- [ ] Develop versioning for knowledge updates
- [ ] Create information extraction pipeline
- [ ] Add retrieval-augmented generation
- [ ] Implement cross-referencing between memory and knowledge

### Phase 5: Integration & Optimization
- [ ] Optimize memory retrieval performance
- [ ] Implement multi-session persistence
- [ ] Create user preference learning system
- [ ] Design adaptive context management
- [ ] Add memory visualization and inspection tools

## Current Components

The project currently includes several prototype modules:

- **ConversationalMemory**: Maintains dialog history with customizable persona
- **ListSubjectDetail**: Generates and explores structured lists of topics
- **ZeroShotAgent**: Performs tasks using tools without explicit examples
- **PlanExecutorAgent**: Breaks down complex tasks and executes them step-by-step
- **Gorilla-OpenFunction**: Demonstrates function calling capabilities with an external API

## Getting Started

### Prerequisites
- Python 3.8+
- Local LLM model (currently using GPT4All)
- Required packages: langchain, llama-index, qdrant-client, openai, gpt4all

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

3. Download GPT4All model
```bash
# Will be downloaded automatically on first run, or can be manually placed at:
# ~/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin
```

4. Run the base conversation module
```bash
python utils/ConversationalMemory.py
```

## Development Guide

### Memory System Implementation

1. **Working Memory Layer**
   ```python
   from langchain.memory import ConversationBufferMemory
   
   working_memory = ConversationBufferMemory(
       return_messages=True,
       memory_key="chat_history"
   )
   ```

2. **Active Memory Layer**
   ```python
   class ActiveMemory:
       def __init__(self, max_pages=5, page_size=1000):
           self.pages = []
           self.max_pages = max_pages
           self.page_size = page_size
           
       def add_page(self, content, metadata):
           # Add memory page with pagination
           
       def retrieve_relevant(self, query):
           # Get relevant pages based on query
   ```

3. **Archival Memory Layer**
   ```python
   from qdrant_client import QdrantClient
   
   class ArchivalMemory:
       def __init__(self):
           self.client = QdrantClient(":memory:")  # In-memory for development
           
       def store(self, text, metadata, embedding):
           # Store in vector database
           
       def search(self, query_embedding, limit=5):
           # Semantic search
   ```

4. **Memory Manager**
   ```python
   class MemoryManager:
       def __init__(self):
           self.working_memory = WorkingMemory()
           self.active_memory = ActiveMemory()
           self.archival_memory = ArchivalMemory()
           
       def store_memory(self, content, source):
           # Store in appropriate tier
           
       def retrieve_context(self, query):
           # Retrieve from all tiers as needed
           
       def update_memory_state(self):
           # Handle memory pagination and promotion/demotion
   ```

### Knowledge Integration with LlamaIndex

```python
from llama_index import SimpleDirectoryReader, GPTVectorStoreIndex

class KnowledgeManager:
    def __init__(self):
        self.document_indices = {}
        
    def index_documents(self, directory, index_name):
        documents = SimpleDirectoryReader(directory).load_data()
        index = GPTVectorStoreIndex.from_documents(documents)
        self.document_indices[index_name] = index
        
    def query_knowledge(self, query_text, index_name=None):
        # Query specific or all indices
```

## Future Enhancements

- Web interface with visualization of thought processes
- Multi-modal input/output support
- Collaborative agent frameworks
- Fine-tuning capabilities for personalization
- Federated learning across personal instances

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
