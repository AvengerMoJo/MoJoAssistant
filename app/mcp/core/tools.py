"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""

from typing import Dict, Any, List
import os
import time
import threading
import asyncio
from datetime import datetime
from app.git.git_service import GitService


def _is_llm_model_path(path: str) -> bool:
    """Check if a dot-path targets a model field under api_models (e.g. 'api_models.lmstudio.model')."""
    import fnmatch

    return fnmatch.fnmatch(path, "api_models.*.model")


class ToolRegistry:
    """Registry of available tools and their execution"""

    def __init__(
        self, memory_service, config: Dict[str, Any] | None = None, logger=None
    ):
        self.memory_service = memory_service
        self.logger = logger

        # Load Google API config from environment if not provided
        if config is None:
            config = {}

        # Ensure Google API config is loaded
        if "google_api_key" not in config:
            from app.config.mcp_config import load_mcp_config

            mcp_config = load_mcp_config()
            config.update(mcp_config)

        self.config = config

        # Initialize git service
        self.git_service = GitService()

        # Initialize shared MCPClientManager — single instance for both tool
        # dispatch (AgenticExecutor) and lifecycle management (AgentRegistry).
        from app.scheduler.mcp_client_manager import MCPClientManager
        self._mcp_client_manager = MCPClientManager()

        # Initialize unified Agent Registry (replaces separate manager init)
        from app.mcp.agents.registry import AgentRegistry

        self.agent_registry = AgentRegistry(logger=logger,
                                            mcp_client_manager=self._mcp_client_manager)

        # Initialize persistent event log
        from app.mcp.adapters.event_log import EventLog

        self._event_log = EventLog()

        # Initialize role manager
        from app.roles.role_manager import RoleManager
        self._role_manager = RoleManager()

        # Initialize SSE notifier for real-time task events
        from app.mcp.adapters.sse import SSENotifier

        self._sse_notifier = SSENotifier(event_log=self._event_log)

        # Initialize push adapter manager (independent notification channels)
        from app.mcp.adapters.push.manager import PushAdapterManager

        self._push_manager = PushAdapterManager(event_log=self._event_log)
        self._push_manager.load_and_start()

        # Initialize Scheduler (pass memory_service for agentic tool use)
        from app.scheduler.core import Scheduler

        self.scheduler = Scheduler(
            logger=logger,
            memory_service=memory_service,
            sse_notifier=self._sse_notifier,
            mcp_client_manager=self._mcp_client_manager,
        )
        self.scheduler_thread = None

        # Auto-start scheduler in background thread
        self._start_scheduler_daemon()

        # Config module registry — each entry maps a module name to its
        # config file, description, sensitive key patterns, and change hook.
        self._config_modules = {
            "llm": {
                "file": "config/llm_config.json",
                "description": "LLM providers, models, and task routing",
                "sensitive_keys": ["api_models.*.api_key"],
                "on_change": self._on_llm_config_change,
            },
            "embedding": {
                "file": "config/embedding_config.json",
                "description": "Embedding models and memory settings",
                "sensitive_keys": [
                    "embedding_models.openai.api_key",
                    "embedding_models.cohere.api_key",
                ],
                "on_change": None,
            },
            "resource_pool": {
                "file": "config/resource_pool.json",
                "description": "LLM resource pool — flat resources dict. Each entry: type, provider, base_url, api_key_env, model, tier, priority, context_limit. User personal accounts live in ~/.memory/config/resource_pool.json.",
                "sensitive_keys": [],
                "on_change": self._on_resource_pool_config_change,
            },
            "tool_catalog": {
                "file": "config/tool_catalog.json",
                "description": "Tool catalog — maps tool names to categories (memory, file, web, exec, comms). Roles declare tool_access by category. User custom tools live in ~/.memory/config/tool_catalog.json.",
                "sensitive_keys": [],
                "on_change": self._on_tool_catalog_change,
            },
            "agentic_tools": {
                "file": "config/dynamic_tools.json",
                "description": "Dynamic tool registry for agentic LLM tasks - tools available to AI agents during execution. AI can add/remove tools with policy enforcement and automatic rollback.",
                "sensitive_keys": [],
                "ai_writable": True,
                "on_change": self._on_agentic_tools_change,
            },
            "agentic_prompts": {
                "file": "config/planning_prompts.json",
                "description": "Planning prompts for agentic LLM tasks - workflow prompts that guide AI agent behavior. AI can add/update prompts with versioning and rollback support.",
                "sensitive_keys": [],
                "ai_writable": True,
                "on_change": self._on_agentic_prompts_change,
            },
            "policy": {
                "file": "config/safety_policy.json",
                "description": "Immutable safety rules for agentic tasks - limits what AI can do. AI can READ this module but CANNOT modify it (read-only for safety).",
                "sensitive_keys": [],
                "ai_writable": False,
                "on_change": None,
            },
            "scheduler": {
                "file": "config/scheduler_config.json",
                "description": "Default recurring scheduler tasks — add/remove/disable background tasks without code changes.",
                "sensitive_keys": [],
                "on_change": self._on_scheduler_config_change,
            },
            "notifications": {
                "file": "config/notifications_config.json",
                "description": "Push notification adapters — each adapter (ntfy, FCM, etc.) is an independent channel. Enable/disable or configure per adapter without affecting others.",
                "sensitive_keys": [],
                "on_change": self._on_notifications_config_change,
            },
        }

        # Initialize Role Manager
        from app.roles.role_manager import RoleManager
        self._role_manager = RoleManager()

        self.tools = self._define_tools()
        # Re-enable the working placeholder tools
        self.placeholder_tools = {
            "get_current_time",            # Absorbed into get_context
            "get_current_day",             # Absorbed into get_context
            "get_memory_context",          # Replaced by get_context + search_memory
            "get_memory_stats",            # Now under memory(action='stats')
            "get_recent_events",           # Now get_context(type='events')
            "get_attention_summary",       # Now get_context(type='attention')
            "task_session_read",           # Now get_context(type='task_session')
            "scheduler_resume_task",       # Retired — use reply_to_task
            # Memory management → memory hub
            "end_conversation",
            "toggle_multi_model",
            "list_recent_conversations",
            "remove_conversation_message",
            "remove_recent_conversations",
            "add_documents",
            "list_recent_documents",
            "remove_document",
            # Knowledge → knowledge hub
            "knowledge_add_repo",
            "knowledge_get_file",
            "knowledge_list_repos",
            # Agent → agent hub
            "agent_list_types",
            "agent_start",
            "agent_stop",
            "agent_status",
            "agent_list",
            "agent_restart",
            "agent_destroy",
            "agent_action",
            # Scheduler → scheduler hub
            "scheduler_add_task",
            "scheduler_list_tasks",
            "scheduler_get_status",
            "scheduler_get_task",
            "scheduler_remove_task",
            "scheduler_purge_tasks",
            "scheduler_start_daemon",
            "scheduler_stop_daemon",
            "scheduler_restart_daemon",
            "scheduler_daemon_status",
            "scheduler_list_assistant_tools",
            # Dream → dream hub
            "dreaming_process",
            "dreaming_list_archives",
            "dreaming_get_archive",
            "dreaming_upgrade_quality",
            # Config hub expansion
            "config_doctor",
            "llm_list_available_models",
            "resource_pool_status",
            "resource_pool_approve",
            "resource_pool_revoke",
            "resource_pool_smoke_test",
            "audit_get",
            "role_design_start",
            "role_design_answer",
            "role_create",
            "role_list",
            "role_get",
            # External agent → external_agent hub
            "google_service",
        }

        # Standardized user prompt templates for LLM usability
        self.user_prompt_templates = {
            "get_context": {
                "template": "Get current context and orientation",
                "examples": [
                    "Get current context",
                    "Orient me for this conversation",
                ],
                "usage_tip": "Call at conversation start. Returns timestamp, recent memory, and any urgent attention items.",
            },
            "search_memory": {
                "template": "Search my memory for: {query}",
                "examples": [
                    "Search my memory for information about Python programming",
                    "Find information about our previous discussion about machine learning",
                    "Search conversations and documents about climate change",
                ],
                "usage_tip": "Use after get_context when you need to find specific information. Specify types for targeted search.",
            },
            "add_documents": {
                "template": "Add these documents to my knowledge base: {content}",
                "examples": [
                    "Add this document to my knowledge base: Python best practices for web development",
                    "Store this reference material: Machine learning algorithms explained",
                    "Save this information: Climate change impacts and solutions",
                ],
                "usage_tip": "Use this tool to permanently store reference material, documentation, or any information that should be available for future conversations.",
            },
            "add_conversation": {
                "template": "Remember this conversation: User asked '{user_message}' and I responded '{assistant_message}'",
                "examples": [
                    "Remember this conversation: User asked 'What is Python?' and I responded 'Python is a high-level programming language...'",
                    "Store this exchange: User asked 'How do I install packages?' and I responded 'You can use pip to install Python packages...'",
                ],
                "usage_tip": "Call this tool IMMEDIATELY after every user question and your response to maintain conversation context.",
            },
            "end_conversation": {
                "template": "Archive our current conversation topic",
                "examples": [
                    "Archive our current conversation topic",
                    "End this discussion and save it to memory",
                ],
                "usage_tip": "Use when switching to a completely different topic or when the current discussion is complete.",
            },
            "toggle_multi_model": {
                "template": "Toggle multi-model embeddings: {enabled}",
                "examples": [
                    "Enable multi-model embeddings for better search accuracy",
                    "Disable multi-model embeddings to save resources",
                ],
                "usage_tip": "Enable when you need better search accuracy across diverse content types, disable to reduce resource usage.",
            },
            "list_recent_conversations": {
                "template": "Show me my recent conversation history",
                "examples": [
                    "Show me my recent conversation history",
                    "List my last 5 conversations",
                    "What have we discussed recently?",
                ],
                "usage_tip": "Use this to review conversation history or identify conversations that need cleanup.",
            },
            "remove_conversation_message": {
                "template": "Remove conversation message with ID: {message_id}",
                "examples": [
                    "Remove conversation message with ID: conv_12345",
                    "Delete this bad conversation: conv_67890",
                ],
                "usage_tip": "Use to remove specific problematic conversation messages that are cluttering memory.",
            },
            "remove_recent_conversations": {
                "template": "Remove my last {count} conversations",
                "examples": [
                    "Remove my last 3 conversations",
                    "Clean up the last 10 conversations",
                ],
                "usage_tip": "Use for bulk cleanup of multiple recent problematic conversations.",
            },
            "list_recent_documents": {
                "template": "Show me my recent documents in the knowledge base",
                "examples": [
                    "Show me my recent documents in the knowledge base",
                    "List my last 5 added documents",
                    "What reference materials do I have?",
                ],
                "usage_tip": "Use this to review what documents are stored in the knowledge base.",
            },
            "remove_document": {
                "template": "Remove document with ID: {document_id}",
                "examples": [
                    "Remove document with ID: doc_12345",
                    "Delete this outdated document: doc_67890",
                ],
                "usage_tip": "Use to remove specific documents that are outdated, incorrect, or no longer relevant.",
            },
            "web_search": {
                "template": "Search the web for: {query}",
                "examples": [
                    "Search the web for latest AI news",
                    "Find information about quantum computing advancements",
                    "Look up current weather in Tokyo",
                ],
                "usage_tip": "Use when you need up-to-date information, news, or data not available in local memory.",
            },
            "agent_list_types": {
                "template": "List available coding agent types",
                "examples": [
                    "What coding agent types are available?",
                    "List coding assistant agents",
                ],
                "usage_tip": "Use to discover available coding assistant types (opencode, claude_code) and their supported actions.",
            },
        }

    # ========================================================================
    # Scheduler Daemon Lifecycle Management
    # ========================================================================

    def _start_scheduler_daemon(self):
        """
        Start scheduler in background thread with its own event loop

        Similar to how OpenCodeManager starts processes, but the scheduler
        needs to run continuously in the background.
        """
        # Check if scheduler is actually running (not just thread alive)
        if (
            self.scheduler_thread
            and self.scheduler_thread.is_alive()
            and self.scheduler.running
        ):
            self._log("Scheduler daemon already running")
            return True

        # If old thread exists but scheduler stopped, wait for it to finish
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self._log("Waiting for old thread to finish...")
            self.scheduler_thread.join(timeout=3)
            if self.scheduler_thread.is_alive():
                self._log("Old thread still alive, may cause issues", "warning")

        def run_scheduler():
            """Run scheduler in dedicated thread with event loop"""
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                if self.logger:
                    self.logger.info("[ToolRegistry] Scheduler daemon thread started")

                # Start scheduler (blocks until stopped)
                loop.run_until_complete(self.scheduler.start())

                if self.logger:
                    self.logger.info(
                        "[ToolRegistry] Scheduler daemon thread exiting normally"
                    )
            except Exception as e:
                if self.logger:
                    self.logger.error(f"[ToolRegistry] Scheduler daemon error: {e}")
                    import traceback

                    self.logger.error(traceback.format_exc())
                else:
                    import traceback

                    print(f"[ToolRegistry] Scheduler daemon error: {e}")
                    traceback.print_exc()
            finally:
                loop.close()

        # Start scheduler thread
        self.scheduler_thread = threading.Thread(
            target=run_scheduler,
            name="SchedulerDaemon",
            daemon=True,  # Dies when main thread exits
        )
        self.scheduler_thread.start()

        if self.logger:
            self.logger.info("[ToolRegistry] Scheduler daemon started in background")

        # Give thread a moment to actually start and set running flag
        import time

        time.sleep(1.0)

        return True

    def _stop_scheduler_daemon(self):
        """Stop scheduler gracefully"""
        # Check if scheduler is marked as running (even if thread has already died)
        was_running = self.scheduler.running or (
            self.scheduler_thread and self.scheduler_thread.is_alive()
        )

        if not was_running:
            self._log("Scheduler daemon not running")
            return False

        # Signal scheduler to stop
        self.scheduler.stop()

        # Wait for thread to finish (with timeout) if it exists and is alive
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)

            if self.scheduler_thread.is_alive():
                self._log("Scheduler thread did not stop gracefully", "warning")
                return False

        self._log("Scheduler daemon stopped")
        self.scheduler_thread = None
        return True

    def _restart_scheduler_daemon(self):
        """Restart scheduler daemon"""
        self._stop_scheduler_daemon()
        return self._start_scheduler_daemon()

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[ToolRegistry] {message}")

    # ========================================================================
    # Tool Definitions
    # ========================================================================

    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define all available tools"""
        return [
            {
                "name": "get_context",
                "description": (
                    "Unified context read tool. Call with no args at conversation start for orientation.\n\n"
                    "type='orientation' (default): timestamp + date + recent memory + attention wake-up.\n"
                    "type='attention':    grouped inbox — blocking/alerts/digest/cursor. "
                    "                     params: since (ISO cursor), min_level (default 1).\n"
                    "type='events':       raw event log. "
                    "                     params: since, event_types (list), limit (default 50), include_data.\n"
                    "type='task_session': full output of a specific task. "
                    "                     params: task_id (required).\n\n"
                    "Discover task_ids from the task_sessions directory in the orientation response."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["orientation", "attention", "events", "task_session"],
                            "description": "What to read. Omit for orientation (default).",
                        },
                        "since": {
                            "type": "string",
                            "description": "ISO-8601 cursor (attention + events types).",
                        },
                        "min_level": {
                            "type": "integer",
                            "description": "Minimum hitl_level to include (attention type, default 1).",
                            "default": 1,
                        },
                        "event_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by event_type list (events type).",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max events to return (events type, default 50).",
                            "default": 50,
                        },
                        "include_data": {
                            "type": "boolean",
                            "description": "Include full event data payload (events type, default false).",
                            "default": False,
                        },
                        "task_id": {
                            "type": "string",
                            "description": "Task to read output from (task_session type).",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "search_memory",
                "description": (
                    "Semantic search across memory tiers. Use after get_context() when you need to "
                    "find specific information.\n\n"
                    "Types:\n"
                    "  conversations — working, active, and archival conversation history\n"
                    "  documents     — knowledge base (documents added via add_documents)\n"
                    "Omit types to search all. limit_per_type controls how many results come "
                    "from each tier — use higher values (10+) for broad research, lower (3) for "
                    "a quick check."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (English or Chinese)",
                            "minLength": 1,
                        },
                        "types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["conversations", "documents"],
                            },
                            "description": "Memory types to search. Omit for all types.",
                        },
                        "limit_per_type": {
                            "type": "integer",
                            "description": "Max results per memory type (default: 5, max: 20).",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                        "role_id": {
                            "type": "string",
                            "description": "Search this role's private memory in addition to shared memory (e.g. 'ahman', 'rebecca').",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "add_documents",
                "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base for future retrieval. When to use: Use this when you want to permanently store reference material, documentation, code snippets, or any information that should be available for future conversations. How it works: Documents are embedded and stored in the knowledge base with optional metadata. Why useful: Builds a personal knowledge repository that can be searched later using search_memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "documents": {
                            "type": "array",
                            "description": "Array of documents to add to knowledge base",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "Document content (supports Chinese and English text)",
                                        "minLength": 1,
                                    },
                                    "metadata": {
                                        "type": "object",
                                        "description": "Optional metadata (title, topic, tags, source, etc.) for better organization",
                                        "additionalProperties": True,
                                    },
                                },
                                "required": ["content"],
                            },
                            "minItems": 1,
                        }
                    },
                    "required": ["documents"],
                },
            },
            {
                "name": "add_conversation",
                "description": "PRESERVE CONVERSATION CONTEXT: Add this Q&A exchange to memory so I remember our conversation. Use IMMEDIATELY after every user question and my response to maintain context across our interaction. This ensures I can reference previous parts of our conversation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_message": {
                            "type": "string",
                            "description": "The exact user question/message that was just asked",
                            "minLength": 1,
                        },
                        "assistant_message": {
                            "type": "string",
                            "description": "My complete response to that user question",
                            "minLength": 1,
                        },
                    },
                    "required": ["user_message", "assistant_message"],
                },
            },
            {
                "name": "get_memory_stats",
                "description": "Get comprehensive statistics about the memory system including sizes of different memory tiers and performance metrics. When to use: Use to monitor memory usage, check system health, or understand how much information is stored. How it works: Returns detailed statistics from all memory tiers (working, active, archival, knowledge base). Why useful: Helps monitor system performance and memory utilization for optimization.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "end_conversation",
                "description": "ARCHIVE CURRENT TOPIC: End this conversation topic and archive it for long-term memory. Use when switching to a completely different topic or when the current discussion is complete. This moves our conversation from short-term working memory to long-term storage.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "toggle_multi_model",
                "description": "Enable or disable multi-model embedding support at runtime for enhanced semantic search. When to use: Enable when you need better search accuracy across diverse content types, disable to reduce resource usage. How it works: Switches between single and multi-model embedding modes. Why useful: Multi-model mode provides better semantic understanding but uses more computational resources.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "True to enable multi-model embeddings, False to disable (uses single model)",
                        }
                    },
                    "required": ["enabled"],
                },
            },
            {
                "name": "list_recent_conversations",
                "description": "REVIEW CONVERSATION HISTORY: Show me recent conversation exchanges that are stored in memory. Use this when I need to see what we've discussed before, or when I want to clean up unwanted conversations. This helps me understand our conversation history and manage stored content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent conversations to show (default: 10, max: 50)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50,
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "remove_conversation_message",
                "description": "CLEAN UP BAD CONVERSATIONS: Remove a specific problematic conversation message by its ID. Use when other AI models generated bad responses that are cluttering our memory. This helps keep our conversation history clean and relevant.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "ID of the bad message to remove (get this from list_recent_conversations first)",
                        }
                    },
                    "required": ["message_id"],
                },
            },
            {
                "name": "remove_recent_conversations",
                "description": "BULK CLEANUP: Remove multiple recent bad conversations at once. Use when several recent interactions were problematic and need to be cleared. This is faster than removing conversations one by one.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "Number of most recent conversations to remove (1-100)",
                            "minimum": 1,
                            "maximum": 100,
                        }
                    },
                    "required": ["count"],
                },
            },
            {
                "name": "list_recent_documents",
                "description": "REVIEW KNOWLEDGE BASE: Show me recently added documents in the knowledge base. Use this to see what reference materials are available, or to identify documents that need cleanup. This helps me understand what information is stored for future reference.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent documents to show (default: 10, max: 50)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50,
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "remove_document",
                "description": "CLEAN UP KNOWLEDGE BASE: Remove a specific document by its ID. Use when a document is outdated, incorrect, or no longer relevant. This keeps the knowledge base focused on useful reference material.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "ID of the document to remove (get this from list_recent_documents first)",
                        }
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "web_search",
                "description": "Search the internet for current information using Google Custom Search API. When to use: Use when you need up-to-date information, news, or data not available in local memory. How it works: Queries Google Custom Search API and returns relevant results with citations. Why useful: Provides access to current web information for comprehensive responses. [PLACEHOLDER - Not yet implemented]",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for finding current information on the web",
                            "minLength": 1,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of search results to return (max: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "google_service",
                "description": "Generic Google Workspace gateway via gws CLI. Use one tool by passing service/resource/method and optional params/body.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Google Workspace service (calendar, drive, sheets, gmail, docs, people)",
                            "minLength": 1,
                        },
                        "resource": {
                            "type": "string",
                            "description": "API resource name (e.g., events, files, spreadsheets, users)",
                            "minLength": 1,
                        },
                        "method": {
                            "type": "string",
                            "description": "API method (e.g., list, get, create, update, delete)",
                            "minLength": 1,
                        },
                        "sub_resource": {
                            "type": "string",
                            "description": "Optional sub-resource between resource and method",
                        },
                        "params": {
                            "type": "object",
                            "description": "JSON object for gws --params",
                        },
                        "json_body": {
                            "type": "object",
                            "description": "JSON request body for gws --json",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "table", "yaml", "csv"],
                            "default": "json",
                        },
                        "api_version": {
                            "type": "string",
                            "description": "Optional API version override",
                        },
                        "page_all": {
                            "type": "boolean",
                            "default": False,
                        },
                        "page_limit": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "page_delay": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "upload_path": {
                            "type": "string",
                            "description": "Optional local file path for upload",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Optional output file path for download/binary responses",
                        },
                    },
                    "required": ["service", "resource", "method"],
                },
            },
            {
                "name": "knowledge_add_repo",
                "description": "Register a git repository in the knowledge base for code analysis and retrieval. When to use: Use when you want to give the memory system access to a codebase for future reference and understanding. How it works: Clones repository using SSH key authentication and stores it locally for file access. Why useful: Enables code-aware conversations and allows storing code insights in memory. IMPORTANT: SSH key must NOT have a passphrase. If your key has a passphrase, remove it first with: ssh-keygen -p -f <key_path>",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Local name for the repository (e.g., 'MyProject')",
                            "minLength": 1,
                        },
                        "repo_url": {
                            "type": "string",
                            "description": "Git SSH URL (e.g., 'git@github.com:user/repo.git')",
                            "minLength": 1,
                        },
                        "ssh_key_path": {
                            "type": "string",
                            "description": "Path to SSH private key file (e.g., '~/.ssh/id_rsa'). Must be a passwordless SSH key!",
                            "minLength": 1,
                        },
                        "branch": {
                            "type": "string",
                            "description": "Branch to track (default: 'main')",
                            "default": "main",
                        },
                    },
                    "required": ["repo_name", "repo_url", "ssh_key_path"],
                },
            },
            {
                "name": "knowledge_get_file",
                "description": "Retrieve file content from a repository registered in the knowledge base. When to use: Use when you need to read the actual code content of specific files for analysis or reference. How it works: Retrieves current or historical file content directly from the repository. Why useful: Provides access to actual code for detailed analysis and understanding.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Name of registered repository",
                            "minLength": 1,
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Path to file within repository (e.g., 'src/main.py')",
                            "minLength": 1,
                        },
                        "git_hash": {
                            "type": "string",
                            "description": "Optional specific commit hash (defaults to latest)",
                            "minLength": 7,
                        },
                    },
                    "required": ["repo_name", "file_path"],
                },
            },
            {
                "name": "knowledge_list_repos",
                "description": "List all repositories registered in the knowledge base. When to use: Use to see which repositories are available for code analysis and their current status. How it works: Shows all registered repositories with their URLs, branches, and status. Why useful: Helps you understand what codebases are available for analysis.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            # External Agent Manager Tools — manages external agent processes (opencode, claude_code,
            # or any external agent). NOTE: These are NOT MoJo's internal agentic assistants.
            # To run a MoJo agentic assistant task (e.g. Ahman), use scheduler_add_task with
            # task_type="assistant" and a role_id.
            {
                "name": "agent_list_types",
                "description": "List all installed external agent types (e.g. 'opencode', 'claude_code'). Shows supported actions and how to identify instances. NOTE: These are external agent processes — for MoJo's internal agentic assistants use scheduler_add_task.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "agent_start",
                "description": "Start an external agent process. For opencode: pass git_url as identifier. For claude_code: pass session_id as identifier with working_dir in params. Use agent_list_types to see available types.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code'). Use agent_list_types to see available types.",
                            "minLength": 1,
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Instance identifier (git_url for opencode, session_id for claude_code)",
                            "minLength": 1,
                        },
                        "params": {
                            "type": "object",
                            "description": "Additional parameters (e.g. user_ssh_key for opencode, working_dir/model for claude_code)",
                        },
                    },
                    "required": ["agent_type", "identifier"],
                },
            },
            {
                "name": "agent_stop",
                "description": "Stop a coding assistant process. Terminates the process but preserves state for restart.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Instance identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type", "identifier"],
                },
            },
            {
                "name": "agent_status",
                "description": "Get the status of a coding assistant process. Shows PID, ports, health, and running state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Instance identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type", "identifier"],
                },
            },
            {
                "name": "agent_list",
                "description": "List all running instances of a coding assistant type. Shows identifiers, running status, and details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type"],
                },
            },
            {
                "name": "agent_restart",
                "description": "Restart a coding assistant process. Stops and starts the process with the same configuration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Instance identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type", "identifier"],
                },
            },
            {
                "name": "agent_destroy",
                "description": "Destroy a coding assistant instance and clean up all local resources. DESTRUCTIVE: permanently removes local data. The remote Git repository is NOT affected.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "External agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                        "identifier": {
                            "type": "string",
                            "description": "Instance identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type", "identifier"],
                },
            },
            {
                "name": "agent_action",
                "description": "Execute a backend-specific action on a coding assistant. Use agent_list_types to see supported actions per type. Examples: sandbox_create, llm_config, get_deploy_key.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                        "action": {
                            "type": "string",
                            "description": "Action name (e.g. 'sandbox_create', 'llm_config', 'get_deploy_key')",
                            "minLength": 1,
                        },
                        "params": {
                            "type": "object",
                            "description": "Action-specific parameters",
                        },
                    },
                    "required": ["agent_type", "action"],
                },
            },
            # Scheduler Tools
            {
                "name": "scheduler_add_task",
                "description": "Schedule a MoJo task for immediate, one-time (datetime), or recurring (cron) execution.\n\nTO RUN A MOJO AGENTIC ASSISTANT (e.g. Ahman): use task_type='assistant'. MoJo runs an LLM think-act loop where the assistant reasons, calls tools, and iterates until it produces a FINAL_ANSWER.\n  • Call scheduler_list_assistant_tools first to see what capabilities to grant.\n  • Key config fields: goal (required), role_id, planning_prompt, max_iterations, tier_preference, available_tools, resource_policy, final_answer_requirements.\n  • Assign a role with role_id to give the assistant a personality and model (see role_list).\n  • Example: task_type='assistant', role_id='ahman', goal='scan the local network'\n\nOTHER TASK TYPES:\n• custom — runs a single shell command, no LLM.\n• dreaming — memory consolidation pipeline.\n• agent — launches an external agent subprocess (opencode, claude_code, etc.).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Unique identifier for the task",
                            "minLength": 1,
                        },
                        "task_type": {
                            "type": "string",
                            "enum": [
                                "assistant",
                                "dreaming",
                                "custom",
                                "agent",
                                "scheduled",
                            ],
                            "description": "Type of task: assistant=MoJo agentic assistant with a role (use this to run Ahman or any internal assistant), custom=shell command, dreaming=memory consolidation, agent=external agent subprocess, scheduled=calendar event",
                        },
                        "schedule": {
                            "type": "string",
                            "description": "When to run (ISO datetime format, e.g., '2026-02-12T03:00:00'). Omit for immediate execution.",
                        },
                        "cron_expression": {
                            "type": "string",
                            "description": "Recurring schedule (cron format, e.g., '0 3 * * *' for daily at 3 AM). Overrides 'schedule'.",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "description": "Task priority (default: medium). Critical tasks run first.",
                        },
                        "config": {
                            "type": "object",
                            "description": "Task-specific configuration (for custom tasks, include 'command' key with shell command)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of what this task does",
                        },
                        "urgency": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": "How time-sensitive is this task? 1=can wait, 5=do it now. Combined with importance to set a minimum attention level on task events.",
                        },
                        "importance": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": "How much does this task matter? 1=nice-to-have, 5=critical outcome. Combined with urgency to set a minimum attention level on task events.",
                        },
                    },
                    "required": ["task_id", "task_type"],
                },
            },
            {
                "name": "scheduler_list_tasks",
                "description": "List all scheduled tasks with optional filtering. Shows task status, priority, schedule, and execution results. Use this to monitor what tasks are pending, running, or completed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": [
                                "pending",
                                "running",
                                "completed",
                                "failed",
                                "cancelled",
                                "waiting_for_input",
                            ],
                            "description": "Filter by task status",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "description": "Filter by priority",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of tasks to return (default: 100)",
                            "minimum": 1,
                            "maximum": 1000,
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "scheduler_get_status",
                "description": "Get current scheduler status including running state, tick count, current task being executed, and overall statistics. Use this to check if the scheduler is healthy and see performance metrics.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "scheduler_get_task",
                "description": "Get detailed information about a specific task by ID. Shows full task configuration, execution status, result, and retry count. Use this to check on a specific task's progress.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "scheduler_remove_task",
                "description": "Remove a task from the scheduler queue. Works for any task status (pending, failed, running, completed). Use this to clean up old or zombie tasks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task identifier",
                            "minLength": 1,
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "scheduler_purge_tasks",
                "description": "Bulk remove tasks by status. Use this to clean up all failed, completed, or zombie running tasks in one call.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["failed", "completed", "running", "cancelled"],
                            "description": "Remove all tasks with this status",
                        },
                        "exclude_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Task IDs to keep even if they match the status",
                        },
                    },
                    "required": ["status"],
                },
            },
            # Scheduler Daemon Control Tools
            {
                "name": "scheduler_start_daemon",
                "description": "Manually start the scheduler daemon if it's not running. The scheduler daemon is the background process that executes scheduled tasks. Normally it starts automatically with the MCP service, but you can use this to restart it if needed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "scheduler_stop_daemon",
                "description": "Stop the scheduler daemon gracefully. This will stop the background ticker loop that processes scheduled tasks. Tasks in the queue will be preserved and can be processed when the daemon restarts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "scheduler_restart_daemon",
                "description": "Restart the scheduler daemon. Useful if the scheduler appears stuck or you want to force a clean restart of the background processing loop.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "scheduler_daemon_status",
                "description": "Check if the scheduler daemon is running and get basic health information. Shows whether the background ticker is active, thread status, and basic statistics.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "scheduler_list_assistant_tools",
                "description": "List all tools that can be given to a MoJo agentic assistant via the available_tools field in scheduler_add_task. Returns each tool's name, description, and danger_level (low/medium/high). Call this before scheduling an agentic assistant task to know what capabilities to grant.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_tools",
                "description": "List all tools from the tool catalog, with category metadata. Use category filter to see tools for a specific access category (memory, file, web, exec, comms). Roles declare tool_access by category — e.g. tool_access: [\"memory\", \"web\"] grants all tools in those categories.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Filter by category: memory, file, web, exec, comms. Omit to list all tools.",
                            "enum": ["memory", "file", "web", "exec", "comms"],
                        }
                    },
                },
            },
            # Dreaming Tools
            {
                "name": "dreaming_process",
                "description": "Process a conversation through the dreaming pipeline (A→B→C→D). Transforms raw conversation into semantic chunks, synthesized clusters, and archived knowledge. Use this for immediate memory consolidation or to test the dreaming system.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "Unique identifier for this conversation",
                            "minLength": 1,
                        },
                        "conversation_text": {
                            "type": "string",
                            "description": "Raw conversation content (multi-language supported)",
                            "minLength": 1,
                        },
                        "quality_level": {
                            "type": "string",
                            "enum": ["basic", "good", "premium"],
                            "description": "Processing quality level (basic=local free, good=API budget, premium=extra cost). Default: basic",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata (topic, date, participants, etc.)",
                        },
                    },
                    "required": ["conversation_id", "conversation_text"],
                },
            },
            {
                "name": "dreaming_list_archives",
                "description": "List all archived conversations from the dreaming system. Shows conversation IDs, quality levels, entity counts, and archive metadata. Use this to see what has been consolidated into long-term memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "dreaming_get_archive",
                "description": "Retrieve a specific archived conversation with all its chunks, clusters, entities, and relationships. Use this to recall consolidated knowledge from past conversations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "ID of the archived conversation",
                            "minLength": 1,
                        },
                        "version": {
                            "type": "integer",
                            "description": "Specific version to retrieve (omit for latest version)",
                            "minimum": 1,
                        },
                    },
                    "required": ["conversation_id"],
                },
            },
            {
                "name": "dreaming_upgrade_quality",
                "description": "Upgrade an existing archive to higher quality by reprocessing with better LLM. Progressive enhancement: basic→good (uses API budget), good→premium (extra cost). Use when you need better quality consolidation for important conversations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "ID of the conversation to upgrade",
                            "minLength": 1,
                        },
                        "target_quality": {
                            "type": "string",
                            "enum": ["good", "premium"],
                            "description": "Target quality level to upgrade to",
                        },
                    },
                    "required": ["conversation_id", "target_quality"],
                },
            },
            # Generic Configuration Tool
            {
                "name": "config",
                "description": (
                    "Config management hub. Call with no action for help menu.\n\n"
                    "action='modules'                                    → list all config modules\n"
                    "action='get',    module, path?                      → read config\n"
                    "action='set',    module, path, value                → write config\n"
                    "action='list',   module                             → list config file structure\n"
                    "action='delete', module, path                       → remove a config key\n"
                    "action='validate', module                           → validate config\n"
                    "action='sync_local_models', resource_id             → sync models from local server\n\n"
                    "# Resource pool (runtime LLM state)\n"
                    "action='resource_status'                            → all resources + approval state\n"
                    "action='resource_approve',   resource_id            → approve a resource for use\n"
                    "action='resource_revoke',    resource_id            → revoke a resource\n"
                    "action='resource_smoke_test',resource_id            → test connectivity\n"
                    "action='llm_models',         resource_id            → list live models from server\n\n"
                    "# Validation\n"
                    "action='doctor'                                     → full config pre-flight report\n\n"
                    "# Role management\n"
                    "action='role_list'                                  → list all roles\n"
                    "action='role_get',           role_id                → get role details\n"
                    "action='role_create',        role_id, system_prompt, model_preference, ... → create role\n"
                    "action='role_design_start'                          → guided role design (Nine Chapter Q1)\n"
                    "action='role_design_answer', session_id, answer     → next design question / finish"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Operation to perform. Omit for help menu.",
                        },
                        "module": {
                            "type": "string",
                            "description": "Config module name (e.g. 'llm', 'embedding'). Required for get/set.",
                        },
                        "path": {
                            "type": "string",
                            "description": "Dot-notation path into config (e.g. 'api_models.lmstudio.model'). Optional for get, required for set.",
                        },
                        "value": {
                            "description": "Value to set at the given path. Required for action=set. Can be any JSON type.",
                        },
                        "validate": {
                            "type": "boolean",
                            "description": "For LLM model changes: validate the model is loaded in the server before applying (default: true)",
                        },
                        "resource_id": {"type": "string", "description": "Resource ID (resource_* and llm_models actions)."},
                        "role_id": {"type": "string", "description": "Role ID (role_* actions)."},
                        "system_prompt": {"type": "string", "description": "Role system prompt (role_create)."},
                        "model_preference": {"type": "string", "description": "Preferred model for role (role_create)."},
                        "session_id": {"type": "string", "description": "Design session ID (role_design_answer)."},
                        "answer": {"type": "string", "description": "Answer to design question (role_design_answer)."},
                    },
                    "required": [],
                },
            },
            # Memory Hub
            {
                "name": "memory",
                "description": (
                    "Memory management hub. Call with no action for help menu.\n\n"
                    "action='end_conversation'                   — archive current conversation topic\n"
                    "action='list_conversations', limit?         — recent conversation history\n"
                    "action='remove_conversation', id            — delete a specific conversation message\n"
                    "action='remove_conversations', count        — bulk delete recent conversations\n"
                    "action='add_documents', documents           — add reference material to knowledge base\n"
                    "action='list_documents', limit?             — recent knowledge base documents\n"
                    "action='remove_document', id                — delete a document\n"
                    "action='stats'                              — memory tier statistics\n"
                    "action='toggle_multi_model', enabled        — switch embedding mode"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Operation to perform. Omit for help menu.",
                        },
                        "limit": {"type": "integer", "description": "Result limit (list actions)."},
                        "id": {"type": "string", "description": "Message or document ID (remove actions)."},
                        "count": {"type": "integer", "description": "Number to remove (remove_conversations)."},
                        "documents": {
                            "type": "array",
                            "description": "Documents to add (add_documents action).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "metadata": {"type": "object", "additionalProperties": True},
                                },
                                "required": ["content"],
                            },
                        },
                        "enabled": {"type": "boolean", "description": "Embedding mode (toggle_multi_model)."},
                    },
                    "required": [],
                },
            },
            # Knowledge Hub
            {
                "name": "knowledge",
                "description": (
                    "Git repository knowledge base. Call with no action for help menu.\n\n"
                    "action='list_repos'                                       — list registered repos\n"
                    "action='add_repo', name, url, ssh_key_path, branch?      — register a repo\n"
                    "action='get_file', repo, path, git_hash?                 — read file from repo"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operation. Omit for help menu."},
                        "name": {"type": "string", "description": "Repository name."},
                        "url": {"type": "string", "description": "Git SSH URL."},
                        "ssh_key_path": {"type": "string", "description": "Path to passwordless SSH private key."},
                        "branch": {"type": "string", "description": "Branch to track (default: main)."},
                        "repo": {"type": "string", "description": "Registered repo name (get_file)."},
                        "path": {"type": "string", "description": "File path within repo (get_file)."},
                        "git_hash": {"type": "string", "description": "Commit hash (get_file, optional)."},
                    },
                    "required": [],
                },
            },
            # Scheduler Hub
            {
                "name": "scheduler",
                "description": (
                    "Scheduler management hub. Call with no action for help menu.\n\n"
                    "action='add',    task_id, type, goal, role_id?, available_tools?, ... — schedule a task\n"
                    "action='list',   status?, priority?, limit? — list tasks\n"
                    "action='get',    task_id                    — task detail\n"
                    "action='remove', task_id                    — remove a task\n"
                    "action='purge',  before_date?               — bulk remove old completed/failed tasks\n"
                    "action='status'                             — daemon + queue stats\n"
                    "action='daemon_start'                       — start the scheduler daemon\n"
                    "action='daemon_stop'                        — stop the scheduler daemon\n"
                    "action='daemon_restart'                     — restart the scheduler daemon\n"
                    "action='list_tools'                         — tools available to scheduled agents"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operation. Omit for help menu."},
                        "task_id": {"type": "string"},
                        "type": {"type": "string", "description": "Task type (add action)."},
                        "goal": {"type": "string", "description": "Task goal (add action)."},
                        "cron": {"type": "string", "description": "Cron expression (add action)."},
                        "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                        "role_id": {"type": "string", "description": "Role for assistant tasks (add action)."},
                        "available_tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tools the assistant may use (add action, type='assistant'). Call action='list_tools' to see all available tool names. If omitted the assistant only has ask_user.",
                        },
                        "max_iterations": {
                            "type": "integer",
                            "description": "Max think-act iterations before the task fails (add action, default 10).",
                        },
                        "status": {"type": "string", "description": "Filter by status (list action)."},
                        "limit": {"type": "integer"},
                        "before_date": {"type": "string", "description": "ISO date for purge cutoff."},
                    },
                    "required": [],
                },
            },
            # Dream Hub
            {
                "name": "dream",
                "description": (
                    "Memory consolidation (dreaming) hub. Call with no action for help menu.\n\n"
                    "action='process',  conversation_id, quality? — run dreaming pipeline\n"
                    "action='list'                                — list dreaming archives\n"
                    "action='get',      conversation_id, version? — retrieve archive\n"
                    "action='upgrade',  conversation_id, target_quality — quality upgrade"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operation. Omit for help menu."},
                        "conversation_id": {"type": "string"},
                        "quality": {"type": "string", "description": "Quality level (process action)."},
                        "version": {"type": "string", "description": "Archive version (get action)."},
                        "target_quality": {"type": "string", "description": "Target quality (upgrade action)."},
                    },
                    "required": [],
                },
            },
            # Dialog — direct conversation with a role
            {
                "name": "dialog",
                "description": (
                    "Talk directly to an assistant role in conversational mode.\n\n"
                    "The role responds with its full personality and knowledge from "
                    "its private research memory. This is NOT a task — the role will "
                    "NOT accept new task assignments here. Use scheduler to assign work.\n\n"
                    "action='chat',    role_id, message, session_id? — send a message\n"
                    "action='history', role_id, session_id?          — view session history\n"
                    "action='sessions',role_id                       — list all sessions for a role"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Operation: 'chat' (default), 'history', or 'sessions'.",
                        },
                        "role_id": {
                            "type": "string",
                            "description": "Which role to talk to (e.g. 'rebecca').",
                        },
                        "message": {
                            "type": "string",
                            "description": "Your message to the role (chat action).",
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Session ID for continuity. Omit to start a new session.",
                        },
                    },
                    "required": [],
                },
            },
            # Agent Hub
            {
                "name": "agent",
                "description": (
                    "External agent lifecycle hub. Call with no action for help menu.\n"
                    "NOTE: These are external agent processes (opencode, claude_code). "
                    "For MoJo internal agentic tasks use scheduler(action='add', type='assistant', role_id=...).\n\n"
                    "action='list_types'                          — available agent types\n"
                    "action='start',   agent_id, type, ...        — start an agent\n"
                    "action='stop',    agent_id                   — stop an agent\n"
                    "action='status',  agent_id                   — agent status\n"
                    "action='list'                                — all running agents\n"
                    "action='restart', agent_id                   — restart an agent\n"
                    "action='destroy', agent_id                   — destroy an agent\n"
                    "action='action',  agent_id, action, params   — send action to agent"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operation. Omit for help menu."},
                        "agent_id": {"type": "string"},
                        "type": {"type": "string", "description": "Agent type (start action)."},
                        "params": {"type": "object", "description": "Action params (action sub-action)."},
                    },
                    "required": [],
                },
            },
            # External Agent Hub
            {
                "name": "external_agent",
                "description": (
                    "External services, 3rd-party integrations, and coding agent HITL bridge. "
                    "Call with no action for help menu.\n\n"
                    "── HITL bridge (for coding agents connected via MCP) ──\n"
                    "action='ask_user', task_id, question, options? — pause and inject question into HITL inbox\n"
                    "action='check_reply', task_id — poll for user reply; returns {status:'answered',reply:...} or {status:'pending'}\n"
                    "action='run_task', prompt, working_dir?, task_id?, model? — spawn headless Claude Code with MoJo as MCP server\n\n"
                    "── Google Workspace ──\n"
                    "action='google', service, resource, method, params?, json_body?, format?, ...\n\n"
                    "── Coding agent backends ──\n"
                    "action='backend_servers' — list all configured coding agent backends\n"
                    "action='backend_health', server_id? — check if a backend is reachable\n"
                    "action='backend_session_list', server_id? — list sessions on a backend\n"
                    "action='backend_session_create', server_id? — create a new session\n"
                    "action='backend_session_message', session_id, content, server_id? — send a message\n"
                    "action='backend_session_messages', session_id, server_id? — get message history\n"
                    "action='backend_session_delete', session_id, server_id? — delete a session\n\n"
                    "Future: action='github', action='slack', action='notion', ..."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Action to perform. Omit for help menu."},
                        # HITL bridge params
                        "task_id": {"type": "string", "description": "Unique session/task ID (ask_user, check_reply, run_task)."},
                        "question": {"type": "string", "description": "Question to ask the user (ask_user)."},
                        "options": {"type": "array", "items": {"type": "string"}, "description": "Optional answer choices (ask_user)."},
                        "prompt": {"type": "string", "description": "Task prompt for headless Claude Code (run_task)."},
                        "working_dir": {"type": "string", "description": "Working directory for headless Claude Code (run_task)."},
                        "model": {"type": "string", "description": "Model override for headless Claude Code (run_task)."},
                        # Backend params
                        "server_id": {"type": "string", "description": "Backend server ID (backend actions). Omit for default server."},
                        "session_id": {"type": "string", "description": "Session ID (backend session actions)."},
                        "content": {"type": "string", "description": "Message content (backend_session_message)."},
                        # Google params
                        "service": {"type": "string", "description": "Google service (google action): calendar, drive, sheets, gmail, docs, people."},
                        "resource": {"type": "string", "description": "API resource (google action)."},
                        "method": {"type": "string", "description": "API method (google action): list, get, create, update, delete."},
                        "sub_resource": {"type": "string"},
                        "params": {"type": "object"},
                        "json_body": {"type": "object"},
                        "format": {"type": "string", "enum": ["json", "table", "yaml", "csv"], "default": "json"},
                        "api_version": {"type": "string"},
                        "page_all": {"type": "boolean", "default": False},
                        "page_limit": {"type": "integer", "minimum": 1},
                        "page_delay": {"type": "integer", "minimum": 0},
                        "upload_path": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "required": [],
                },
            },
            # Event Log polling (non-WebSocket clients)
            {
                "name": "get_recent_events",
                "description": "Poll the persistent event log for recent system events. Use this to check what has happened recently (task completions, failures, config changes, etc.). Events with notify_user=true or severity warning/error/critical are worth surfacing to the user. Advance your cursor by passing the timestamp of the last event you saw as since_timestamp.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "since_timestamp": {
                            "type": "string",
                            "description": "ISO-8601 timestamp. Only return events after this point. Omit for all recent events.",
                        },
                        "types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by event_type (e.g. ['task_failed', 'config_changed']). Omit for all types.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of events to return (default: 50, max: 500).",
                            "default": 50,
                        },
                        "include_data": {
                            "type": "boolean",
                            "description": "Include full event data payload (default: false — returns envelope only).",
                            "default": False,
                        },
                    },
                    "required": [],
                },
            },
            # Attention Layer — proactive situational awareness
            {
                "name": "get_attention_summary",
                "description": (
                    "Return a token-compact grouped summary of events that need attention, "
                    "bucketed by urgency. Use this at conversation start (or when checking in) "
                    "to discover tasks waiting for input, failures, and completions.\n\n"
                    "Response buckets:\n"
                    "  blocking  — level 4-5, requires immediate action; each item has reply_with + args\n"
                    "  alerts    — level 3, errors needing attention\n"
                    "  digest    — level 1-2, FYI completions and notifications (capped at 10)\n"
                    "  noise_count — suppressed level-0 events\n"
                    "  cursor    — pass as 'since' on next call to advance your position\n\n"
                    "Behaviour:\n"
                    "  - If blocking is non-empty: surface to user before anything else.\n"
                    "    Each item includes reply_with so you know how to respond.\n"
                    "  - If alerts is non-empty: mention in passing, ask if user wants to investigate.\n"
                    "  - If all buckets are empty: everything is quiet, proceed normally."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "since": {
                            "type": "string",
                            "description": "ISO-8601 cursor. Only return events after this timestamp. Omit for the last 24 hours.",
                        },
                        "min_level": {
                            "type": "integer",
                            "description": "Minimum hitl_level to include (default: 1 — suppresses level-0 noise).",
                            "default": 1,
                        },
                    },
                    "required": [],
                },
            },
            # Configuration Doctor
            {
                "name": "config_doctor",
                "description": (
                    "Validate all runtime configuration before running tasks. "
                    "Checks LLM resource reachability, API key presence, model name correctness, "
                    "role model_preference alignment, allowed_tools existence, and task sanity. "
                    "Returns structured pass/warn/error report. Run this when tasks fail with "
                    "cryptic errors to pinpoint configuration mistakes."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "categories": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Limit checks to specific categories: 'resource', 'role', 'task'. Omit to run all.",
                        },
                    },
                    "required": [],
                },
            },
            # Agentic Assistant — Role Design & Personality (Nine Chapter framework)
            {
                "name": "role_design_start",
                "description": "Start a Nine Chapter role design interview to create a MoJo agentic assistant personality. Guides across five dimensions (Core Values, Emotional Reaction, Cognitive Style, Social Orientation, Adaptability) to build a complete role config and system prompt. Returns the first question and a session_id for follow-up calls.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Optional initial description of the character to pre-fill the intro step.",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "role_design_answer",
                "description": "Submit the user's answer to the current role design question and get the next question. When step=synthesis, the draft role spec is returned for review. Reply 'yes' to finalise, 'adjust: ...' to refine, or 'restart' to begin again.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID from role_design_start.",
                        },
                        "answer": {
                            "type": "string",
                            "description": "The user's answer to the current question.",
                        },
                    },
                    "required": ["session_id", "answer"],
                },
            },
            {
                "name": "role_create",
                "description": "Save a finalised role config to the role library. Accepts either a session_id (auto-builds from session) or a complete role spec dict. Saved roles define the personality and model for a MoJo agentic assistant — assign via role_id in scheduler_add_task.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID of a completed design session (step=complete).",
                        },
                        "role": {
                            "type": "object",
                            "description": "Complete role spec dict (alternative to session_id).",
                        },
                        "model_preference": {
                            "type": "string",
                            "description": "Preferred LLM model for this role (e.g. 'qwen/qwen3-35b-a22b').",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tool names this role should have access to.",
                        },
                        "notify_on_completion": {
                            "type": "boolean",
                            "description": "Push a notification when a task assigned to this role completes. Defaults to false (system tasks are silent; user-initiated tasks always notify regardless).",
                        },
                        "policy": {
                            "type": "object",
                            "description": "Runtime permission policy for this role. Fields: allowed_tools (list), denied_tools (list), require_confirmation_for (list), max_bash_exec_per_task (int), sandbox_paths_only (bool).",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "role_list",
                "description": "List all saved agentic assistant roles with their Nine Chapter scores, archetypes, and purpose. Use role_id from this list when scheduling an assistant task.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "role_get",
                "description": "Get the full spec for a saved role including its system prompt and all dimension details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "role_id": {
                            "type": "string",
                            "description": "Role ID to retrieve.",
                        },
                    },
                    "required": ["role_id"],
                },
            },
            # LLM Server Discovery (not a config operation — queries external service)
            {
                "name": "llm_list_available_models",
                "description": "List models currently loaded in an OpenAI-compatible server (e.g. LMStudio). Queries the server's /models endpoint to show what's actually available for use.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "interface_name": {
                            "type": "string",
                            "description": "Name of the interface to query (defaults to active interface if omitted)",
                        },
                    },
                    "required": [],
                },
            },
            # Task Session Tools
            {
                "name": "task_session_read",
                "description": "Read the full conversation trail for an agentic task. Works for both running and completed tasks (live tracking). Returns session status, messages, final_answer, and timestamps.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "ID of the agentic task to read the session for",
                            "minLength": 1,
                        },
                        "include_metadata": {
                            "type": "boolean",
                            "description": "Include per-message metadata in the response (default: false)",
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "reply_to_task",
                "description": (
                    "Send a reply to an agentic task that is waiting for user input. "
                    "The task must be in 'waiting_for_input' status (check with scheduler_list_tasks). "
                    "The agent will resume from where it paused, using your reply as the answer."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "ID of the task in waiting_for_input status",
                            "minLength": 1,
                        },
                        "reply": {
                            "type": "string",
                            "description": "Your answer to the agent's question",
                            "minLength": 1,
                        },
                    },
                    "required": ["task_id", "reply"],
                },
            },
            {
                "name": "scheduler_resume_task",
                "description": "Resume a failed or timed-out agentic task. Creates a new task that loads the previous session's conversation and continues from where it left off.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "ID of the failed/timed_out agentic task to resume",
                            "minLength": 1,
                        },
                        "max_additional_iterations": {
                            "type": "integer",
                            "description": "Maximum additional LLM iterations for the resumed task (default: 10)",
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": ["task_id"],
                },
            },
            # Resource Pool Tools
            {
                "name": "audit_get",
                "description": "Show the audit trail of external LLM boundary crossings — every call to a non-local resource (free_api, paid) logged with task_id, role_id, resource_id, tier, model, and token counts. Content is never logged. Use task_id to filter to a specific task.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Filter to a specific task. Omit to see all recent crossings.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max records to return (default 50).",
                            "default": 50,
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "resource_pool_status",
                "description": "Get the status of all LLM resources in the resource pool. Shows model, tier, priority, availability status, and usage statistics for each resource. Use this to monitor resource health and utilization for agentic tasks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "resource_pool_approve",
                "description": "Approve a paid LLM resource for use by agentic tasks. Paid resources are not used by default — they must be explicitly approved. Use resource_pool_status to see available resource IDs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "resource_id": {
                            "type": "string",
                            "description": "ID of the paid resource to approve (e.g., 'openai_gpt4')",
                            "minLength": 1,
                        },
                    },
                    "required": ["resource_id"],
                },
            },
            {
                "name": "resource_pool_revoke",
                "description": "Revoke approval for a paid LLM resource, preventing agentic tasks from using it. The resource remains configured but will not be selected for agent use.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "resource_id": {
                            "type": "string",
                            "description": "ID of the paid resource to revoke approval for",
                            "minLength": 1,
                        },
                    },
                    "required": ["resource_id"],
                },
            },
            {
                "name": "resource_pool_smoke_test",
                "description": (
                    "Run an agentic capability smoke test on a specific LLM resource. "
                    "Validates that the model can: (1) emit real tool calls (not hallucinate results), "
                    "(2) produce <FINAL_ANSWER> tags within the iteration budget. "
                    "Sets agentic_capable flag on the resource. "
                    "Use before approving a new model for agentic tasks."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "resource_id": {
                            "type": "string",
                            "description": "ID of the resource to test (from resource_pool_status)",
                            "minLength": 1,
                        },
                        "full": {
                            "type": "boolean",
                            "description": "If true, also run extended checks (default: false)",
                            "default": False,
                        },
                    },
                    "required": ["resource_id"],
                },
            },
        ]

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools (excludes placeholders and disabled features)"""
        # Special case: web_search is implemented and should be available
        available_tools = [
            tool for tool in self.tools if tool["name"] not in self.placeholder_tools
        ]

        # Add web_search if it's not already included (implementation is complete)
        web_search_tool = next(
            (tool for tool in self.tools if tool["name"] == "web_search"), None
        )
        if web_search_tool and web_search_tool not in available_tools:
            available_tools.append(web_search_tool)

        # Agent tools are always present — agent_type validation happens at execution time

        return available_tools

    def get_user_prompt_template(self, tool_name: str) -> Dict[str, Any] | None:
        """Get user prompt template for a specific tool"""
        return self.user_prompt_templates.get(tool_name)

    def get_all_user_prompt_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get all user prompt templates"""
        return self.user_prompt_templates

    def get_tools_with_templates(self) -> List[Dict[str, Any]]:
        """Get list of available tools with their user prompt templates"""
        tools = self.get_tools()
        result = []

        for tool in tools:
            tool_name = tool["name"]
            template = self.get_user_prompt_template(tool_name)

            if template:
                tool_with_template = tool.copy()
                tool_with_template["user_prompt_template"] = template
                result.append(tool_with_template)
            else:
                result.append(tool)

        return result

    def get_tools_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get tools organized by category for better LLM usability"""
        categories = {
            "memory": [],
            "conversation": [],
            "knowledge": [],
            "git": [],
            "utilities": [],
            "opencode": [],
        }

        tools = self.get_tools()

        for tool in tools:
            tool_name = tool["name"]

            # Categorize tools
            if tool_name in ["get_context", "search_memory", "get_memory_stats"]:
                categories["memory"].append(tool)
            elif tool_name in [
                "add_conversation",
                "end_conversation",
                "list_recent_conversations",
                "remove_conversation_message",
                "remove_recent_conversations",
            ]:
                categories["conversation"].append(tool)
            elif tool_name in [
                "add_documents",
                "list_recent_documents",
                "remove_document",
            ]:
                categories["knowledge"].append(tool)
            elif tool_name in [
                "knowledge_add_repo",
                "knowledge_get_file",
                "knowledge_list_repos",
            ]:
                categories["knowledge"].append(tool)
            elif tool_name in [
                "toggle_multi_model",
                "web_search",
            ]:
                categories["utilities"].append(tool)
            elif tool_name.startswith("opencode_"):
                categories["opencode"].append(tool)

        return categories

    def get_tools_by_priority(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get tools organized by priority level"""
        priority_levels = {"high": [], "medium": [], "low": []}

        tools = self.get_tools()

        # Define priority mapping
        priority_mapping = {
            "get_context": "high",
            "search_memory": "high",
            "add_conversation": "high",
            "add_documents": "high",
            "end_conversation": "medium",
            "toggle_multi_model": "medium",
            "list_recent_conversations": "medium",
            "web_search": "medium",
            "knowledge_add_repo": "medium",
            "knowledge_get_file": "medium",
            "knowledge_list_repos": "medium",
            "remove_conversation_message": "low",
            "remove_recent_conversations": "low",
            "list_recent_documents": "low",
            "remove_document": "low",
        }

        for tool in tools:
            tool_name = tool["name"]
            priority = priority_mapping.get(tool_name, "medium")
            priority_levels[priority].append(tool)

        return priority_levels

    def get_essential_tools(self) -> List[Dict[str, Any]]:
        """Get essential tools that should always be available to LLMs"""
        essential_tool_names = [
            "get_context",        # Orientation — timestamp + recent memory + attention
            "search_memory",      # Targeted memory search
            "add_conversation",   # Conversation context preservation
            "add_documents",      # Knowledge base management
            "end_conversation",   # Conversation management
            "web_search",         # Current information access
        ]

        tools = self.get_tools()
        return [tool for tool in tools if tool["name"] in essential_tool_names]

    def get_category_description(self, category: str) -> str:
        """Get description for a category"""
        descriptions = {
            "memory": "Memory and context retrieval tools for accessing user's stored information",
            "conversation": "Conversation management tools for preserving and organizing dialogue history",
            "knowledge": "Knowledge base tools for managing reference materials and documents",
            "utilities": "Utility tools for web search, time information, and system configuration",
            "agents": "Unified coding agent management tools for starting, stopping, and managing agent instances",
        }
        return descriptions.get(category, "General tools")

    def get_tools_usage_guide(self) -> str:
        """
        Return the recommended system prompt and usage guide for MCP clients.

        This is the authoritative guide — returned by the MCP server when
        a client asks how to use the tools. It reflects the 12-tool architecture.
        """
        return """\
## MoJoAssistant — MCP Usage Guide

### Every Conversation — Start Here

Call get_context() as your first action. Returns in one shot:
- Current date, day of week, and time
- Last 3 memory items from the previous session
- attention.blocking — agents waiting for your input right now
- task_sessions — active or recently completed background tasks

If attention.blocking is non-empty, surface those items immediately.
Each blocking item includes reply_with + task_id so you know how to respond.

---

### Top-Level Tools (always available)

| Tool | When to use |
|------|------------|
| get_context() | First call every session. Orientation + attention check. |
| get_context(type="attention", since=cursor) | Cursor-based inbox polling. |
| get_context(type="task_session", task_id=...) | Read full task output before replying. |
| get_context(type="events", ...) | Raw event history — failures, config changes. |
| search_memory(query, types?, limit_per_type?) | Find past context. types: conversations, documents. |
| add_conversation(user_message, assistant_message) | After every exchange worth keeping. |
| reply_to_task(task_id, reply) | Answer an agent waiting for input (from attention.blocking). |
| web_search(query) | Current information not in local memory. |

---

### Hub Tools (call with no action to see help menu)

Every hub returns a compact help menu when called without arguments.
A wrong action also returns the help menu — you can never get stuck.

| Hub | Covers |
|-----|--------|
| memory(action) | end_conversation, list/remove conversations and documents, stats |
| knowledge(action) | Git repository access (add_repo, list_repos, get_file) |
| config(action) | LLM resources, roles, smoke tests, config doctor |
| scheduler(action) | Schedule tasks, list/get/remove tasks, daemon management |
| dream(action) | Dreaming pipeline, list/get/upgrade archives |
| agent(action) | Coding agent start/stop/status/action |
| external_agent(action) | Google services and future 3rd-party integrations |

---

### Workflow Pattern

```
1. get_context()
   → check attention.blocking (reply immediately if non-empty)
   → note task_sessions (any tasks to follow up on?)
   → time and recent memory now available

2. search_memory(query=user_topic) if deeper context needed
   → types=["conversations"] for past discussions
   → types=["documents"] for stored reference material

3. Respond to user

4. add_conversation(user_message, assistant_message)
   → skip trivial exchanges ("ok", "thanks")
   → always save when new information or decisions were made
```

---

### HITL Inbox — Replying to Agent Questions

```
get_context() shows:
  attention.blocking[0]:
    task_id: "ahman_scan_001"
    blurb: "Waiting: which subnet should I scan?"
    reply_with: "reply_to_task"

→ Optionally drill in first:
  get_context(type="task_session", task_id="ahman_scan_001")

→ Reply:
  reply_to_task(task_id="ahman_scan_001", reply="scan 10.0.0.0/24")

Agent resumes within seconds.
```

---

### Language & Formatting

- Respond in the user's language
- Use markdown when it aids clarity
- Use mermaid for diagrams
- Be concise — prefer direct answers
"""

    def get_copy_paste_prompt_list(self) -> str:
        """Generate a copy-paste friendly prompt list for users"""
        categories = self.get_tools_by_category()

        prompt_list = "# MCP Tools Prompt List\n\n"
        prompt_list += "Copy and paste these prompts into your MCP client:\n\n"

        for category, tools in categories.items():
            if tools:
                prompt_list += f"## {category.title()} Tools\n\n"

                for tool in tools:
                    tool_name = tool["name"]
                    template = self.get_user_prompt_template(tool_name)

                    prompt_list += f"### {tool_name}\n"
                    prompt_list += f"**Description**: {tool['description']}\n\n"

                    if template:
                        prompt_list += f"**Prompt Template**:\n```\n{template['template']}\n```\n\n"

                        prompt_list += "**Examples**:\n"
                        for i, example in enumerate(template["examples"], 1):
                            prompt_list += f"{i}. {example}\n"
                        prompt_list += "\n"

                        prompt_list += f"**Usage Tip**: {template['usage_tip']}\n\n"

                    prompt_list += "---\n\n"

        prompt_list += "## Quick Reference\n\n"
        prompt_list += "### High Priority (Use Frequently)\n"
        high_priority = [tool for tool in self.get_tools_by_priority()["high"]]
        for tool in high_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"

        prompt_list += "\n### Medium Priority (Supporting Tools)\n"
        medium_priority = [tool for tool in self.get_tools_by_priority()["medium"]]
        for tool in medium_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"

        prompt_list += "\n### Low Priority (Cleanup/Management)\n"
        low_priority = [tool for tool in self.get_tools_by_priority()["low"]]
        for tool in low_priority:
            prompt_list += f"- **{tool['name']}**: {tool['description'][:60]}...\n"

        return prompt_list

    def get_json_prompt_list(self) -> Dict[str, Any]:
        """Generate JSON format prompt list for programmatic access"""
        categories = self.get_tools_by_category()

        json_data = {
            "title": "MCP Tools Prompt List",
            "description": "Copy and paste prompts for MCP tools",
            "generated_at": datetime.now().isoformat(),
            "categories": {},
            "quick_reference": {
                "high_priority": [],
                "medium_priority": [],
                "low_priority": [],
            },
        }

        # Add categories
        for category, tools in categories.items():
            category_data = {
                "description": self.get_category_description(category),
                "tools": [],
            }

            for tool in tools:
                tool_name = tool["name"]
                template = self.get_user_prompt_template(tool_name)

                tool_data = {
                    "name": tool_name,
                    "description": tool["description"],
                    "input_schema": tool["inputSchema"],
                }

                if template:
                    tool_data.update(
                        {
                            "prompt_template": template["template"],
                            "examples": template["examples"],
                            "usage_tip": template["usage_tip"],
                        }
                    )

                category_data["tools"].append(tool_data)

            json_data["categories"][category] = category_data

        # Add quick reference
        for priority, tools in self.get_tools_by_priority().items():
            for tool in tools:
                json_data["quick_reference"][f"{priority}_priority"].append(
                    {"name": tool["name"], "description": tool["description"]}
                )

        json_data["total_tools"] = len(self.get_tools())
        return json_data

    def enable_placeholder_tool(self, tool_name: str):
        """Enable a placeholder tool (make it available to MCP)"""
        if tool_name in self.placeholder_tools:
            self.placeholder_tools.remove(tool_name)

    def disable_placeholder_tool(self, tool_name: str):
        """Disable a tool (make it unavailable to MCP but keep definition)"""
        if tool_name not in self.placeholder_tools:
            self.placeholder_tools.add(tool_name)

    async def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""

        # Check if this is a placeholder tool
        if name in self.placeholder_tools:
            return {
                "status": "placeholder",
                "message": f"Tool '{name}' is not yet implemented. This is a placeholder for future development.",
                "tool_name": name,
                "timestamp": time.time(),
            }

        if name == "get_context":
            return await self._execute_get_context(args)
        elif name == "search_memory":
            return await self._execute_search_memory(args)
        elif name == "add_conversation":
            return await self._execute_add_conversation(args)
        elif name == "get_memory_stats":
            return await self._execute_get_memory_stats(args)
        elif name == "add_documents":
            return await self._execute_add_documents(args)
        elif name == "end_conversation":
            return await self._execute_end_conversation(args)
        elif name == "toggle_multi_model":
            return await self._execute_toggle_multi_model(args)
        elif name == "list_recent_conversations":
            return await self._execute_list_recent_conversations(args)
        elif name == "remove_conversation_message":
            return await self._execute_remove_conversation_message(args)
        elif name == "remove_recent_conversations":
            return await self._execute_remove_recent_conversations(args)
        elif name == "list_recent_documents":
            return await self._execute_list_recent_documents(args)
        elif name == "remove_document":
            return await self._execute_remove_document(args)
        elif name == "web_search":
            return await self._execute_web_search(args)
        elif name == "google_service":
            return await self._execute_google_service(args)
        elif name == "get_current_day":
            return await self._execute_get_current_day(args)
        elif name == "get_current_time":
            return await self._execute_get_current_time(args)
        elif name == "knowledge_add_repo":
            return await self._execute_knowledge_add_repo(args)
        elif name == "knowledge_get_file":
            return await self._execute_knowledge_get_file(args)
        elif name == "knowledge_list_repos":
            return await self._execute_knowledge_list_repos(args)
        # Coding Agent Manager Tools
        elif name == "agent_list_types":
            return await self._execute_agent_list_types(args)
        elif name == "agent_start":
            return await self._execute_agent_start(args)
        elif name == "agent_stop":
            return await self._execute_agent_stop(args)
        elif name == "agent_status":
            return await self._execute_agent_status(args)
        elif name == "agent_list":
            return await self._execute_agent_list(args)
        elif name == "agent_restart":
            return await self._execute_agent_restart(args)
        elif name == "agent_destroy":
            return await self._execute_agent_destroy(args)
        elif name == "agent_action":
            return await self._execute_agent_action(args)
        # Scheduler Tools
        elif name == "scheduler_add_task":
            return await self._execute_scheduler_add_task(args)
        elif name == "scheduler_list_tasks":
            return await self._execute_scheduler_list_tasks(args)
        elif name == "scheduler_get_status":
            return await self._execute_scheduler_get_status(args)
        elif name == "scheduler_get_task":
            return await self._execute_scheduler_get_task(args)
        elif name == "scheduler_remove_task":
            return await self._execute_scheduler_remove_task(args)
        elif name == "scheduler_purge_tasks":
            return await self._execute_scheduler_purge_tasks(args)
        # Scheduler Daemon Control
        elif name == "scheduler_start_daemon":
            return await self._execute_scheduler_start_daemon(args)
        elif name == "scheduler_stop_daemon":
            return await self._execute_scheduler_stop_daemon(args)
        elif name == "scheduler_restart_daemon":
            return await self._execute_scheduler_restart_daemon(args)
        elif name == "scheduler_daemon_status":
            return await self._execute_scheduler_daemon_status(args)
        elif name == "scheduler_list_assistant_tools":
            return await self._execute_scheduler_list_assistant_tools(args)
        elif name == "list_tools":
            return await self._execute_list_tools(args)
        # Dreaming Tools
        elif name == "dreaming_process":
            return await self._execute_dreaming_process(args)
        elif name == "dreaming_list_archives":
            return await self._execute_dreaming_list_archives(args)
        elif name == "dreaming_get_archive":
            return await self._execute_dreaming_get_archive(args)
        elif name == "dreaming_upgrade_quality":
            return await self._execute_dreaming_upgrade_quality(args)
        # Event Log / Attention Layer
        elif name == "get_recent_events":
            return await self._execute_get_recent_events(args)
        elif name == "get_attention_summary":
            return await self._execute_get_attention_summary(args)
        elif name == "config_doctor":
            return await self._execute_config_doctor(args)
        # Configuration Tool
        elif name == "config":
            return await self._execute_config(args)
        elif name == "llm_list_available_models":
            return await self._execute_llm_list_available_models(args)
        # Task Session Tools
        elif name == "task_session_read":
            return await self._execute_task_session_read(args)
        elif name == "scheduler_resume_task":
            return await self._execute_scheduler_resume_task(args)
        elif name == "reply_to_task":
            return await self._execute_reply_to_task(args)
        # Audit Trail
        elif name == "audit_get":
            return await self._execute_audit_get(args)
        # Resource Pool Tools
        elif name == "resource_pool_status":
            return await self._execute_resource_pool_status(args)
        elif name == "resource_pool_approve":
            return await self._execute_resource_pool_approve(args)
        elif name == "resource_pool_revoke":
            return await self._execute_resource_pool_revoke(args)
        elif name == "resource_pool_smoke_test":
            return await self._execute_resource_pool_smoke_test(args)
        # Role System Tools
        elif name == "role_design_start":
            return await self._execute_role_design_start(args)
        elif name == "role_design_answer":
            return await self._execute_role_design_answer(args)
        elif name == "role_create":
            return await self._execute_role_create(args)
        elif name == "role_list":
            return await self._execute_role_list(args)
        elif name == "role_get":
            return await self._execute_role_get(args)
        # Hub Tools
        elif name == "memory":
            return await self._execute_memory(args)
        elif name == "knowledge":
            return await self._execute_knowledge(args)
        elif name == "scheduler":
            return await self._execute_scheduler_hub(args)
        elif name == "dream":
            return await self._execute_dream(args)
        elif name == "dialog":
            return await self._execute_dialog(args)
        elif name == "agent":
            return await self._execute_agent_hub(args)
        elif name == "external_agent":
            return await self._execute_external_agent(args)
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def _execute_get_memory_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory context search"""
        query = args.get("query", "")
        max_results = args.get("max_items", 10)

        # Use async version for better performance in async contexts
        results = await self.memory_service.get_context_for_query_async(
            query, max_items=max_results
        )

        response: Dict[str, Any] = {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": time.time(),
        }

        # Wake-up hook: inject attention summary if anything needs action.
        # Only adds the field when there is something to surface — quiet
        # conversations are not polluted with empty noise.
        try:
            attention = await self._execute_get_attention_summary({})
            blocking = attention.get("blocking", [])
            alerts = attention.get("alerts", [])
            if blocking or alerts:
                response["attention"] = {
                    "blocking": blocking,
                    "alerts": alerts,
                    "note": "Call get_context(type='attention') for full details or to advance cursor.",
                }
        except Exception:
            pass  # never let attention errors break memory context

        return response

    async def _execute_get_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unified context read tool — dispatch on type parameter.

        type='orientation' (default): timestamp + recent memory + attention wake-up.
        type='attention':             grouped inbox with cursor (get_attention_summary).
        type='events':                raw event log (get_recent_events).
        type='task_session':          full task output (task_session_read).
        """
        ctx_type = args.get("type", "orientation")

        if ctx_type == "attention":
            return await self._execute_get_attention_summary({
                "since": args.get("since"),
                "min_level": args.get("min_level", 1),
            })

        if ctx_type == "events":
            return await self._execute_get_recent_events({
                "since_timestamp": args.get("since"),
                "types": args.get("event_types"),
                "limit": args.get("limit", 50),
                "include_data": args.get("include_data", False),
            })

        if ctx_type == "task_session":
            task_id = args.get("task_id")
            if not task_id:
                return {"status": "error", "message": "task_id is required for type='task_session'"}
            return await self._execute_task_session_read({"task_id": task_id})

        # Default: orientation
        from datetime import datetime
        from app.roles.owner_context import load_owner_profile

        now = datetime.now()
        response: Dict[str, Any] = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "day_of_week": now.strftime("%A"),
            "time": now.strftime("%H:%M"),
        }

        # Owner identity — minimal slice (safe for external LLMs via tool result path)
        try:
            _owner = load_owner_profile()
            if _owner:
                _name = _owner.get("preferred_name") or _owner.get("name")
                _comm = _owner.get("communication_preferences", {})
                _owner_ctx: Dict[str, Any] = {}
                if _name:
                    _owner_ctx["name"] = _name
                if _comm:
                    _style = _comm.get("style", [])
                    _verbosity = _comm.get("verbosity_default", "")
                    if _style:
                        _owner_ctx["communication_style"] = _style
                    if _verbosity:
                        _owner_ctx["verbosity"] = _verbosity
                if _owner_ctx:
                    response["owner"] = _owner_ctx
        except Exception:
            pass  # never let owner profile errors break context

        # Last 3 items from working memory — recency-based, no embedding needed
        try:
            messages = self.memory_service.working_memory.get_messages()
            recent = [
                {"source": "working_memory", "content": m.content}
                for m in messages[-3:]
            ]
            response["recent_memory"] = recent
        except Exception:
            response["recent_memory"] = []

        # Attention wake-up hook — inject only if something needs action
        try:
            attention = await self._execute_get_attention_summary({})
            blocking = attention.get("blocking", [])
            alerts = attention.get("alerts", [])
            if blocking or alerts:
                response["attention"] = {
                    "blocking": blocking,
                    "alerts": alerts,
                    "note": "Call get_context(type='attention') for full details or to advance cursor.",
                }
        except Exception:
            pass  # never let attention errors break context

        # Task sessions directory — active + interesting tasks so LLMs can discover task_ids
        try:
            from app.scheduler.models import TaskStatus
            sessions = []

            # Running tasks
            for task in self.scheduler.list_tasks(status=TaskStatus.RUNNING):
                sessions.append({
                    "task_id": task.id,
                    "status": "running",
                    "title": task.description or task.id,
                    "role": task.config.get("role_id") if task.config else None,
                    "pending_question": None,
                    "created_at": task.created_at.isoformat(),
                })

            # Tasks waiting for input
            for task in self.scheduler.list_tasks(status=TaskStatus.WAITING_FOR_INPUT):
                sessions.append({
                    "task_id": task.id,
                    "status": "waiting_for_input",
                    "title": task.description or task.id,
                    "role": task.config.get("role_id") if task.config else None,
                    "pending_question": task.pending_question,
                    "created_at": task.created_at.isoformat(),
                })

            # Recently completed tasks that requested user attention (notify_user via event log)
            try:
                recent_events = self._event_log.get_recent(
                    types=["task_completed"], limit=20
                )
                notify_ids = {
                    e.get("data", {}).get("task_id")
                    for e in recent_events
                    if e.get("notify_user") and e.get("data", {}).get("task_id")
                }
                for task in self.scheduler.list_tasks(status=TaskStatus.COMPLETED, limit=50):
                    if task.id in notify_ids:
                        sessions.append({
                            "task_id": task.id,
                            "status": "completed",
                            "title": task.description or task.id,
                            "role": task.config.get("role_id") if task.config else None,
                            "pending_question": None,
                            "created_at": task.created_at.isoformat(),
                        })
            except Exception:
                pass

            if sessions:
                response["task_sessions"] = sessions
        except Exception:
            pass  # never let task_sessions errors break context

        # Audit summary — show recent external boundary crossings if any exist
        try:
            from app.mcp.adapters.audit_log import get as _audit_get
            recent = _audit_get(limit=10)
            if recent:
                by_tier = {}
                total_tokens = 0
                for r in recent:
                    t = r.get("tier", "unknown")
                    by_tier[t] = by_tier.get(t, 0) + 1
                    total_tokens += r.get("tokens_total", 0)
                response["audit_summary"] = {
                    "recent_external_calls": len(recent),
                    "calls_by_tier": by_tier,
                    "total_tokens": total_tokens,
                    "note": "Call audit_get() for full details.",
                }
        except Exception:
            pass  # never let audit errors break context

        return response

    async def _execute_search_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Targeted semantic search across selected memory tiers.

        types:
          conversations — working + active + archival memory (conversation history)
          documents     — knowledge base (docs added via add_documents)
        Omit types to search all.
        limit_per_type controls how many results come from each tier.
        """
        query = args.get("query", "")
        requested_types = args.get("types")  # None = all
        limit_per_type = min(int(args.get("limit_per_type", 5)), 20)
        role_id = args.get("role_id")  # optional: search role-private store

        if not query:
            return {"status": "error", "message": "query is required"}

        all_types = ["conversations", "documents"]
        if requested_types:
            search_types = [t for t in requested_types if t in all_types]
        else:
            search_types = all_types

        results: Dict[str, Any] = {}

        if "conversations" in search_types:
            try:
                # Generate embedding once for working + active searches
                embedding = self.memory_service.embedding.get_text_embedding(
                    query, prompt_name="query"
                )
                conv = []
                if embedding:
                    w = await self.memory_service._search_working_memory_async(embedding)
                    a = await self.memory_service._search_active_memory_async(embedding)
                    conv.extend(w + a)
                arch = await self.memory_service._search_archival_memory_async(
                    query, limit_per_type
                )
                conv.extend(arch)
                # Sort by relevance, cap at limit
                conv.sort(key=lambda x: float(x.get("relevance", 0)), reverse=True)
                results["conversations"] = conv[:limit_per_type]
            except Exception as e:
                results["conversations"] = []

        if "documents" in search_types:
            try:
                docs = await self.memory_service._search_knowledge_base_async(
                    query, limit_per_type, role_id=role_id
                )
                results["documents"] = docs[:limit_per_type]
            except Exception as e:
                results["documents"] = []

        total = sum(len(v) for v in results.values())
        return {
            "query": query,
            "types_searched": search_types,
            "results": results,
            "total": total,
        }

    async def _execute_add_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add conversation"""
        user_message = args.get("user_message", "")
        assistant_message = args.get("assistant_message", "")

        # Embedding generation + file writes are blocking (CPU-bound, up to several seconds).
        # Run them in a thread executor as a background task so the caller gets an immediate
        # response instead of waiting for all embedding models to finish.
        loop = asyncio.get_event_loop()

        async def _store() -> None:
            await loop.run_in_executor(None, self.memory_service.add_user_message, user_message)
            await loop.run_in_executor(
                None, self.memory_service.add_assistant_message, assistant_message
            )

        asyncio.create_task(_store())

        return {
            "status": "success",
            "message": "Conversation exchange queued for storage",
            "user_message_length": len(user_message),
            "assistant_message_length": len(assistant_message),
        }

    async def _execute_get_memory_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get memory statistics"""
        stats = self.memory_service.get_memory_stats()
        return stats

    async def _execute_add_documents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add documents with support for code metadata"""
        documents = args.get("documents", [])
        results = []

        for doc in documents:
            try:
                content = doc.get("content", "")
                metadata = doc.get("metadata", {})

                # Check if this is code metadata
                if metadata.get("type") == "code_metadata":
                    result = await self._process_code_metadata(content, metadata)
                    results.append(result)
                else:
                    # Regular document processing — route to role store if metadata.role is set
                    role_id = metadata.get("role")
                    self.memory_service.add_to_knowledge_base(content, metadata, role_id=role_id)
                    scope = f"role:{role_id}" if role_id else "shared"
                    results.append({"status": "success", "message": f"Document added [{scope}]"})

            except Exception as e:
                results.append({"status": "error", "message": str(e)})

        return {"results": results, "total_processed": len(documents)}

    async def _process_code_metadata(
        self, content: str, metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process code metadata document with git-aware features"""
        try:
            repo_name = metadata.get("repo")
            files = metadata.get("files", [])

            if not repo_name:
                return {
                    "status": "error",
                    "message": "Repository name required for code metadata",
                }

            # Validate git repository exists
            repos_result = self.git_service.list_repositories()
            if repos_result["status"] != "success":
                return {
                    "status": "error",
                    "message": "Failed to access git repositories",
                }

            repo_exists = any(
                repo["name"] == repo_name
                for repo in repos_result.get("repositories", [])
            )
            if not repo_exists:
                return {
                    "status": "warning",
                    "message": f"Repository '{repo_name}' not registered. Register it first with knowledge_add_repo.",
                }

            # Validate file hashes if provided
            validated_files = []
            for file_info in files:
                file_path = file_info.get("path")
                expected_hash = file_info.get("hash")

                if file_path and expected_hash:
                    # Get current file and check hash
                    file_result = self.git_service.get_file_content(
                        repo_name, file_path
                    )
                    if file_result["status"] == "success":
                        current_hash = file_result["metadata"]["git_hash"]
                        file_info["current_hash"] = current_hash
                        file_info["hash_match"] = current_hash == expected_hash
                        validated_files.append(file_info)

            # Update metadata with validated file info
            enhanced_metadata = metadata.copy()
            enhanced_metadata["validated_files"] = validated_files
            enhanced_metadata["git_aware"] = True
            enhanced_metadata["added_at"] = datetime.now().isoformat()

            # Add to knowledge base with enhanced metadata
            self.memory_service.add_to_knowledge_base(content, enhanced_metadata)

            return {
                "status": "success",
                "message": "Code metadata added with git validation",
                "git_info": {
                    "repo": repo_name,
                    "files_validated": len(validated_files),
                    "files_with_hash_mismatch": len(
                        [f for f in validated_files if not f.get("hash_match", True)]
                    ),
                },
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to process code metadata: {str(e)}",
            }

    async def _execute_end_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute end conversation"""
        self.memory_service.end_conversation()
        return {"status": "success", "message": "Conversation ended and archived"}

    async def _execute_toggle_multi_model(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute toggle multi model"""
        enabled = args.get("enabled", False)
        self.memory_service.multi_model_enabled = enabled
        return {"status": "success", "multi_model_enabled": enabled}

    async def _execute_list_recent_conversations(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute list recent conversations"""
        limit = args.get("limit", 10)
        conversations = self.memory_service.list_recent_conversations(limit)
        return {
            "conversations": conversations,
            "total": len(conversations),
            "message": f"Retrieved {len(conversations)} recent conversations",
        }

    async def _execute_remove_conversation_message(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute remove conversation message"""
        message_id = args.get("message_id", "")

        # Validate message_id
        if not message_id or not message_id.strip():
            return {
                "success": False,
                "message": "No conversation message ID was provided",
            }

        success = self.memory_service.remove_conversation_message(message_id)
        return {
            "success": success,
            "message": f"Conversation message {message_id} {'removed' if success else 'not found'}",
        }

    async def _execute_remove_recent_conversations(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute remove recent conversations"""
        count = args.get("count", 0)
        removed_count = self.memory_service.remove_recent_conversations(count)
        return {
            "removed_count": removed_count,
            "message": f"Removed {removed_count} recent conversations",
        }

    async def _execute_list_recent_documents(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute list recent documents"""
        limit = args.get("limit", 10)
        documents = self.memory_service.list_recent_documents(limit)
        return {
            "documents": documents,
            "total": len(documents),
            "message": f"Retrieved {len(documents)} recent documents",
        }

    async def _execute_remove_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute remove document"""
        document_id = args.get("document_id", "")
        success = self.memory_service.remove_document(document_id)
        return {
            "success": success,
            "message": f"Document {document_id} {'removed' if success else 'not found'}",
        }

    async def _execute_web_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute web search using Google Custom Search API"""
        query = args.get("query", "")
        max_results = args.get("limit", 10)

        try:
            # Import here to avoid dependency issues if not available
            import urllib.request
            import urllib.parse
            import json

            # Try Google Custom Search API first (if API key is available)
            google_api_key = self.config.get("google_api_key", "")
            search_engine_id = self.config.get("google_search_engine_id", "")

            if google_api_key and search_engine_id:
                try:
                    # Use Google Custom Search API
                    encoded_query = urllib.parse.quote(query)
                    url = f"https://www.googleapis.com/customsearch/v1?key={google_api_key}&cx={search_engine_id}&q={encoded_query}&num={min(max_results, 10)}"

                    req = urllib.request.Request(url)
                    req.add_header("User-Agent", "MoJoAssistant/1.0")

                    with urllib.request.urlopen(req, timeout=15) as response:
                        data = response.read().decode("utf-8")
                        search_result = json.loads(data)

                    # Parse Google results
                    results = []
                    if "items" in search_result:
                        for item in search_result["items"][:max_results]:
                            results.append(
                                {
                                    "title": item.get("title", ""),
                                    "content": item.get("snippet", ""),
                                    "url": item.get("link", ""),
                                    "source": "google",
                                }
                            )

                    return {
                        "query": query,
                        "results": results,
                        "total_results": len(results),
                        "source": "google_custom_search",
                        "timestamp": time.time(),
                    }

                except Exception as e:
                    # Fallback if Google API fails
                    return {
                        "query": query,
                        "error": f"Google Custom Search API failed: {str(e)}",
                        "results": [],
                        "timestamp": time.time(),
                    }
            else:
                return {
                    "query": query,
                    "error": "Google Custom Search API not configured",
                    "results": [],
                    "timestamp": time.time(),
                }

        except Exception as e:
            return {
                "query": query,
                "error": f"Web search failed: {str(e)}",
                "results": [],
                "timestamp": time.time(),
            }

    async def _execute_google_service(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute generic Google Workspace operation via gws CLI."""
        import json

        service = args.get("service")
        resource = args.get("resource")
        method = args.get("method")
        sub_resource = args.get("sub_resource")
        params = args.get("params")
        json_body = args.get("json_body")
        output_format = args.get("format", "json")
        api_version = args.get("api_version")
        page_all = bool(args.get("page_all", False))
        page_limit = args.get("page_limit")
        page_delay = args.get("page_delay")
        upload_path = args.get("upload_path")
        output_path = args.get("output_path")

        if not service or not resource or not method:
            return {
                "status": "error",
                "message": "Missing required arguments: service, resource, method",
            }

        allowed_services = {"calendar", "drive", "sheets", "gmail", "docs", "people"}
        if service not in allowed_services:
            return {
                "status": "error",
                "message": f"Service '{service}' not allowed. Allowed: {sorted(allowed_services)}",
            }

        cmd = ["gws", service, resource]
        if sub_resource:
            cmd.append(str(sub_resource))
        cmd.append(str(method))

        if params is not None:
            cmd.extend(["--params", json.dumps(params)])
        if json_body is not None:
            cmd.extend(["--json", json.dumps(json_body)])
        if upload_path:
            cmd.extend(["--upload", str(upload_path)])
        if output_path:
            cmd.extend(["--output", str(output_path)])
        if output_format:
            cmd.extend(["--format", str(output_format)])
        if api_version:
            cmd.extend(["--api-version", str(api_version)])
        if page_all:
            cmd.append("--page-all")
        if page_limit is not None:
            cmd.extend(["--page-limit", str(page_limit)])
        if page_delay is not None:
            cmd.extend(["--page-delay", str(page_delay)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_text = stdout.decode("utf-8", errors="ignore")
            stderr_text = stderr.decode("utf-8", errors="ignore")

            if proc.returncode != 0:
                return {
                    "status": "error",
                    "message": f"gws failed with exit code {proc.returncode}",
                    "service": service,
                    "resource": resource,
                    "method": method,
                    "stderr": stderr_text,
                    "stdout": stdout_text,
                }

            parsed = None
            if output_format == "json" and stdout_text.strip():
                try:
                    parsed = json.loads(stdout_text)
                except Exception:
                    parsed = None

            return {
                "status": "success",
                "service": service,
                "resource": resource,
                "method": method,
                "data": parsed if parsed is not None else stdout_text,
                "stderr": stderr_text,
                "output_path": output_path,
                "timestamp": time.time(),
            }
        except FileNotFoundError:
            return {"status": "error", "message": "gws CLI not found in PATH"}
        except Exception as e:
            return {"status": "error", "message": f"google_service failed: {str(e)}"}

    async def _execute_get_current_day(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get current day"""
        from datetime import datetime

        now = datetime.now()
        return {
            "date": now.strftime("%Y-%m-%d"),
            "day_of_week": now.strftime("%A"),
            "time": now.strftime("%H:%M:%S"),
            "year": now.year,
            "month": now.month,
            "day": now.day,
        }

    async def _execute_get_current_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get current time"""
        from datetime import datetime

        now = datetime.now()
        return {"time": now.strftime("%H:%M:%S"), "timezone": now.astimezone().tzname()}

    async def _execute_knowledge_add_repo(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute knowledge_add_repo"""
        repo_name = args.get("repo_name")
        repo_url = args.get("repo_url")
        ssh_key_path = args.get("ssh_key_path")
        branch = args.get("branch", "main")

        try:
            result = self.git_service.add_repository(
                repo_name, repo_url, ssh_key_path, branch
            )
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to add repository: {str(e)}"}

    async def _execute_knowledge_get_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute knowledge_get_file"""
        repo_name = args.get("repo_name")
        file_path = args.get("file_path")
        git_hash = args.get("git_hash")

        try:
            result = self.git_service.get_file_content(repo_name, file_path, git_hash)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get file content: {str(e)}",
            }

    async def _execute_knowledge_list_repos(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute knowledge_list_repos"""
        try:
            result = self.git_service.list_repositories()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list repositories: {str(e)}",
            }

    # ========================================================================
    # Unified Agent Manager execution methods
    # ========================================================================

    async def _execute_agent_list_types(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_list_types tool"""
        return {
            "status": "success",
            "agent_types": self.agent_registry.list_types(),
        }

    async def _execute_agent_start(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_start tool"""
        agent_type = args.get("agent_type")
        identifier = args.get("identifier")
        params = args.get("params") or {}

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.start_project(identifier, **params)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start {agent_type} agent: {str(e)}",
            }

    async def _execute_agent_stop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_stop tool"""
        agent_type = args.get("agent_type")
        identifier = args.get("identifier")

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.stop_project(identifier)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to stop {agent_type} agent: {str(e)}",
            }

    async def _execute_agent_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_status tool"""
        agent_type = args.get("agent_type")
        identifier = args.get("identifier")

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.get_status(identifier)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get {agent_type} agent status: {str(e)}",
            }

    async def _execute_agent_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_list tool"""
        agent_type = args.get("agent_type")

        try:
            if agent_type:
                manager = self.agent_registry.get_manager(agent_type)
                return await manager.list_projects()
            # No type — aggregate across all registered managers
            all_agents = []
            for atype, manager in self.agent_registry._managers.items():
                try:
                    result = await manager.list_projects()
                    projects = result.get("projects") or result.get("agents") or []
                    for p in projects:
                        if isinstance(p, dict):
                            p.setdefault("agent_type", atype)
                    all_agents.extend(projects)
                except Exception:
                    pass
            return {"status": "success", "agents": all_agents, "count": len(all_agents)}
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list agents: {str(e)}",
            }

    async def _execute_agent_restart(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_restart tool"""
        agent_type = args.get("agent_type")
        identifier = args.get("identifier")

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.restart_project(identifier)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to restart {agent_type} agent: {str(e)}",
            }

    async def _execute_agent_destroy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_destroy tool"""
        agent_type = args.get("agent_type")
        identifier = args.get("identifier")

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.destroy_project(identifier)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to destroy {agent_type} agent: {str(e)}",
            }

    async def _execute_agent_action(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent_action tool"""
        agent_type = args.get("agent_type")
        action = args.get("action")
        params = args.get("params") or {}

        try:
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.execute_action(action, params)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to execute {agent_type} action '{action}': {str(e)}",
            }

    # ========================================================================
    # Scheduler execution methods
    # ========================================================================

    async def _execute_scheduler_add_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_add_task tool"""
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
        from datetime import datetime

        try:
            task_id = args.get("task_id") or args.get("id")
            if not task_id:
                import uuid as _uuid
                task_id = str(_uuid.uuid4())[:8]
            task_type_str = args.get("task_type")
            schedule_str = args.get("schedule")
            cron_expression = args.get("cron_expression")
            priority_str = args.get("priority", "medium")
            config = args.get("config", {})
            description = args.get("description")
            resources_dict = args.get("resources", {})
            urgency = args.get("urgency")
            importance = args.get("importance")

            # Validate urgency / importance: must be int 1–5 if provided
            def _validate_routing_field(name: str, value):
                if value is None:
                    return None
                try:
                    v = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"'{name}' must be an integer, got {value!r}")
                if not (1 <= v <= 5):
                    raise ValueError(f"'{name}' must be between 1 and 5, got {v}")
                return v

            urgency = _validate_routing_field("urgency", urgency)
            importance = _validate_routing_field("importance", importance)

            # Convert strings to enums
            task_type = TaskType(task_type_str)
            priority = TaskPriority(priority_str)

            # Parse schedule
            schedule = None
            if schedule_str:
                schedule = datetime.fromisoformat(schedule_str)

            # §21 enforcement — role_id required for assistant tasks
            role_id = config.get("role_id") if isinstance(config, dict) else None
            if task_type_str == "assistant":
                inline_prompt = config.get("system_prompt") if isinstance(config, dict) else None
                if inline_prompt:
                    return {
                        "status": "error",
                        "message": (
                            "§21 violation: inline system_prompt is not allowed for assistant tasks. "
                            "Create a role with role_create and pass role_id instead. "
                            "Use role_list to see existing roles."
                        ),
                    }
                if not role_id:
                    return {
                        "status": "error",
                        "message": (
                            "§21 violation: role_id is required for assistant tasks. "
                            "Use role_list to see available roles, or role_create to make a new one."
                        ),
                    }

            # Setup-time ceiling: validate available_tools against role policy
            available_tools = config.get("available_tools", []) if isinstance(config, dict) else []
            if role_id and available_tools:
                from app.roles.role_manager import RoleManager
                from app.scheduler.policy_monitor import PolicyMonitor
                role = RoleManager().get(role_id)
                monitor = PolicyMonitor.from_role(role_id, role)
                violations = monitor.validate_available_tools(available_tools)
                if violations:
                    return {
                        "status": "error",
                        "message": "Task rejected: available_tools exceeds role policy ceiling",
                        "violations": violations,
                    }

            # Create task
            # max_iterations can come from config (hub shorthand) or resources dict
            if isinstance(config, dict) and "max_iterations" in config:
                resources_dict = dict(resources_dict) if isinstance(resources_dict, dict) else {}
                resources_dict.setdefault("max_iterations", config["max_iterations"])
            resources = (
                TaskResources.from_dict(resources_dict)
                if isinstance(resources_dict, dict)
                else TaskResources()
            )
            task = Task(
                id=task_id,
                type=task_type,
                schedule=schedule,
                cron_expression=cron_expression,
                priority=priority,
                config=config,
                resources=resources,
                description=description,
                created_by="user",
                urgency=urgency,
                importance=importance,
            )

            # Add to scheduler
            success = self.scheduler.add_task(task)

            if success:
                return {
                    "status": "success",
                    "message": f"Task {task_id} added to scheduler",
                    "task": task.to_dict(),
                }
            else:
                return {"status": "error", "message": f"Task {task_id} already exists"}

        except Exception as e:
            return {"status": "error", "message": f"Failed to add task: {str(e)}"}

    async def _execute_scheduler_list_tasks(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_list_tasks tool"""
        from app.scheduler.models import TaskStatus, TaskPriority

        try:
            # Parse filters
            status_filter = None
            if "status" in args:
                status_filter = TaskStatus(args["status"])

            priority_filter = None
            if "priority" in args:
                priority_filter = TaskPriority(args["priority"])

            limit = args.get("limit", 100)

            # Get tasks
            tasks = self.scheduler.list_tasks(
                status=status_filter, priority=priority_filter, limit=limit
            )

            # Convert to dict
            tasks_data = [task.to_dict() for task in tasks]

            return {"status": "success", "tasks": tasks_data, "total": len(tasks_data)}

        except Exception as e:
            return {"status": "error", "message": f"Failed to list tasks: {str(e)}"}

    async def _execute_scheduler_get_status(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_get_status tool"""
        try:
            status = self.scheduler.get_status()
            return {"status": "success", "scheduler": status}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get scheduler status: {str(e)}",
            }

    async def _execute_scheduler_get_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_get_task tool"""
        try:
            task_id = args.get("task_id")
            task = self.scheduler.get_task(task_id)

            if task:
                return {"status": "success", "task": task.to_dict()}
            else:
                return {"status": "error", "message": f"Task {task_id} not found"}

        except Exception as e:
            return {"status": "error", "message": f"Failed to get task: {str(e)}"}

    async def _execute_scheduler_remove_task(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_remove_task tool"""
        try:
            task_id = args.get("task_id")
            success = self.scheduler.remove_task(task_id)

            if success:
                return {
                    "status": "success",
                    "message": f"Task {task_id} removed from scheduler",
                }
            else:
                return {"status": "error", "message": f"Task {task_id} not found"}

        except Exception as e:
            return {"status": "error", "message": f"Failed to remove task: {str(e)}"}

    async def _execute_scheduler_purge_tasks(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Bulk remove all tasks matching a given status"""
        try:
            target_status = args.get("status")
            exclude_ids = set(args.get("exclude_ids") or [])

            all_tasks = self.scheduler.list_tasks()
            removed = []
            for task in all_tasks:
                if task.status.value == target_status and task.id not in exclude_ids:
                    self.scheduler.remove_task(task.id)
                    removed.append(task.id)

            return {
                "status": "success",
                "removed_count": len(removed),
                "removed_ids": removed,
                "message": f"Purged {len(removed)} {target_status} task(s)",
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to purge tasks: {str(e)}"}

    # ========================================================================
    # Scheduler Daemon Control execution methods
    # ========================================================================

    async def _execute_scheduler_start_daemon(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_start_daemon tool"""
        try:
            success = self._start_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon started",
                    "running": self.scheduler.running,
                    "tick_count": self.scheduler.tick_count,
                    "thread_alive": self.scheduler_thread.is_alive()
                    if self.scheduler_thread
                    else False,
                }
            else:
                return {
                    "status": "error",
                    "message": "Scheduler daemon is already running",
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start scheduler daemon: {str(e)}",
            }

    async def _execute_scheduler_stop_daemon(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_stop_daemon tool"""
        try:
            success = self._stop_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon stopped gracefully",
                    "running": self.scheduler.running,
                }
            else:
                return {
                    "status": "error",
                    "message": "Scheduler daemon was not running",
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to stop scheduler daemon: {str(e)}",
            }

    async def _execute_scheduler_restart_daemon(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_restart_daemon tool"""
        try:
            success = self._restart_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon restarted",
                    "running": self.scheduler.running,
                    "tick_count": self.scheduler.tick_count,
                    "thread_alive": self.scheduler_thread.is_alive()
                    if self.scheduler_thread
                    else False,
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to restart scheduler daemon",
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to restart scheduler daemon: {str(e)}",
            }

    async def _execute_scheduler_daemon_status(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_daemon_status tool"""
        try:
            thread_alive = (
                self.scheduler_thread.is_alive() if self.scheduler_thread else False
            )

            # Get scheduler statistics
            status = self.scheduler.get_status()

            return {
                "status": "success",
                "daemon": {
                    "running": self.scheduler.running,
                    "thread_alive": thread_alive,
                    "thread_name": self.scheduler_thread.name
                    if self.scheduler_thread
                    else None,
                },
                "scheduler": status,
                "message": f"Scheduler daemon is {'running' if thread_alive and self.scheduler.running else 'stopped'}",
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get scheduler daemon status: {str(e)}",
            }

    async def _execute_scheduler_list_assistant_tools(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return all tools available for assignment to agentic tasks."""
        try:
            from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

            registry = DynamicToolRegistry()
            tools = registry.list_tools()
            return {
                "status": "success",
                "tools": [
                    {
                        "name": name,
                        "description": meta.get("description", ""),
                        "danger_level": meta.get("danger_level", "low"),
                        "requires_auth": meta.get("requires_auth", False),
                    }
                    for name, meta in tools.items()
                ],
                "usage": "Pass desired tool names in available_tools when calling scheduler_add_task with task_type='agentic'.",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _execute_list_tools(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return tools from the catalog, optionally filtered by category."""
        try:
            from app.config.config_loader import load_layered_json_config
            from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

            catalog = load_layered_json_config("config/tool_catalog.json")
            catalog_entries = catalog.get("tools", {})
            categories_meta = catalog.get("categories", {})
            category_filter = args.get("category")

            registry = DynamicToolRegistry()
            registry_tools = registry.list_tools()

            result = []
            # Tools from catalog (with category metadata)
            for name, cat_entry in catalog_entries.items():
                if not isinstance(cat_entry, dict):
                    continue
                category = cat_entry.get("category", "unknown")
                if category_filter and category != category_filter:
                    continue
                registry_meta = registry_tools.get(name, {})
                result.append({
                    "name": name,
                    "description": cat_entry.get("description") or registry_meta.get("description", ""),
                    "danger_level": cat_entry.get("danger_level", registry_meta.get("danger_level", "low")),
                    "category": category,
                    "requires_auth": cat_entry.get("requires_auth", registry_meta.get("requires_auth", False)),
                    "always_injected": cat_entry.get("always_injected", False),
                })
            # Tools in registry but not yet in catalog
            if not category_filter:
                cataloged = set(catalog_entries.keys())
                for name, meta in registry_tools.items():
                    if name not in cataloged:
                        result.append({
                            "name": name,
                            "description": meta.get("description", ""),
                            "danger_level": meta.get("danger_level", "low"),
                            "category": "unknown",
                            "requires_auth": meta.get("requires_auth", False),
                            "always_injected": False,
                        })
            return {
                "status": "success",
                "tools": result,
                "categories": categories_meta,
                "usage": (
                    "Roles declare tool_access by category (e.g. [\"memory\", \"file\"]). "
                    "Pass explicit tool names in task config.available_tools to override."
                ),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ========================================================================
    # Dreaming Tool Executors
    # ========================================================================

    async def _execute_dreaming_process(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute dreaming_process tool"""
        try:
            conversation_id = args.get("conversation_id")
            conversation_text = args.get("conversation_text")
            quality_level = args.get("quality_level", "basic")
            metadata = args.get("metadata", {})

            # Store original text in metadata so upgrade_quality can re-process
            metadata["original_text"] = conversation_text

            # Initialize dreaming pipeline
            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(
                config_file=self.config.get("llm_config_path", "config/llm_config.json")
            )

            pipeline = DreamingPipeline(
                llm_interface=llm, quality_level=quality_level, logger=self.logger
            )

            # Process conversation
            results = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata=metadata,
            )

            if results.get("status") == "success":
                d_stage = results.get("stages", {}).get("D_archive", {})
                lifecycle = pipeline.get_archive_lifecycle(
                    conversation_id=conversation_id,
                    version=d_stage.get("version"),
                )
                return {
                    "status": "success",
                    "conversation_id": conversation_id,
                    "quality_level": quality_level,
                    "stages": results.get("stages", {}),
                    "version": d_stage.get("version"),
                    "lifecycle": lifecycle,
                    "message": f"Successfully processed conversation {conversation_id}",
                }
            else:
                return {
                    "status": "error",
                    "message": results.get("error", "Unknown error during processing"),
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Dreaming processing failed: {str(e)}",
            }

    async def _execute_dreaming_list_archives(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute dreaming_list_archives tool"""
        try:
            from pathlib import Path
            from dreaming.storage.json_backend import JsonFileBackend
            from app.config.paths import get_memory_subpath

            storage = JsonFileBackend(storage_path=Path(get_memory_subpath("dreams")))
            archives = storage.list_archives()

            return {
                "status": "success",
                "archives": archives,
                "count": len(archives),
                "message": f"Found {len(archives)} archived conversations",
            }

        except Exception as e:
            return {"status": "error", "message": f"Failed to list archives: {str(e)}"}

    async def _execute_dreaming_get_archive(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute dreaming_get_archive tool"""
        try:
            conversation_id = args.get("conversation_id")
            version = args.get("version")

            from pathlib import Path
            from dreaming.storage.json_backend import JsonFileBackend
            from app.config.paths import get_memory_subpath

            storage = JsonFileBackend(storage_path=Path(get_memory_subpath("dreams")))

            archive = storage.load_archive(
                conversation_id=conversation_id, version=version
            )

            if archive:
                manifest = storage.get_manifest(conversation_id=conversation_id)
                # Build lifecycle from manifest
                lifecycle = None
                if manifest:
                    av = version if version is not None else int(manifest.get("latest_version", 0))
                    lifecycle = manifest.get("versions", {}).get(str(av))
                    if lifecycle:
                        lifecycle = {"conversation_id": conversation_id, "version": av, **lifecycle}
                return {
                    "status": "success",
                    "archive": archive,
                    "lifecycle": lifecycle,
                    "latest_version": manifest.get("latest_version")
                    if manifest
                    else None,
                    "message": f"Retrieved archive for {conversation_id}",
                }
            else:
                return {
                    "status": "error",
                    "message": f"Archive not found for conversation {conversation_id}",
                }

        except Exception as e:
            return {"status": "error", "message": f"Failed to get archive: {str(e)}"}

    async def _execute_dreaming_upgrade_quality(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute dreaming_upgrade_quality tool"""
        try:
            conversation_id = args.get("conversation_id")
            target_quality = args.get("target_quality")

            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(
                config_file=self.config.get("llm_config_path", "config/llm_config.json")
            )

            pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level="basic",  # Will be upgraded
                logger=self.logger,
            )

            results = await pipeline.upgrade_quality(
                conversation_id=conversation_id, target_quality=target_quality
            )

            if results.get("status") == "success":
                d_stage = results.get("stages", {}).get("D_archive", {})
                lifecycle = pipeline.get_archive_lifecycle(
                    conversation_id=conversation_id,
                    version=d_stage.get("version"),
                )
                return {
                    "status": "success",
                    "conversation_id": conversation_id,
                    "upgraded_from": results.get("upgraded_from"),
                    "upgraded_to": results.get("upgraded_to"),
                    "stages": results.get("stages", {}),
                    "version": d_stage.get("version"),
                    "lifecycle": lifecycle,
                    "message": f"Successfully upgraded {conversation_id} to {target_quality}",
                }
            else:
                return {
                    "status": "error",
                    "message": results.get("error", "Unknown error during upgrade"),
                }

        except Exception as e:
            return {"status": "error", "message": f"Quality upgrade failed: {str(e)}"}

    # ========================================================================
    # Task Session Tools
    # ========================================================================

    async def _execute_task_session_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task_session_read tool"""
        try:
            from app.scheduler.session_storage import SessionStorage

            task_id = args.get("task_id")
            include_metadata = args.get("include_metadata", False)

            storage = SessionStorage()
            session = storage.load_session(task_id)

            if session is None:
                return {
                    "status": "error",
                    "message": f"No session found for task '{task_id}'",
                }

            # Format messages
            messages = []
            for msg in session.messages:
                entry = {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "iteration": msg.iteration,
                }
                if msg.tool_call_id:
                    entry["tool_call_id"] = msg.tool_call_id
                if msg.tool_name:
                    entry["tool_name"] = msg.tool_name
                if include_metadata and msg.metadata:
                    entry["metadata"] = msg.metadata
                messages.append(entry)

            return {
                "status": "success",
                "task_id": session.task_id,
                "session_status": session.status,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "final_answer": session.final_answer,
                "error_message": session.error_message,
                "message_count": len(messages),
                "messages": messages,
                "metadata": session.metadata,
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to read task session: {str(e)}",
            }

    async def _execute_scheduler_resume_task(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute scheduler_resume_task tool"""
        try:
            from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
            from app.scheduler.session_storage import SessionStorage

            task_id = args.get("task_id")
            max_additional = args.get("max_additional_iterations", 10)

            # Validate original task exists and is agentic
            original_task = self.scheduler.get_task(task_id)
            if original_task is None:
                return {"status": "error", "message": f"Task '{task_id}' not found"}

            if original_task.type != TaskType.ASSISTANT:
                return {
                    "status": "error",
                    "message": f"Task '{task_id}' is not an agentic assistant task (type: {original_task.type.value})",
                }

            if original_task.status.value not in ("failed", "completed"):
                # Also check session status for timed_out
                storage = SessionStorage()
                session = storage.load_session(task_id)
                if session is None or session.status not in ("failed", "timed_out"):
                    return {
                        "status": "error",
                        "message": f"Task '{task_id}' is not in a resumable state (status: {original_task.status.value})",
                    }

            # Verify session exists
            storage = SessionStorage()
            session = storage.load_session(task_id)
            if session is None:
                return {
                    "status": "error",
                    "message": f"No session found for task '{task_id}'",
                }

            # Create resume task
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            resume_task_id = f"{task_id}_resume_{timestamp}"

            original_config = original_task.config.copy()
            original_config["resume_from_task_id"] = task_id
            original_config["max_iterations"] = max_additional

            resume_task = Task(
                id=resume_task_id,
                type=TaskType.ASSISTANT,
                priority=original_task.priority,
                config=original_config,
                resources=original_task.resources,
                description=f"Resume of {task_id}",
                created_by="user",
            )

            success = self.scheduler.add_task(resume_task)
            if success:
                return {
                    "status": "success",
                    "message": f"Resume task '{resume_task_id}' created",
                    "resume_task_id": resume_task_id,
                    "original_task_id": task_id,
                    "max_iterations": max_additional,
                }
            else:
                return {"status": "error", "message": f"Failed to create resume task"}

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to resume task: {str(e)}",
            }

    async def _execute_reply_to_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute reply_to_task tool — resume a WAITING_FOR_INPUT task with the user's answer."""
        task_id = args.get("task_id", "").strip()
        reply = args.get("reply", "").strip()
        if not task_id:
            return {"status": "error", "message": "task_id is required"}
        if not reply:
            return {"status": "error", "message": "reply is required"}

        if not self.scheduler:
            return {"status": "error", "message": "Scheduler not available"}

        result = self.scheduler.resume_task_with_reply(task_id, reply)
        if result.get("success"):
            return {
                "status": "success",
                "message": f"Task '{task_id}' resumed — agent will continue with your reply",
                "task_id": task_id,
            }
        return {"status": "error", "message": result.get("error", "Unknown error")}

    # ========================================================================
    # Resource Pool Tools
    # ========================================================================

    def _get_resource_manager(self):
        """Get the ResourceManager from the scheduler's executor, lazy-initializing if needed."""
        return self.scheduler.executor._get_resource_manager()

    async def _execute_get_recent_events(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return recent events from the persistent event log."""
        since = args.get("since_timestamp")
        types = args.get("types")
        limit = min(int(args.get("limit", 50)), 500)
        include_data = bool(args.get("include_data", False))

        events = self._event_log.get_recent(
            since=since,
            types=types,
            limit=limit,
            include_data=include_data,
        )
        return {
            "status": "success",
            "count": len(events),
            "events": events,
            "latest_timestamp": events[-1]["timestamp"] if events else None,
        }

    async def _execute_get_attention_summary(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Return a grouped attention summary bucketed by urgency level.

        Reads events from the persistent event log filtered by hitl_level,
        groups them into blocking / alerts / digest buckets, and returns
        a token-compact representation the MCP client LLM can act on.
        """
        from datetime import datetime, timedelta

        since = args.get("since")
        min_level = int(args.get("min_level", 1))

        # Default window: last 24 hours
        if not since:
            since = (datetime.now() - timedelta(hours=24)).isoformat()

        # Pull all events with data (needed for task_id in blocking items)
        all_events = self._event_log.get_recent(
            since=since,
            limit=500,
            include_data=True,
        )

        blocking = []   # level 4-5
        alerts = []     # level 3
        digest = []     # level 1-2
        noise_count = 0

        for e in all_events:
            level = e.get("hitl_level", 0)
            if level == 0:
                noise_count += 1
                continue
            if level < min_level:
                continue

            event_type = e.get("event_type", "")
            data = e.get("data") or {}
            blurb = e.get("title") or event_type

            # Determine source label
            source = data.get("created_by") or data.get("agent_id") or (
                "scheduler" if "task" in event_type else "system"
            )

            item: Dict[str, Any] = {
                "id": e.get("id"),
                "level": level,
                "from": source,
                "blurb": blurb,
                "created_at": e.get("timestamp"),
            }

            # For waiting_for_input events, attach reply guidance — but skip if
            # the task is no longer actually waiting (completed/failed/cancelled).
            if event_type == "task_waiting_for_input":
                task_id = data.get("task_id")
                if task_id:
                    try:
                        from app.scheduler.models import TaskStatus
                        task = self.scheduler.get_task(task_id)
                        if task and task.status != TaskStatus.WAITING_FOR_INPUT:
                            continue  # task resolved — drop stale blocking item
                    except Exception:
                        pass  # can't check status → show the item to be safe
                    item["reply_with"] = "reply_to_task"
                    item["task_id"] = task_id
                question = data.get("question") or data.get("pending_question")
                if question:
                    item["blurb"] = f"Waiting: {question}"

            if level >= 4:
                blocking.append(item)
            elif level == 3:
                alerts.append(item)
            else:
                digest.append(item)

        # Cap digest at 10 items (keep newest)
        digest = digest[-10:]

        # Cursor = latest event timestamp in the returned set
        all_returned = blocking + alerts + digest
        cursor = max(
            (e["created_at"] for e in all_returned if e.get("created_at")),
            default=since,
        )

        return {
            "status": "success",
            "blocking": blocking,
            "alerts": alerts,
            "digest": digest,
            "digest_count": len(digest),
            "noise_count": noise_count,
            "cursor": cursor,
        }

    async def _execute_config_doctor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run the config doctor and return a structured validation report."""
        import asyncio
        try:
            from app.config.doctor import ConfigDoctor
            doctor = ConfigDoctor()

            # Run in executor so blocking I/O (URL probes) doesn't stall the event loop
            loop = asyncio.get_event_loop()
            report = await loop.run_in_executor(None, doctor.run_all_checks)
            data = report.to_dict()
            data["status_label"] = {
                "pass": "All checks passed",
                "warn": "Warnings found — some features may be degraded",
                "error": "Errors found — tasks will likely fail at runtime",
            }.get(data["status"], data["status"])
            return data
        except Exception as e:
            return {"status": "error", "message": f"Config doctor failed: {e}"}

    async def _execute_audit_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return audit records of external boundary crossings."""
        try:
            from app.mcp.adapters.audit_log import get as _audit_get
            task_id = args.get("task_id")
            limit = int(args.get("limit", 50))
            records = _audit_get(task_id=task_id, limit=limit)

            # Summarise token totals
            total_tokens = sum(r.get("tokens_total", 0) for r in records)
            by_tier = {}
            for r in records:
                t = r.get("tier", "unknown")
                by_tier[t] = by_tier.get(t, 0) + 1

            return {
                "status": "success",
                "filter_task_id": task_id,
                "record_count": len(records),
                "total_tokens": total_tokens,
                "calls_by_tier": by_tier,
                "records": records,
            }
        except Exception as e:
            return {"status": "error", "message": f"audit_get failed: {e}"}

    async def _execute_resource_pool_status(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute resource_pool_status tool"""
        try:
            rm = self._get_resource_manager()
            status = rm.get_status()
            # Annotate each resource with its agentic_capable flag if tested
            for res_id, info in status.items():
                capable = rm.get_agentic_capable(res_id)
                info["agentic_capable"] = capable  # None = not yet tested
            return {
                "status": "success",
                "resources": status,
                "count": len(status),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get resource pool status: {str(e)}",
            }

    async def _execute_resource_pool_approve(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute resource_pool_approve tool"""
        try:
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Missing resource_id"}

            rm = self._get_resource_manager()

            # Verify resource exists
            if resource_id not in rm._resources:
                return {
                    "status": "error",
                    "message": f"Resource '{resource_id}' not found. Use resource_pool_status to see available resources.",
                }

            rm.approve_paid_resource(resource_id)
            asyncio.create_task(self._sse_notifier.broadcast({
                "event_type": "resource_event",
                "severity": "info",
                "title": f"Resource '{resource_id}' approved",
                "data": {"resource_id": resource_id, "action": "approved"},
            }))
            return {
                "status": "success",
                "message": f"Paid resource '{resource_id}' approved for agentic use",
                "resource_id": resource_id,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to approve resource: {str(e)}",
            }

    async def _execute_resource_pool_revoke(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute resource_pool_revoke tool"""
        try:
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Missing resource_id"}

            rm = self._get_resource_manager()
            rm.revoke_paid_resource(resource_id)
            asyncio.create_task(self._sse_notifier.broadcast({
                "event_type": "resource_event",
                "severity": "warning",
                "title": f"Resource '{resource_id}' revoked",
                "data": {"resource_id": resource_id, "action": "revoked"},
            }))
            return {
                "status": "success",
                "message": f"Paid resource '{resource_id}' approval revoked",
                "resource_id": resource_id,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to revoke resource: {str(e)}",
            }

    async def _execute_resource_pool_smoke_test(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run the agentic smoke test on a specific resource."""
        resource_id = args.get("resource_id", "").strip()
        full = bool(args.get("full", False))
        if not resource_id:
            return {"status": "error", "message": "resource_id is required"}

        try:
            from app.scheduler.agentic_smoke_test import AgenticSmokeTest
            tester = AgenticSmokeTest()
            result = await tester.run(resource_id=resource_id, full=full)

            # Persist agentic_capable flag to ResourceManager
            try:
                from app.scheduler.resource_pool import ResourceManager
                rm = ResourceManager()
                rm.set_agentic_capable(resource_id, result.agentic_capable)
            except Exception:
                pass

            data = result.to_dict()
            data["status"] = "success"
            return data
        except Exception as e:
            return {"status": "error", "message": f"Smoke test failed: {e}"}

    # ── Role System Tools ────────────────────────────────────────────

    async def _execute_role_design_start(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Start a new role design session."""
        from app.roles.role_designer import RoleDesignSession
        session = RoleDesignSession()
        session.save()
        return {
            "session_id": session.session_id,
            "step": session.current_step,
            "question": session.current_question(),
            "progress": session.progress(),
        }

    async def _execute_role_design_answer(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an answer to the current role design step."""
        from app.roles.role_designer import RoleDesignSession
        session_id = args.get("session_id")
        answer = args.get("answer", "")
        if not session_id:
            return {"status": "error", "message": "Missing session_id"}
        session = RoleDesignSession.load(session_id)
        if session is None:
            return {"status": "error", "message": f"Session '{session_id}' not found"}
        next_step, payload = session.submit_answer(answer)
        result = {
            "session_id": session_id,
            "step": next_step,
            "progress": session.progress(),
        }
        result.update(payload)
        return result

    async def _execute_role_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Save a role config (from a design session or provided directly)."""
        from app.roles.role_designer import RoleDesignSession
        session_id = args.get("session_id")
        role_data = args.get("role")

        if session_id and not role_data:
            session = RoleDesignSession.load(session_id)
            if session is None:
                return {"status": "error", "message": f"Session '{session_id}' not found"}
            role_data = session._build_role_spec()

        if not role_data:
            return {"status": "error", "message": "Provide session_id or role data"}

        # Apply optional overrides
        if args.get("model_preference") is not None:
            role_data["model_preference"] = args["model_preference"]
        if args.get("tools") is not None:
            role_data["tools"] = args["tools"]
        if args.get("notify_on_completion") is not None:
            role_data["notify_on_completion"] = args["notify_on_completion"]
        if args.get("policy") is not None:
            role_data["policy"] = args["policy"]

        path = self._role_manager.save(role_data)
        return {
            "status": "success",
            "role_id": role_data.get("id"),
            "name": role_data.get("name"),
            "nine_chapter_score": role_data.get("nine_chapter_score"),
            "path": path,
        }

    async def _execute_role_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all saved roles."""
        roles = self._role_manager.list_roles()
        return {"roles": roles, "count": len(roles)}

    async def _execute_role_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get a role config by ID."""
        role_id = args.get("role_id")
        if not role_id:
            return {"status": "error", "message": "Missing role_id"}
        role = self._role_manager.get(role_id)
        if role is None:
            return {"status": "error", "message": f"Role '{role_id}' not found"}
        return role

    # ── LLM Configuration Tools ──────────────────────────────────────

    # ========================================================================
    # Generic Config Tool
    # ========================================================================

    def _load_config_file(self, path: str) -> Dict[str, Any]:
        """Load a JSON config file from disk"""
        import json

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config_file(self, path: str, data: Dict[str, Any]) -> None:
        """Save a JSON config file to disk"""
        import json

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def _resolve_path(self, config: Dict[str, Any], path: str) -> Any:
        """Navigate dot-notation path into a nested dict. Raises KeyError on miss."""
        current = config
        for key in path.split("."):
            if isinstance(current, dict):
                current = current[key]
            else:
                raise KeyError(key)
        return current

    def _set_path(self, config: Dict[str, Any], path: str, value: Any) -> None:
        """Set a value at a dot-notation path, creating intermediate dicts as needed."""
        keys = path.split(".")
        current = config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def _matches_sensitive(self, path: str, patterns: List[str]) -> bool:
        """Check if a dot-path matches any sensitive key pattern (supports * wildcards)."""
        import fnmatch

        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    def _redact_sensitive(
        self, config: Any, sensitive_keys: List[str], prefix: str = ""
    ) -> Any:
        """Deep-copy config with sensitive values redacted."""
        if isinstance(config, dict):
            result = {}
            for k, v in config.items():
                full_path = f"{prefix}.{k}" if prefix else k
                if self._matches_sensitive(full_path, sensitive_keys):
                    result[k] = "***REDACTED***" if isinstance(v, str) else v
                else:
                    result[k] = self._redact_sensitive(v, sensitive_keys, full_path)
            return result
        elif isinstance(config, list):
            return [
                self._redact_sensitive(item, sensitive_keys, prefix) for item in config
            ]
        return config

    def _on_llm_config_change(self) -> None:
        """Hook called after LLM config is modified — resets pipeline and reloads resource manager."""
        try:
            if hasattr(self, "scheduler") and hasattr(self.scheduler, "executor"):
                self.scheduler.executor.reset_pipeline()
        except Exception:
            pass  # non-critical
        self._on_resource_pool_config_change()

    def _on_resource_pool_config_change(self) -> None:
        """Hook called after resource pool config is modified — reloads resource manager."""
        try:
            if hasattr(self, "scheduler") and hasattr(self.scheduler, "executor"):
                executor = self.scheduler.executor
                if (
                    hasattr(executor, "_resource_manager")
                    and executor._resource_manager
                ):
                    executor._resource_manager.reload_config()
        except Exception:
            pass  # non-critical

    def _on_tool_catalog_change(self) -> None:
        """Hook called after tool_catalog config is modified — no in-memory state to reload."""
        pass  # tool_catalog.json is read on each tool-resolution call; no cache to invalidate

    def _on_agentic_tools_change(self) -> None:
        """Hook called after agentic_tools config is modified — reloads tool registry."""
        try:
            if hasattr(self, "scheduler") and hasattr(self.scheduler, "executor"):
                executor = self.scheduler.executor
                if hasattr(executor, "_tool_registry") and executor._tool_registry:
                    from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

                    executor._tool_registry = DynamicToolRegistry()
                    executor._tool_registry.set_memory_service(self.memory_service)
                    self.logger.info("Agentic tools config reloaded")
        except Exception:
            pass  # non-critical

    def _on_agentic_prompts_change(self) -> None:
        """Hook called after agentic_prompts config is modified — reloads prompt manager."""
        try:
            if hasattr(self, "scheduler") and hasattr(self.scheduler, "executor"):
                executor = self.scheduler.executor
                if (
                    hasattr(executor, "_planning_manager")
                    and executor._planning_manager
                ):
                    from app.scheduler.planning_prompt_manager import (
                        PlanningPromptManager,
                    )

                    executor._planning_manager = PlanningPromptManager()
                    self.logger.info("Agentic prompts config reloaded")
        except Exception:
            pass  # non-critical

    def _on_scheduler_config_change(self) -> None:
        """Hook called after scheduler config is modified — reseeds default tasks."""
        try:
            if hasattr(self, "scheduler"):
                self.scheduler.reseed_default_tasks()
        except Exception:
            pass  # non-critical

    def _on_notifications_config_change(self) -> None:
        """Hook called after notifications config is modified — reloads all push adapters."""
        try:
            if hasattr(self, "_push_manager"):
                self._push_manager.reload()
        except Exception:
            pass  # non-critical

    async def _execute_config(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch config actions: help, get, set."""
        action = args.get("action")
        module_name = args.get("module")

        # --- sync_local_models ---
        if action == "sync_local_models":
            resource_id = args.get("path") or module_name or "lmstudio"
            try:
                rm = self.scheduler.executor._resource_manager
                synced = rm.sync_local_server_models(resource_id)
                statuses = rm.get_status()
                entries = {rid: statuses[rid] for rid in synced if rid in statuses}
                return {
                    "status": "success",
                    "server": resource_id,
                    "synced_count": len(synced),
                    "entries": entries,
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # --- resource pool actions ---
        if action == "resource_status":
            return await self._execute_resource_pool_status({})
        if action == "resource_approve":
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Parameter 'resource_id' is required."}
            return await self._execute_resource_pool_approve({"resource_id": resource_id})
        if action == "resource_revoke":
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Parameter 'resource_id' is required."}
            return await self._execute_resource_pool_revoke({"resource_id": resource_id})
        if action == "resource_smoke_test":
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Parameter 'resource_id' is required."}
            return await self._execute_resource_pool_smoke_test({"resource_id": resource_id})
        if action == "llm_models":
            resource_id = args.get("resource_id")
            if not resource_id:
                return {"status": "error", "message": "Parameter 'resource_id' is required."}
            return await self._execute_llm_list_available_models({"resource_id": resource_id})

        # --- doctor ---
        if action == "doctor":
            return await self._execute_config_doctor({})

        # --- role management ---
        if action == "role_list":
            return await self._execute_role_list({})
        if action == "role_get":
            role_id = args.get("role_id")
            if not role_id:
                return {"status": "error", "message": "Parameter 'role_id' is required."}
            return await self._execute_role_get({"role_id": role_id})
        if action == "role_create":
            return await self._execute_role_create(args)
        if action == "role_design_start":
            return await self._execute_role_design_start({})
        if action == "role_design_answer":
            return await self._execute_role_design_answer({
                "session_id": args.get("session_id"),
                "answer": args.get("answer"),
            })

        # --- modules list ---
        if action == "modules":
            modules = {}
            for name, meta in self._config_modules.items():
                modules[name] = {
                    "description": meta["description"],
                    "file": meta["file"],
                }
            return {"status": "success", "modules": modules}

        # --- help ---
        if action == "help" or not action:
            if not module_name:
                # List all modules
                modules = {}
                for name, meta in self._config_modules.items():
                    modules[name] = {
                        "description": meta["description"],
                        "file": meta["file"],
                    }
                return {
                    "status": "success",
                    "modules": modules,
                    "actions": {
                        "get":                   "Read config — params: module, path?",
                        "set":                   "Write config — params: module, path, value",
                        "list":                  "Show config structure — params: module",
                        "delete":                "Remove config key — params: module, path",
                        "validate":              "Validate config — params: module",
                        "modules":               "List all config modules",
                        "sync_local_models":     "Sync models from local server — params: resource_id",
                        "resource_status":       "All resources + approval state",
                        "resource_approve":      "Approve a resource — params: resource_id",
                        "resource_revoke":       "Revoke a resource — params: resource_id",
                        "resource_smoke_test":   "Test resource connectivity — params: resource_id",
                        "llm_models":            "List live models from server — params: resource_id",
                        "doctor":                "Full config pre-flight report",
                        "role_list":             "List all roles",
                        "role_get":              "Get role details — params: role_id",
                        "role_create":           "Create a role — params: role_id, system_prompt, model_preference, ...",
                        "role_design_start":     "Guided role design (Nine Chapter Q1)",
                        "role_design_answer":    "Next design question — params: session_id, answer",
                    },
                    "example": 'config(action="resource_status")',
                }
            # Show specific module structure
            if module_name not in self._config_modules:
                return {
                    "status": "error",
                    "message": f"Unknown module '{module_name}'. Available: {list(self._config_modules.keys())}",
                }
            meta = self._config_modules[module_name]
            try:
                data = self._load_config_file(meta["file"])
                redacted = self._redact_sensitive(data, meta.get("sensitive_keys", []))
                return {
                    "status": "success",
                    "module": module_name,
                    "description": meta["description"],
                    "file": meta["file"],
                    "current_config": redacted,
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to load config: {e}"}

        # --- get / set require a module ---
        if not module_name:
            return {
                "status": "error",
                "message": "Parameter 'module' is required for get/set actions.",
            }
        if module_name not in self._config_modules:
            return {
                "status": "error",
                "message": f"Unknown module '{module_name}'. Available: {list(self._config_modules.keys())}",
            }
        meta = self._config_modules[module_name]

        # --- get ---
        if action == "get":
            try:
                from app.config.config_loader import load_layered_json_config
                data = load_layered_json_config(meta["file"])
                path = args.get("path")
                if path:
                    try:
                        value = self._resolve_path(data, path)
                        # Redact if the path itself is sensitive
                        if self._matches_sensitive(
                            path, meta.get("sensitive_keys", [])
                        ):
                            value = "***REDACTED***"
                        return {
                            "status": "success",
                            "module": module_name,
                            "path": path,
                            "value": value,
                        }
                    except KeyError:
                        return {
                            "status": "error",
                            "message": f"Path '{path}' not found in {module_name} config.",
                        }
                else:
                    redacted = self._redact_sensitive(
                        data, meta.get("sensitive_keys", [])
                    )
                    return {
                        "status": "success",
                        "module": module_name,
                        "config": redacted,
                    }
            except Exception as e:
                return {"status": "error", "message": f"Failed to load config: {e}"}

        # --- set ---
        if action == "set":
            path = args.get("path")
            if not path:
                return {
                    "status": "error",
                    "message": "Parameter 'path' is required for action=set.",
                }
            if "value" not in args:
                return {
                    "status": "error",
                    "message": "Parameter 'value' is required for action=set.",
                }
            value = args["value"]
            validate = args.get("validate", True)

            try:
                from app.config.config_loader import (
                    load_layered_json_config,
                    load_runtime_layer,
                    save_runtime_config,
                )

                # Read merged config for old_value + validation context
                merged = load_layered_json_config(meta["file"])
                try:
                    old_value = self._resolve_path(merged, path)
                except KeyError:
                    old_value = None

                # Smart validation: LLM model changes on openai-compatible providers
                if module_name == "llm" and validate and _is_llm_model_path(path):
                    parts = path.split(".")
                    if len(parts) >= 2:
                        interface_name = parts[1]
                        iface = merged.get("api_models", {}).get(interface_name, {})
                        if iface.get("provider") == "openai":
                            result = await self._validate_model_available(
                                base_url=iface["base_url"],
                                model=value,
                                api_key=iface.get("api_key"),
                            )
                            if result["error"]:
                                return {
                                    "status": "error",
                                    "message": f"Validation failed: {result['error']}",
                                }
                            if not result["available"]:
                                return {
                                    "status": "error",
                                    "message": f"Model '{value}' is not loaded in the server.",
                                    "available_models": result["models"],
                                }

                # Apply change to runtime layer only (never touch codebase default)
                runtime_data = load_runtime_layer(meta["file"])
                self._set_path(runtime_data, path, value)
                runtime_path = save_runtime_config(meta["file"], runtime_data)

                # Fire change hook
                if meta.get("on_change"):
                    meta["on_change"]()

                # Broadcast config_changed event
                asyncio.create_task(self._sse_notifier.broadcast({
                    "event_type": "config_changed",
                    "module": module_name,
                    "path": path,
                    "old_value": old_value,
                    "new_value": value,
                    "severity": "info",
                    "title": f"Config {module_name}.{path} updated",
                }))

                return {
                    "status": "success",
                    "module": module_name,
                    "path": path,
                    "old_value": old_value,
                    "new_value": value,
                    "saved_to": runtime_path,
                    "message": f"Updated {module_name}.{path}: {old_value!r} -> {value!r} (runtime layer)",
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to set config: {e}"}

        if action == "delete":
            path = args.get("path")
            if not path:
                return {
                    "status": "error",
                    "message": "Parameter 'path' is required for action=delete.",
                }
            try:
                from app.config.config_loader import (
                    load_layered_json_config,
                    load_runtime_layer,
                    save_runtime_config,
                )

                merged = load_layered_json_config(meta["file"])
                try:
                    old_value = self._resolve_path(merged, path)
                except KeyError:
                    return {
                        "status": "error",
                        "message": f"Path '{path}' not found in config.",
                    }

                # Delete from runtime layer only
                runtime_data = load_runtime_layer(meta["file"])
                parts = path.split(".")
                target = runtime_data
                for part in parts[:-1]:
                    if part not in target:
                        return {
                            "status": "error",
                            "message": f"Path '{path}' not found in runtime layer — nothing to delete.",
                        }
                    target = target[part]
                key = parts[-1]
                if key not in target:
                    return {
                        "status": "error",
                        "message": f"Key '{key}' not found in runtime layer at '{'.'.join(parts[:-1])}' — nothing to delete.",
                    }
                del target[key]
                runtime_path = save_runtime_config(meta["file"], runtime_data)

                if meta.get("on_change"):
                    meta["on_change"]()

                # Broadcast config_changed event
                asyncio.create_task(self._sse_notifier.broadcast({
                    "event_type": "config_changed",
                    "module": module_name,
                    "path": path,
                    "action": "delete",
                    "old_value": old_value,
                    "severity": "info",
                    "title": f"Config {module_name}.{path} deleted",
                }))

                return {
                    "status": "success",
                    "module": module_name,
                    "path": path,
                    "deleted_value": old_value,
                    "saved_to": runtime_path,
                    "message": f"Deleted {module_name}.{path} from runtime layer",
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to delete config: {e}"}

        return {
            "status": "error",
            "message": f"Unknown action '{action}'. Use: help, get, set, delete.",
        }

    # ========================================================================
    # LLM Server Discovery (kept separate — queries external service)
    # ========================================================================

    async def _validate_model_available(
        self, base_url: str, model: str, api_key: str | None = None
    ) -> Dict[str, Any]:
        """Query an OpenAI-compatible /models endpoint to check if a model is loaded.

        Returns dict with keys: available (bool), models (list of model IDs), error (str|None)
        """
        import json as _json
        import urllib.request
        import urllib.error

        url = f"{base_url.rstrip('/')}/models"
        req = urllib.request.Request(url, method="GET")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        def _fetch():
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        return {
                            "available": False,
                            "models": [],
                            "error": f"Server returned HTTP {resp.status}",
                        }
                    data = _json.loads(resp.read().decode())
                    model_ids = [m.get("id", "") for m in data.get("data", [])]
                    return {
                        "available": model in model_ids,
                        "models": model_ids,
                        "error": None,
                    }
            except Exception as e:
                return {
                    "available": False,
                    "models": [],
                    "error": f"Failed to query models endpoint: {e}",
                }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def _execute_llm_list_available_models(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """List models available in an OpenAI-compatible server"""
        try:
            from app.config.config_loader import load_layered_json_config
            llm_config = load_layered_json_config(self._config_modules["llm"]["file"])
            interface_name = args.get("interface_name") or llm_config.get(
                "default_interface"
            )
            api_models = llm_config.get("api_models", {})

            if interface_name not in api_models:
                return {
                    "status": "error",
                    "message": f"Interface '{interface_name}' not found. Available: {list(api_models.keys())}",
                }

            iface = api_models[interface_name]
            openai_compatible_providers = {"openai", "openai-compatible", "local_api", "deepseek", "groq", "deepinfra", "xai", "lmstudio"}
            if iface.get("provider") not in openai_compatible_providers and not iface.get("base_url"):
                return {
                    "status": "error",
                    "message": f"Interface '{interface_name}' uses provider '{iface.get('provider')}', which does not support OpenAI-compatible model listing.",
                }

            result = await self._validate_model_available(
                base_url=iface["base_url"],
                model="",  # not checking a specific model
                api_key=iface.get("api_key"),
            )
            if result["error"]:
                return {"status": "error", "message": result["error"]}

            return {
                "status": "success",
                "interface": interface_name,
                "base_url": iface["base_url"],
                "models": result["models"],
                "count": len(result["models"]),
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to list models: {e}"}

    # ========================================================================
    # Hub Dispatchers
    # ========================================================================

    async def _execute_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Memory management hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "memory",
            "actions": {
                "end_conversation": "Archive current conversation topic",
                "list_conversations": "Recent conversation history — params: limit?",
                "remove_conversation": "Delete a conversation message — params: id",
                "remove_conversations": "Bulk delete recent conversations — params: count",
                "add_documents": "Add reference material — params: documents",
                "list_documents": "Recent documents — params: limit?",
                "remove_document": "Delete a document — params: id",
                "stats": "Memory tier statistics",
                "toggle_multi_model": "Switch embedding mode — params: enabled",
            },
            "example": 'memory(action="list_conversations", limit=5)',
        }

        if not action or action == "help":
            return HELP

        if action == "end_conversation":
            return await self._execute_end_conversation({})
        elif action == "list_conversations":
            return await self._execute_list_recent_conversations({"limit": args.get("limit", 10)})
        elif action == "remove_conversation":
            id_ = args.get("id")
            if not id_:
                return {"status": "error", "message": "Parameter 'id' is required."}
            return await self._execute_remove_conversation_message({"message_id": id_})
        elif action == "remove_conversations":
            count = args.get("count")
            if not count:
                return {"status": "error", "message": "Parameter 'count' is required."}
            return await self._execute_remove_recent_conversations({"count": count})
        elif action == "add_documents":
            docs = args.get("documents")
            if not docs:
                return {"status": "error", "message": "Parameter 'documents' is required."}
            return await self._execute_add_documents({"documents": docs})
        elif action == "list_documents":
            return await self._execute_list_recent_documents({"limit": args.get("limit", 10)})
        elif action == "remove_document":
            id_ = args.get("id")
            if not id_:
                return {"status": "error", "message": "Parameter 'id' is required."}
            return await self._execute_remove_document({"document_id": id_})
        elif action == "stats":
            return await self._execute_get_memory_stats({})
        elif action == "toggle_multi_model":
            enabled = args.get("enabled")
            if enabled is None:
                return {"status": "error", "message": "Parameter 'enabled' is required."}
            return await self._execute_toggle_multi_model({"enabled": enabled})
        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_knowledge(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Knowledge hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "knowledge",
            "actions": {
                "list_repos": "List registered repos",
                "add_repo": "Register a repo — params: name, url, ssh_key_path, branch?",
                "get_file": "Read file from repo — params: repo, path, git_hash?",
            },
            "example": 'knowledge(action="list_repos")',
        }

        if not action or action == "help":
            return HELP

        if action == "list_repos":
            return await self._execute_knowledge_list_repos({})
        elif action == "add_repo":
            for param in ("name", "url", "ssh_key_path"):
                if not args.get(param):
                    return {"status": "error", "message": f"Parameter '{param}' is required."}
            return await self._execute_knowledge_add_repo({
                "repo_name": args["name"],
                "repo_url": args["url"],
                "ssh_key_path": args["ssh_key_path"],
                "branch": args.get("branch", "main"),
            })
        elif action == "get_file":
            for param in ("repo", "path"):
                if not args.get(param):
                    return {"status": "error", "message": f"Parameter '{param}' is required."}
            return await self._execute_knowledge_get_file({
                "repo_name": args["repo"],
                "file_path": args["path"],
                "git_hash": args.get("git_hash"),
            })
        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_scheduler_hub(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Scheduler hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "scheduler",
            "actions": {
                "add":            "Schedule a task — params: task_id, type, goal, cron?, priority?, role_id?, ...",
                "list":           "List tasks — params: status?, priority?, limit?",
                "get":            "Task detail — params: task_id",
                "remove":         "Remove a task — params: task_id",
                "purge":          "Bulk remove old tasks — params: before_date?",
                "status":         "Daemon + queue stats",
                "daemon_start":   "Start the scheduler daemon",
                "daemon_stop":    "Stop the scheduler daemon",
                "daemon_restart": "Restart the scheduler daemon",
                "list_tools":     "Tools available to scheduled agents",
            },
            "note": "To reply to a waiting task use reply_to_task(task_id=..., reply=...) directly.",
            "example": 'scheduler(action="list", status="waiting_for_input")',
        }

        if not action or action == "help":
            return HELP

        if action == "add":
            # Normalise hub params → internal format
            add_args = dict(args)
            # 'type' → 'task_type'
            if "task_type" not in add_args or not add_args.get("task_type"):
                add_args["task_type"] = add_args.get("type")
            # 'goal' → config.goal; 'role_id' → config.role_id
            config = add_args.get("config") or {}
            if not isinstance(config, dict):
                config = {}
            if add_args.get("goal") and "goal" not in config:
                config["goal"] = add_args["goal"]
            if add_args.get("role_id") and "role_id" not in config:
                config["role_id"] = add_args["role_id"]
            if add_args.get("available_tools") and "available_tools" not in config:
                config["available_tools"] = add_args["available_tools"]
            if add_args.get("max_iterations") and "max_iterations" not in config:
                config["max_iterations"] = add_args["max_iterations"]
            add_args["config"] = config
            return await self._execute_scheduler_add_task(add_args)
        elif action == "list":
            return await self._execute_scheduler_list_tasks(args)
        elif action == "get":
            task_id = args.get("task_id")
            if not task_id:
                return {"status": "error", "message": "Parameter 'task_id' is required."}
            return await self._execute_scheduler_get_task({"task_id": task_id})
        elif action == "remove":
            task_id = args.get("task_id")
            if not task_id:
                return {"status": "error", "message": "Parameter 'task_id' is required."}
            return await self._execute_scheduler_remove_task({"task_id": task_id})
        elif action == "purge":
            return await self._execute_scheduler_purge_tasks({"before_date": args.get("before_date")})
        elif action == "status":
            return await self._execute_scheduler_daemon_status({})
        elif action == "daemon_start":
            return await self._execute_scheduler_start_daemon({})
        elif action == "daemon_stop":
            return await self._execute_scheduler_stop_daemon({})
        elif action == "daemon_restart":
            return await self._execute_scheduler_restart_daemon({})
        elif action == "list_tools":
            return await self._execute_scheduler_list_assistant_tools({})
        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_dream(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dream hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "dream",
            "actions": {
                "process":        "Run dreaming pipeline — params: conversation_id, quality?",
                "list":           "List dreaming archives",
                "get":            "Retrieve archive — params: conversation_id, version?",
                "upgrade":        "Quality upgrade — params: conversation_id, target_quality",
                "distill_inbox":  "Run inbox distillation for a date — params: date? (YYYY-MM-DD, default yesterday)",
            },
            "example": 'dream(action="list")',
        }

        if not action or action == "help":
            return HELP

        if action == "process":
            conv_id = args.get("conversation_id")
            if not conv_id:
                return {"status": "error", "message": "Parameter 'conversation_id' is required."}
            return await self._execute_dreaming_process({
                "conversation_id": conv_id,
                "quality": args.get("quality"),
            })
        elif action == "list":
            return await self._execute_dreaming_list_archives({})
        elif action == "get":
            conv_id = args.get("conversation_id")
            if not conv_id:
                return {"status": "error", "message": "Parameter 'conversation_id' is required."}
            return await self._execute_dreaming_get_archive({
                "conversation_id": conv_id,
                "version": args.get("version"),
            })
        elif action == "upgrade":
            for param in ("conversation_id", "target_quality"):
                if not args.get(param):
                    return {"status": "error", "message": f"Parameter '{param}' is required."}
            return await self._execute_dreaming_upgrade_quality({
                "conversation_id": args["conversation_id"],
                "target_quality": args["target_quality"],
            })
        elif action == "distill_inbox":
            return await self._execute_dreaming_distill_inbox(args)
        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_dialog(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dialog hub — direct conversational access to a role."""
        from app.scheduler.role_chat import RoleChatSession, list_chat_sessions

        action = args.get("action", "chat")
        role_id = args.get("role_id", "")

        HELP = {
            "tool": "dialog",
            "actions": {
                "chat":     "Talk to a role — params: role_id, message, session_id?",
                "history":  "View session history — params: role_id, session_id?",
                "sessions": "List all sessions for a role — params: role_id",
            },
            "example": 'dialog(action="chat", role_id="rebecca", message="What did you find about Trivy?")',
            "note": "The role will NOT accept new task assignments in chat mode. Use scheduler for that.",
        }

        if not action or action == "help":
            return HELP

        if not role_id:
            return {"status": "error", "message": "Parameter 'role_id' is required."}

        if action == "chat":
            message = args.get("message", "")
            if not message:
                return {"status": "error", "message": "Parameter 'message' is required for chat action."}

            session = RoleChatSession(
                role_id=role_id,
                session_id=args.get("session_id"),
            )

            # Pass ResourceManager if available via scheduler executor
            rm = None
            try:
                executor = getattr(self.scheduler, "executor", None)
                if executor is not None:
                    rm = executor._get_resource_manager()
            except Exception:
                pass

            result = await session.exchange(message=message, resource_manager=rm)
            return result

        elif action == "history":
            session_id = args.get("session_id")
            session = RoleChatSession(role_id=role_id, session_id=session_id)
            data = session._load_session()
            return {
                "session_id": data.get("session_id"),
                "role_id": role_id,
                "started_at": data.get("started_at"),
                "last_active": data.get("last_active"),
                "exchanges": data.get("exchanges", []),
                "turn_count": len(data.get("exchanges", [])),
            }

        elif action == "sessions":
            sessions = list_chat_sessions(role_id)
            return {
                "role_id": role_id,
                "sessions": sessions,
                "count": len(sessions),
            }

        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_dreaming_distill_inbox(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run inbox distillation for a given date (default: yesterday)."""
        from datetime import date, timedelta
        try:
            from app.dreaming.inbox_distillation import run_inbox_distillation
            from app.scheduler.executor import TaskExecutor

            date_str = args.get("date")
            if date_str:
                target_date = date.fromisoformat(date_str)
            else:
                target_date = date.today() - timedelta(days=1)

            quality = args.get("quality", "basic")
            executor = TaskExecutor()
            pipeline = executor._get_dreaming_pipeline(quality)
            result = await run_inbox_distillation(
                target_date=target_date,
                event_log=self._event_log,
                pipeline=pipeline,
                quality_level=quality,
            )
            return {"status": "success", "date": target_date.isoformat(), "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Inbox distillation failed: {e}"}

    async def _execute_agent_hub(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Agent hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "agent",
            "actions": {
                "list_types": "Available agent types",
                "start":      "Start an agent — params: agent_id, type, ...",
                "stop":       "Stop an agent — params: agent_id",
                "status":     "Agent status — params: agent_id",
                "list":       "All running agents",
                "restart":    "Restart an agent — params: agent_id",
                "destroy":    "Destroy an agent — params: agent_id",
                "action":     "Send action to agent — params: agent_id, action, params",
            },
            "note": "For MoJo internal agentic tasks use scheduler(action='add', type='assistant', role_id=...).",
            "example": 'agent(action="list")',
        }

        if not action or action == "help":
            return HELP

        agent_id = args.get("agent_id")

        # Normalise: MCP schema uses 'type' and 'agent_id'; internal methods use 'agent_type' and 'identifier'
        agent_type = args.get("agent_type") or args.get("type")

        # For lifecycle actions that don't require knowing the type up-front,
        # look it up from the registry so callers only need to pass agent_id.
        if not agent_type and agent_id and action in ("stop", "restart", "destroy", "status"):
            found = await self.agent_registry.find_manager_for_agent(agent_id)
            if found:
                agent_type = found[0]
            else:
                return {
                    "status": "error",
                    "message": f"No running agent found with id '{agent_id}'. Use agent(action='list') to see available agents.",
                }

        normalised = {**args, "agent_type": agent_type, "identifier": agent_id}

        if action == "list_types":
            return await self._execute_agent_list_types({})
        elif action == "start":
            return await self._execute_agent_start(normalised)
        elif action == "stop":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' is required."}
            return await self._execute_agent_stop(normalised)
        elif action == "status":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' is required."}
            return await self._execute_agent_status(normalised)
        elif action == "list":
            return await self._execute_agent_list(normalised)
        elif action == "restart":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' is required."}
            return await self._execute_agent_restart(normalised)
        elif action == "destroy":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' is required."}
            return await self._execute_agent_destroy(normalised)
        elif action == "action":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' is required."}
            raw_params = args.get("params") or {}
            if isinstance(raw_params, str):
                import json as _json
                try:
                    raw_params = _json.loads(raw_params)
                except Exception:
                    raw_params = {}
            sub_action = raw_params.get("action")
            sub_params = {k: v for k, v in raw_params.items() if k != "action"}
            return await self._execute_agent_action({
                "agent_type": agent_type,
                "action": sub_action,
                "params": sub_params,
            })
        else:
            return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    async def _execute_external_agent(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """External agent hub dispatcher."""
        action = args.get("action")

        HELP = {
            "tool": "external_agent",
            "actions": {
                # HITL bridge — for coding agents connected to MoJo via MCP
                "ask_user": "Inject a question into the HITL inbox and pause — params: task_id, question, options?",
                "check_reply": "Poll for user reply to a previous ask_user — params: task_id",
                "run_task": "Spawn headless Claude Code for a task — params: prompt, working_dir?, task_id?, model?",
                # Coding agent backend management
                "google": "Google Workspace API proxy — params: service, resource, method, params?, json_body?, format?, ...",
                "backend_servers": "List all configured coding agent backends (OpenCode, Claude Code, ...)",
                "backend_health": "Check if a backend is reachable — params: server_id?",
                "backend_session_list": "List all sessions on a backend — params: server_id?",
                "backend_session_create": "Create a new coding session — params: server_id?",
                "backend_session_message": "Send a message and get a response — params: session_id, content, server_id?",
                "backend_session_messages": "Get full message history — params: session_id, server_id?",
                "backend_session_delete": "Delete a session — params: session_id, server_id?",
            },
            "future": ["github", "slack", "notion"],
            "example": 'external_agent(action="ask_user", task_id="cc-task-1", question="Use approach A or B?")',
        }

        if not action or action == "help":
            return HELP

        if action == "ask_user":
            return self._execute_external_agent_ask_user(args)

        if action == "check_reply":
            return self._execute_external_agent_check_reply(args)

        if action == "run_task":
            return await self._execute_external_agent_run_task(args)

        if action == "google":
            for param in ("service", "resource", "method"):
                if not args.get(param):
                    return {"status": "error", "message": f"Parameter '{param}' is required for google action."}
            return await self._execute_google_service(args)

        if action.startswith("backend") or action.startswith("opencode"):
            # opencode_* prefix kept as a backward-compat alias
            return await self._execute_backend(action, args)

        return {**HELP, "error": f"Unknown action '{action}'. See 'actions' above."}

    def _execute_external_agent_ask_user(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Inject a question from an external coding agent into the HITL inbox."""
        from app.scheduler.hitl_bridge import ask_user as hitl_ask_user
        task_id = (args.get("task_id") or "").strip()
        question = (args.get("question") or "").strip()
        options = args.get("options")
        return hitl_ask_user(self.scheduler.queue, task_id, question, options)

    def _execute_external_agent_check_reply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Poll for user reply to a previous ask_user call."""
        from app.scheduler.hitl_bridge import check_reply as hitl_check_reply
        task_id = (args.get("task_id") or "").strip()
        return hitl_check_reply(self.scheduler.queue, task_id)

    async def _execute_external_agent_run_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Spawn headless Claude Code for a task with MoJo as MCP server."""
        import shutil
        import subprocess
        import json
        import tempfile

        prompt = (args.get("prompt") or "").strip()
        working_dir = (args.get("working_dir") or "").strip()
        model = (args.get("model") or "").strip()
        task_id = (args.get("task_id") or "").strip()

        if not prompt:
            return {"status": "error", "message": "prompt is required"}

        # Generate a unique task_id if not provided
        if not task_id:
            import time as _time
            task_id = f"ext-cc-{int(_time.time())}"

        # Resolve working directory
        working_dir = os.path.expanduser(working_dir) if working_dir else os.path.expanduser("~")
        if not os.path.isdir(working_dir):
            return {"status": "error", "message": f"working_dir does not exist: {working_dir}"}

        # Find claude binary
        claude_bin = os.getenv("CLAUDE_BIN") or shutil.which("claude") or ""
        if not claude_bin:
            return {
                "status": "error",
                "message": "claude binary not found. Install Claude Code CLI or set CLAUDE_BIN env var.",
            }

        # Generate MCP config pointing back to this MoJo instance
        mcp_config = self._generate_claude_code_mcp_config()

        # Create stub task so ask_user calls have a home in the inbox
        from app.scheduler.models import Task, TaskType, TaskStatus
        existing = self.scheduler.queue.get(task_id)
        if existing is None:
            stub = Task(
                id=task_id,
                type=TaskType.AGENT,
                status=TaskStatus.RUNNING,
                description=f"Headless Claude Code: {prompt[:80]}",
                config={
                    "ext_agent_hitl": True,
                    "source": "headless_claude_code",
                    "goal": prompt,
                    "working_dir": working_dir,
                },
            )
            self.scheduler.queue.add(stub)

        # Inject task context into prompt so Claude Code knows its task_id
        mojo_context = (
            f"\n\n---\n"
            f"[MoJo context] Your task_id is '{task_id}'. "
            f"When you need human input, call: "
            f"external_agent(action='ask_user', task_id='{task_id}', question='...'). "
            f"Then poll: external_agent(action='check_reply', task_id='{task_id}') "
            f"until you get a reply."
        )
        full_prompt = prompt + mojo_context

        # Write MCP config to a temp file (not deleted immediately — subprocess needs it)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".mcp.json", delete=False, prefix="mojo_"
        )
        json.dump(mcp_config, tmp)
        tmp.flush()
        tmp.close()
        config_file = tmp.name

        cmd = [claude_bin, "-p", full_prompt, "--dangerously-skip-permissions",
               "--mcp-config", config_file]
        if model:
            cmd.extend(["--model", model])

        try:
            process = subprocess.Popen(
                cmd,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as e:
            return {"status": "error", "message": f"Failed to spawn Claude Code: {e}"}

        # Record PID in task config
        task = self.scheduler.queue.get(task_id)
        if task:
            task.config["pid"] = process.pid
            self.scheduler.queue.update(task)

        return {
            "status": "started",
            "task_id": task_id,
            "pid": process.pid,
            "working_dir": working_dir,
            "mcp_config_file": config_file,
            "note": (
                "Claude Code is running headlessly with MoJo as MCP server. "
                "It will call external_agent(action='ask_user') if it needs input."
            ),
            "monitor_with": f'scheduler(action="get", task_id="{task_id}")',
        }

    def _generate_claude_code_mcp_config(self) -> Dict[str, Any]:
        """Build the .mcp.json config that points headless Claude Code at this MoJo instance."""
        port = int(os.getenv("SERVER_PORT", "8000"))
        api_key = os.getenv("MCP_API_KEY", "")
        base_url = os.getenv("MOJO_BASE_URL", f"http://localhost:{port}")
        mcp_url = f"{base_url.rstrip('/')}/"
        config: Dict[str, Any] = {
            "mcpServers": {
                "mojo": {
                    "url": mcp_url,
                }
            }
        }
        if api_key:
            config["mcpServers"]["mojo"]["headers"] = {"MCP-API-Key": api_key}
        return config

    async def _execute_backend(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Coding agent backend actions via coding-agent-mcp-tool.

        Accepts both backend_* (canonical) and opencode_* (backward-compat alias) prefixes.
        """
        try:
            from coding_agent_mcp.backends import BackendRegistry
            from coding_agent_mcp.config.loader import load_config
        except ImportError:
            return {"status": "error", "message": "coding-agent-mcp-tool not installed. Run: pip install -e submodules/coding-agent-mcp-tool/"}

        try:
            config = load_config()
            registry = BackendRegistry()
            registry.reload(config.servers, config.default_server)
        except Exception as e:
            return {"status": "error", "message": f"Failed to load backend config: {e}"}

        server_id = args.get("server_id")

        # Normalise opencode_* aliases → backend_*
        normalised = action.replace("opencode_", "backend_", 1) if action.startswith("opencode_") else action

        try:
            if normalised == "backend_servers":
                return {"status": "ok", "servers": registry.list_all()}

            if normalised == "backend_health":
                backend = registry.get(server_id)
                return await backend.health()

            if normalised == "backend_session_list":
                backend = registry.get(server_id)
                sessions = await backend.list_sessions()
                return {"status": "ok", "sessions": sessions}

            if normalised == "backend_session_create":
                backend = registry.get(server_id)
                session = await backend.create_session()
                return {"status": "ok", "session": session}

            if normalised == "backend_session_message":
                session_id = args.get("session_id")
                content = args.get("content")
                if not session_id or not content:
                    return {"status": "error", "message": "session_id and content are required"}
                backend = registry.get(server_id)
                result = await backend.send_message(session_id, content)
                return {"status": "ok", "result": result}

            if normalised == "backend_session_messages":
                session_id = args.get("session_id")
                if not session_id:
                    return {"status": "error", "message": "session_id is required"}
                backend = registry.get(server_id)
                messages = await backend.get_messages(session_id)
                return {"status": "ok", "messages": messages}

            if normalised == "backend_session_delete":
                session_id = args.get("session_id")
                if not session_id:
                    return {"status": "error", "message": "session_id is required"}
                backend = registry.get(server_id)
                result = await backend.delete_session(session_id)
                return {"status": "ok", "result": result}

            return {"status": "error", "message": f"Unknown backend action: {action}"}

        except Exception as e:
            return {"status": "error", "message": str(e)}
