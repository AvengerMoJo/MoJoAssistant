# MoJoAssistant

A personal AI assistant framework with memory management, contextual awareness, and modular capabilities.

## Project Overview

MoJoAssistant is a versatile AI assistant platform that combines multiple LLM interaction patterns, memory systems, and tool integration to create a robust personal assistant. Unlike standard AI chat interfaces, MoJoAssistant maintains context awareness across sessions, can focus on specific tasks while retaining the broader conversation context, and provides a sandbox environment for processing and managing information.

## Architecture

### Core Components

1. **Memory Management System**
   - Short-term conversation buffer
   - Long-term persistent storage
   - Context prioritization mechanism
   - Memory retrieval and relevance scoring

2. **Agent Framework**
   - Task planning and decomposition
   - Tool selection and orchestration
   - Plan execution with feedback loops
   - Zero-shot and few-shot reasoning capabilities

3. **Knowledge Integration**
   - Local document storage and retrieval
   - Information extraction and structuring
   - Knowledge graph for relationship tracking
   - Versioning system for information updates

4. **Interface Layer**
   - CLI interaction
   - API endpoints for external integration
   - Conversation history visualization
   - Query and response formatting

## Implementation Roadmap

### Phase 1: Foundation Setup
- [x] Basic conversation interfaces
- [x] Simple memory storage
- [x] Local LLM integration (GPT4All)
- [ ] Core conversation loop with state persistence
- [ ] Basic error handling and logging

### Phase 2: Memory Architecture
- [ ] Implement tiered memory system (buffer, short-term, long-term)
- [ ] Design context windowing mechanism
- [ ] Create memory serialization format
- [ ] Develop relevance-based retrieval system
- [ ] Add conversation summarization capabilities

### Phase 3: Agent Capabilities
- [ ] Implement planning framework
- [ ] Add tool integration system
- [ ] Create plan monitoring and correction mechanisms
- [ ] Develop structured output parsing
- [ ] Add self-reflection capabilities

### Phase 4: Knowledge Management
- [ ] Design document indexing system
- [ ] Implement versioning for knowledge updates
- [ ] Create information extraction pipeline
- [ ] Develop knowledge graph structure
- [ ] Add retrieval-augmented generation

### Phase 5: Integration & Optimization
- [ ] Optimize memory retrieval performance
- [ ] Add cross-referencing between knowledge and memory
- [ ] Implement multi-session persistence
- [ ] Create user preference learning system
- [ ] Design adaptive context management

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
- Required packages: langchain, openai, gpt4all

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

### Adding New Capabilities

1. Create a new module in the `utils` directory
2. Implement the core functionality using LangChain patterns
3. Add memory integration where appropriate
4. Connect to the central conversation manager

### Extending Memory Systems

1. Modify the Conversation class to include new storage methods
2. Implement retrieval methods with relevance scoring
3. Add serialization and deserialization functions
4. Connect to external storage if needed

### Creating New Tools

1. Define the tool interface following LangChain conventions
2. Implement the core functionality
3. Add to the available tools in agent configurations
4. Create appropriate schema for structured input/output

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
