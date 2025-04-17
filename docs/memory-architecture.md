# Memory Modules Architecture

This document provides a detailed overview of the memory system architecture in MoJoAssistant.

## Memory System Overview

The memory system in MoJoAssistant is designed to provide contextual awareness, persistence across sessions, and efficient retrieval of relevant information. It combines different memory types and storage mechanisms to create a comprehensive memory management solution.

## Memory Components

### ConversationalMemory

`ConversationalMemory` is implemented in `utils/ConverstaionalMemory.py` and provides:

- Short-term conversation context using LangChain's `ConversationBufferMemory`
- Customizable AI persona via templating
- Interactive conversation capabilities with context retention
- Backend options (gptj or mpt) for different conversation styles

```python
# Key implementation features
template = """AI's Persona:
The following is a single final record of the last dialog between a human and an AI.\
2. The AI is smart assitant provides lots of specific details to answers human's question. \
3. If the AI does not know the answer, it truthfully says it does not know.\
4. If human is not asking a question. AI will only reply a single line of friendly conversation.\

Information:
Previous conversation:
{history}

Prompt:
Final conversation dialog:
Human: {input}

Response:
AI:"""

PROMPT = PromptTemplate(input_variables=["history", "input"], template=template)
conversation = ConversationChain(
    prompt=PROMPT,
    llm=llm,
    verbose=True,
    memory=ConversationBufferMemory(human_prefix="Human"),
)
```

### Conversation

`Conversation` is implemented in `utils/Conversation.py` and serves as the core memory persistence system:

- Stores conversation entries with timestamps
- Provides methods for retrieving and displaying conversation history
- Supports multiple storage backends (JSON, Google Sheets)
- Handles serialization and deserialization of conversation data

```python
# Core functionality
def add_conversation(self, question, answer):
    conversation = {
            'timestamp': datetime.datetime.now().timestamp(),
            'question': question,
            'answer': answer
    }
    self.conversations.append(conversation)

def store_conversations_to_json(self):
    with open('conversations.json', 'w') as f:
        json.dump(self.conversations, f)
        print("Conversations stored to conversations.json")
```

## Memory Types

### Short-term Memory

Short-term memory maintains the current conversation context and includes:

- Recent conversation turns
- Current user query and assistant response
- Temporary context information

This is primarily implemented using LangChain's `ConversationBufferMemory`, which keeps a running log of the conversation that can be included in the context window of the language model.

### Long-term Memory

Long-term memory provides persistent storage across sessions and includes:

- Historical conversations
- User preferences and information
- Learned patterns and frequently accessed information

This is implemented through both local file storage (JSON) and optional cloud storage (Google Sheets integration).

## Memory Operations

### Storage

The system provides multiple storage mechanisms:

- In-memory storage for active conversations
- JSON file serialization for local persistence
- Google Sheets integration for cloud-based storage

Example usage:

```python
from utils.Conversation import Conversation

# Create a new conversation manager
memory = Conversation()

# Add conversations
memory.add_conversation("What's the weather like?", "It's sunny today.")

# Store conversations
memory.store_conversations_to_json()  # Local storage
memory.store_conversations_to_cloud()  # Cloud storage (requires setup)
```

### Retrieval

Current retrieval mechanisms include:

- Sequential access to conversation history
- Timestamp-based filtering
- Full conversation dump for analysis

Planned enhancements:

- Semantic search for relevant context
- Relevance scoring based on current query
- Summarization of historical conversations

### Integration with LLM Context

The memory system integrates with language models through:

- Template-based prompt construction including conversation history
- Dynamic context window management
- Persona-aware conversation handling

## Extending the Memory System

### Adding New Storage Backends

To add a new storage backend:

1. Create a new method in the `Conversation` class
2. Implement serialization logic for the target storage
3. Add appropriate error handling and status reporting
4. (Optional) Add deserialization for loading from the same backend

Example:

```python
def store_conversations_to_database(self, connection_string):
    try:
        # Connect to database
        db = Database(connection_string)
        
        # Store conversations
        for conversation in self.conversations:
            db.insert("conversations", conversation)
            
        print("Conversations stored to database")
    except Exception as e:
        print(f"Error storing conversations: {e}")
```

### Implementing Memory Relevance

To add relevance-based retrieval:

1. Add embedding functionality to conversation entries
2. Implement vector similarity search
3. Create a relevance scoring mechanism
4. Add a method for retrieving top-N relevant conversations

### Adding Summarization

To implement conversation summarization:

1. Create a method that takes a list of conversations
2. Use the LLM to generate a summary
3. Store the summary as metadata
4. Add functionality to retrieve and update summaries

## Future Enhancements

Planned enhancements for the memory system include:

1. **Hierarchical Memory Structure**
   - Episodic memory for event sequences
   - Semantic memory for concept relationships
   - Procedural memory for task patterns

2. **Advanced Retrieval Mechanisms**
   - Vector-based similarity search
   - Context-aware relevance ranking
   - Dynamic memory compression and expansion

3. **Multi-Modal Memory**
   - Support for storing and retrieving different data types
   - Cross-modal association and retrieval
   - Media attachment capabilities

4. **Memory Analytics**
   - Usage patterns and statistics
   - Memory health monitoring
   - Optimization recommendations

5. **Memory Security**
   - Encryption for sensitive information
   - Access control and permissions
   - Compliance with privacy standards
