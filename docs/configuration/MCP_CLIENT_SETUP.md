# MoJoAssistant MCP Tools — LLM Client Setup Guide

## Overview

MoJoAssistant exposes 14 hub tools over MCP. Each hub dispatches to sub-actions.
This guide helps you configure your LLM client to use these tools effectively.

## Core Tools

### `get_context`
**Purpose:** Read current context — orientation, attention inbox, recent events
**When to use:** At the start of any session to understand what's happening
**How:** Pass `type="orientation"` for overview, `type="attention"` for pending items

### `search_memory`
**Purpose:** Semantic search across conversations and documents
**When to use:** When you need information from previous conversations or stored knowledge
**How:** Provide a natural language query, get back relevant context items

### `add_conversation`
**Purpose:** Store a conversation turn in memory
**When to use:** After significant exchanges worth remembering
**How:** Pass `content` (the exchange text) and `scope` ("role" or "framework")

## Task Management

### `scheduler`
**Purpose:** Task lifecycle — add, list, get, remove tasks
**When to use:** To schedule work, check task status, or manage the queue
**Actions:** `add`, `list`, `get`, `remove`, `resume`

### `reply_to_task`
**Purpose:** Send a HITL reply to a waiting task
**When to use:** When a task has paused to ask you a question
**How:** Pass `task_id` and `reply` (your answer)

## Memory & Knowledge

### `memory`
**Purpose:** Conversation management, document ingestion, stats
**When to use:** To manage stored conversations or ingest documents
**Actions:** `add`, `search`, `list`, `remove`, `stats`

### `knowledge`
**Purpose:** Code/doc repo indexing and file retrieval
**When to use:** To search indexed repositories or retrieve files
**Actions:** `search`, `get_file`, `add`

### `dream`
**Purpose:** Memory consolidation pipeline
**When to use:** To trigger dreaming, list archives, or check status
**Actions:** `process`, `list`, `upgrade`, `distill_inbox`

## Configuration

### `config`
**Purpose:** Runtime configuration, LLM resources, system health
**When to use:** To check or modify system configuration
**Actions:** `get`, `set`, `doctor`, `doctor_improve`

### `role`
**Purpose:** Role CRUD — create, update, list roles
**When to use:** To manage AI personas
**Actions:** `create`, `edit`, `list`, `get`

## Agents

### `dialog`
**Purpose:** Direct conversation with any role
**When to use:** To chat with a specific role outside of task execution
**How:** Pass `role_id` and `message`

### `agent`
**Purpose:** Coding agent lifecycle (Claude Code, OpenCode)
**When to use:** To manage coding agent instances
**Actions:** `start`, `stop`, `status`, `list`, `action`

### `external_agent`
**Purpose:** Google Workspace gateway (Calendar, Drive, Gmail)
**When to use:** To interact with Google services
**Actions:** `list`, `get`, `create`, `update`, `delete`

## Session History

### `task_session_read`
**Purpose:** Read the full message transcript for a completed task
**When to use:** To review what an agent did in a task

### `task_report_read`
**Purpose:** Read the structured result report for a completed task
**When to use:** To get the final answer from a completed task

## Best Practices

1. **Memory-first:** Call `get_context` at session start to understand current state
2. **Store important exchanges:** Use `add_conversation` after significant interactions
3. **Use roles:** Dispatch tasks to appropriate roles rather than doing everything yourself
4. **HITL when stuck:** Tasks that exhaust their budget will ask for more — reply via `reply_to_task`
5. **Check policy:** If a tool call is blocked, check the event log for policy violation details
