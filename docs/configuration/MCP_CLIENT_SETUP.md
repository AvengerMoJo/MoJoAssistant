# MoJoAssistant MCP Tools - LLM Client Setup Guide

## Overview
MoJoAssistant provides a comprehensive memory system with specialized tools for managing conversations and documents. This guide helps you configure your LLM client to use these tools effectively.

## Core Memory Tools

### `get_memory_context`
**Purpose:** Search across all memory tiers for relevant context
**When to use:** Always call this when you need information from previous conversations or stored knowledge
**How:** Provide a natural language query, get back relevant context items
**Why:** Ensures responses are informed by conversation history and stored knowledge

### `add_conversation`
**Purpose:** Preserve conversation context for future reference
**When to use:** IMMEDIATELY after every user question and your response
**How:** Pass the exact user message and your complete response
**Why:** Maintains conversation continuity and allows referencing previous exchanges

## Memory Management Tools

### Conversation Management

#### `list_recent_conversations`
**Purpose:** Review recent conversation history for cleanup
**When to use:** When you want to see what conversations are stored, or identify ones to remove
**How:** Optionally specify limit (default 10), get back list with IDs
**Why:** Helps you understand stored conversation history and manage memory

#### `remove_conversation_message`
**Purpose:** Clean up individual bad conversation messages
**When to use:** When other AI models generated inappropriate or incorrect responses
**How:** Get message ID from `list_recent_conversations`, then remove specific message
**Why:** Keeps conversation history clean and relevant

#### `remove_recent_conversations`
**Purpose:** Bulk cleanup of recent problematic conversations
**When to use:** When multiple recent interactions were bad quality
**How:** Specify count of most recent conversations to remove (1-100)
**Why:** Faster than removing conversations individually

### Document Management

#### `list_recent_documents`
**Purpose:** Review recently added knowledge base documents
**When to use:** When you want to see what reference materials are available, or identify documents to remove
**How:** Optionally specify limit (default 10), get back list with IDs and metadata
**Why:** Helps you understand what reference materials are stored

#### `remove_document`
**Purpose:** Clean up outdated or incorrect knowledge base documents
**When to use:** When documents are no longer relevant or contain incorrect information
**How:** Get document ID from `list_recent_documents`, then remove specific document
**Why:** Keeps knowledge base focused on useful, accurate reference material

### `add_documents`
**Purpose:** Add permanent reference materials to knowledge base
**When to use:** When you want to store documentation, code examples, or any information for future reference
**How:** Provide array of documents with optional metadata (title, tags, source)
**Why:** Builds a personal knowledge repository that can be searched via `get_memory_context`

### `end_conversation`
**Purpose:** Archive current conversation topic to long-term memory
**When to use:** When switching to a completely different topic or ending current discussion thread
**How:** Call with no parameters, moves conversation from working to archival memory
**Why:** Keeps working memory focused on current topics while preserving conversation history

### `toggle_multi_model`
**Purpose:** Switch between single and multi-model embedding for search accuracy
**When to use:** Enable for diverse content types, disable to reduce resource usage
**How:** Set enabled=true/false
**Why:** Balances search accuracy with computational efficiency

### `get_current_day`
**Purpose:** Get current date and time information
**When to use:** For temporal awareness, scheduling, date-sensitive queries
**How:** Returns comprehensive date/time data including timezone
**Why:** Provides accurate temporal context for all interactions

## Configuration for LLM Clients

### Claude Desktop Setup
```json
{
  "mcpServers": {
    "mojo-assistant": {
      "command": "python",
      "args": ["/path/to/unified_mcp_server.py", "--mode", "stdio"],
      "env": {
        "MCP_REQUIRE_AUTH": "false"
      }
    }
  }
}
```

### Client Usage Patterns

#### Standard Conversation Flow:
1. User asks question
2. Call `get_memory_context` to get relevant history
3. Generate response using context
4. Call `add_conversation` to preserve the exchange

#### Memory Management:
1. Regularly call `list_recent_conversations` to review stored content
2. Remove problematic messages with `remove_conversation_message`
3. Clean up knowledge base with `list_recent_documents` + `remove_document`

#### Knowledge Building:
1. Add important information with `add_documents`
2. Information becomes searchable via `get_memory_context`

## Best Practices

1. **Always call `add_conversation`** after each Q&A exchange
2. **Use `get_memory_context`** before responding to maintain context
3. **Regularly review** conversations with `list_recent_conversations`
4. **Clean up** bad content to maintain memory quality
5. **Add documents** for permanent reference materials
6. **Use `end_conversation`** when switching topics

## Global Coding Agent Rules (Cross-Agent Policy)

These rules are intended to apply across all coding agents integrated with MoJoAssistant MCP.

1. **Memory-first operation**: Call `get_memory_context` before major code decisions, and use retrieved context to self-correct.
2. **Conversation persistence**: Preserve key exchanges and decisions via `add_conversation`.
3. **Shared policy document**: Use `Coding Agents Rules.md` in the repository root as the canonical coding policy.
4. **Branch discipline**: Create `wip_<feature>` branches for active work; keep work there until fully tested.
5. **Controlled merges**: Merge `wip_<feature>` into `main` only on explicit user request.
6. **Commit authorship**: All commits must be authored as the user, not the agent; user retains responsibility for submitted code.

## Tool Availability
- **Active Tools:** 11 fully functional tools
- **Placeholders:** 3 tools (web_search, get_memory_stats, get_current_time) - disabled for simplicity

This setup provides a complete memory management system that enhances LLM capabilities with persistent, searchable conversation history and knowledge base.
