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

2. **Agent Framework**
   - Task planning and decomposition
   - Tool selection and orchestration
   - Plan execution with feedback loops

3. **Knowledge Integration**
   - Local document storage and retrieval
   - Information extraction and structuring
   - Knowledge graph for relationship tracking

4. **Interface Layer**
   - CLI interaction
   - API endpoints for external integration
   - Conversation history visualization

## Implementation Roadmap

### Phase 1: Foundation Setup ✓
- Basic conversation interfaces
- Simple memory storage
- Local LLM integration (GPT4All)
- Core conversation loop with state persistence
- Basic error handling and logging

### Phase 2: Memory Architecture ⚙️
- Tiered memory system (buffer, short-term, long-term) ✓
- Context windowing mechanism ✓
- Memory serialization format ✓
- Relevance-based retrieval system ⚙️
- Conversation summarization capabilities ⚙️

### Phase 3: Agent Capabilities ⚙️
- Planning framework ✓
- Tool integration system ✓
- Plan monitoring and correction ✓
- Structured output parsing ✓
- Self-reflection capabilities ⚙️

### Phase 4-5: Knowledge Management & Optimization
- See detailed roadmap in documentation

## Current Components

The project currently includes several prototype modules:

- **ConversationalMemory**: Maintains dialog history with customizable persona
- **Conversation**: Core memory system for storing and retrieving conversations
- **ListSubjectDetail**: Generates and explores structured lists of topics
- **ZeroShotAgent**: Performs tasks using tools without explicit examples
- **PlanExecutorAgent**: Breaks down complex tasks and executes them step-by-step
- **Gorilla-OpenFunction**: Demonstrates function calling capabilities

See `docs/MemoryModulesArchitecture.md` for detailed documentation on the memory system.

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

3. Run the base conversation module
```bash
python utils/ConversationalMemory.py
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
