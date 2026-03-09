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

        # Initialize unified Agent Registry (replaces separate manager init)
        from app.mcp.agents.registry import AgentRegistry

        self.agent_registry = AgentRegistry(logger=logger)

        # Initialize SSE notifier for real-time task events
        from app.mcp.adapters.sse import SSENotifier

        self._sse_notifier = SSENotifier()

        # Initialize Scheduler (pass memory_service for agentic tool use)
        from app.scheduler.core import Scheduler

        self.scheduler = Scheduler(
            logger=logger,
            memory_service=memory_service,
            sse_notifier=self._sse_notifier,
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
                "file": "config/resource_pool_config.json",
                "description": "LLM resource pool for agentic tasks - endpoints, rate limits, budgets",
                "sensitive_keys": ["resources.*.api_key_env"],
                "on_change": self._on_resource_pool_config_change,
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
        }

        self.tools = self._define_tools()
        # Re-enable the working placeholder tools
        self.placeholder_tools = {
            "get_current_time",  # Redundant with get_current_day
            "get_memory_stats",  # Internal stats not useful for LLMs
        }

        # Enable web_search tool as implementation is complete
        if "web_search" in self.placeholder_tools:
            self.placeholder_tools.remove("web_search")

        # Enable web_search tool as implementation is complete
        if "web_search" in self.placeholder_tools:
            self.placeholder_tools.remove("web_search")

        # Enable web_search tool as implementation is complete
        self.enable_placeholder_tool("web_search")

        # Standardized user prompt templates for LLM usability
        self.user_prompt_templates = {
            "get_memory_context": {
                "template": "Search my memory for information about: {query}",
                "examples": [
                    "Search my memory for information about Python programming",
                    "Find information about our previous discussion about machine learning",
                    "Look up what I know about climate change",
                ],
                "usage_tip": "Use this tool to retrieve relevant context from the user's memory before answering questions or providing information.",
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
            "get_current_day": {
                "template": "What is today's date and day?",
                "examples": [
                    "What is today's date and day?",
                    "Tell me the current date and time",
                    "What day of the week is it today?",
                ],
                "usage_tip": "Use for questions about today's date, current day, time, or year information.",
            },
            "agent_list_types": {
                "template": "List available coding agent types",
                "examples": [
                    "What agent types are available?",
                    "List coding agents",
                ],
                "usage_tip": "Use to discover available agent types and their supported actions.",
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
                "name": "get_memory_context",
                "description": "Search all memory tiers (working, active, archival, knowledge base) for relevant context to enhance responses. Supports both English and Chinese queries. When to use: Call this tool whenever you need to retrieve relevant context from the user's memory during conversations, research, or problem-solving. How it works: Performs semantic search across multiple memory tiers using embeddings. Why useful: Provides personalized, context-aware responses based on user's history and knowledge.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query in English or Chinese to find relevant context",
                            "minLength": 1,
                        },
                        "max_items": {
                            "type": "integer",
                            "description": "Maximum number of context items to return (default: 10, max: 50)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "add_documents",
                "description": "Add reference documents, code examples, or knowledge to the permanent knowledge base for future retrieval. When to use: Use this when you want to permanently store reference material, documentation, code snippets, or any information that should be available for future conversations. How it works: Documents are embedded and stored in the knowledge base with optional metadata. Why useful: Builds a personal knowledge repository that can be searched later using get_memory_context.",
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
                "name": "get_current_day",
                "description": "Get the current date, day of week, time, and year information for temporal awareness. When to use: Call for questions about today's date, current day, time, current year, or any date/time related queries. How it works: Returns exact current date/time information without needing web search. Why useful: Provides accurate temporal context for scheduling, reminders, and time-sensitive responses.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_current_time",
                "description": "Get the current time with timezone information for precise timing. When to use: Use for questions about current time, scheduling, or time-sensitive operations. How it works: Returns detailed time information including hours, minutes, seconds, and timezone. Why useful: Ensures accurate time awareness for all responses.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
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
            # Unified Agent Manager Tools (replaces opencode_* and claude_code_* tools)
            {
                "name": "agent_list_types",
                "description": "List all installed and enabled coding agent types. Shows what agent types are available (e.g. 'opencode', 'claude_code'), their supported actions, and how to identify instances.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "agent_start",
                "description": "Start a coding agent instance. For opencode: pass git_url as identifier. For claude_code: pass session_id as identifier with working_dir in params.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code'). Use agent_list_types to see available types.",
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
                "description": "Stop a coding agent instance. Terminates the process but preserves state for restart.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
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
                "description": "Get the status of a coding agent instance. Shows PID, ports, health, and running state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
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
                "description": "List all instances of a coding agent type. Shows identifiers, running status, and details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
                            "minLength": 1,
                        },
                    },
                    "required": ["agent_type"],
                },
            },
            {
                "name": "agent_restart",
                "description": "Restart a coding agent instance. Stops and starts the process with the same configuration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
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
                "description": "Destroy a coding agent instance and clean up all resources. DESTRUCTIVE: permanently removes local data. The remote Git repository is NOT affected.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type (e.g. 'opencode', 'claude_code')",
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
                "description": "Execute a backend-specific action on a coding agent. Use agent_list_types to see supported actions per agent type. Examples: sandbox_create, llm_config, get_deploy_key.",
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
                "description": "Add a new task to the scheduler queue. Supports immediate execution, scheduled execution (specific datetime), and recurring execution (cron expression). Use this to schedule background tasks like memory consolidation (dreaming), periodic maintenance, or custom jobs. For agentic tasks, config supports: goal, max_iterations, tier_preference, planning_prompt, available_tools, resource_policy, and final_answer_requirements.",
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
                                "dreaming",
                                "scheduled",
                                "agent",
                                "custom",
                                "agentic",
                            ],
                            "description": "Type of task (dreaming=memory consolidation, scheduled=calendar event, agent=OpenCode/OpenClaw, custom=shell command, agentic=autonomous LLM agent loop)",
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
                "description": "Remove a task from the scheduler queue. Only pending tasks can be removed. Use this to cancel a scheduled task before it runs.",
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
                "description": "Read and write MoJoAssistant configuration. Actions: 'help' lists configurable modules (or shows structure of a specific module), 'get' reads config (optionally at a dot-path), 'set' writes a value at a dot-path and persists to disk. Modules: llm, embedding.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["help", "get", "set"],
                            "description": "Action to perform: help (list modules or show structure), get (read config), set (write value)",
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
                    },
                    "required": ["action"],
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
            if tool_name in ["get_memory_context", "get_memory_stats"]:
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
                "get_current_day",
                "get_current_time",
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
            "get_memory_context": "high",
            "add_conversation": "high",
            "add_documents": "high",
            "end_conversation": "medium",
            "toggle_multi_model": "medium",
            "list_recent_conversations": "medium",
            "web_search": "medium",
            "get_current_day": "medium",
            "knowledge_add_repo": "medium",
            "knowledge_get_file": "medium",
            "knowledge_list_repos": "medium",
            "remove_conversation_message": "low",
            "remove_recent_conversations": "low",
            "list_recent_documents": "low",
            "remove_document": "low",
            "get_current_time": "low",
        }

        for tool in tools:
            tool_name = tool["name"]
            priority = priority_mapping.get(tool_name, "medium")
            priority_levels[priority].append(tool)

        return priority_levels

    def get_essential_tools(self) -> List[Dict[str, Any]]:
        """Get essential tools that should always be available to LLMs"""
        essential_tool_names = [
            "get_memory_context",  # Core memory functionality
            "add_conversation",  # Conversation context preservation
            "add_documents",  # Knowledge base management
            "end_conversation",  # Conversation management
            "web_search",  # Current information access
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
        """Generate a comprehensive usage guide for LLMs"""
        categories = self.get_tools_by_category()

        guide = "## MCP Tools Usage Guide\n\n"
        guide += "### Tool Categories and Usage Patterns\n\n"

        for category, tools in categories.items():
            if tools:
                guide += f"#### {category.title()} Tools\n"
                guide += f"*{self.get_category_description(category)}*\n\n"

                for tool in tools:
                    tool_name = tool["name"]
                    template = self.get_user_prompt_template(tool_name)

                    guide += f"**{tool_name}**\n"
                    guide += f"- *Description*: {tool['description']}\n"

                    if template:
                        guide += f"- *User Prompt Template*: {template['template']}\n"
                        guide += f"- *Usage Tip*: {template['usage_tip']}\n"

                    guide += "\n"

        guide += "### Priority Guidelines\n"
        guide += (
            "- **High Priority**: Core memory and conversation tools (use frequently)\n"
        )
        guide += "- **Medium Priority**: Supporting tools for enhanced functionality\n"
        guide += "- **Low Priority**: Cleanup and management tools (use as needed)\n\n"

        guide += "### Best Practices\n"
        guide += (
            "1. Always use `add_conversation` after each exchange to maintain context\n"
        )
        guide += "2. Use `get_memory_context` before answering questions to retrieve relevant information\n"
        guide += "3. Use `web_search` for current information not available in local memory\n"
        guide += (
            "4. Use `end_conversation` when switching to completely different topics\n"
        )
        guide += "5. Regularly clean up old conversations and documents to maintain system performance\n"

        return guide

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

        if name == "get_memory_context":
            return await self._execute_get_memory_context(args)
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
        # Unified Agent Manager Tools
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
        # Scheduler Daemon Control
        elif name == "scheduler_start_daemon":
            return await self._execute_scheduler_start_daemon(args)
        elif name == "scheduler_stop_daemon":
            return await self._execute_scheduler_stop_daemon(args)
        elif name == "scheduler_restart_daemon":
            return await self._execute_scheduler_restart_daemon(args)
        elif name == "scheduler_daemon_status":
            return await self._execute_scheduler_daemon_status(args)
        # Dreaming Tools
        elif name == "dreaming_process":
            return await self._execute_dreaming_process(args)
        elif name == "dreaming_list_archives":
            return await self._execute_dreaming_list_archives(args)
        elif name == "dreaming_get_archive":
            return await self._execute_dreaming_get_archive(args)
        elif name == "dreaming_upgrade_quality":
            return await self._execute_dreaming_upgrade_quality(args)
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
        # Resource Pool Tools
        elif name == "resource_pool_status":
            return await self._execute_resource_pool_status(args)
        elif name == "resource_pool_approve":
            return await self._execute_resource_pool_approve(args)
        elif name == "resource_pool_revoke":
            return await self._execute_resource_pool_revoke(args)
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

        return {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": time.time(),
        }

    async def _execute_add_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add conversation"""
        user_message = args.get("user_message", "")
        assistant_message = args.get("assistant_message", "")

        self.memory_service.add_user_message(user_message)
        self.memory_service.add_assistant_message(assistant_message)

        return {
            "status": "success",
            "message": "Conversation exchange added to working memory",
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
                    # Regular document processing
                    self.memory_service.add_to_knowledge_base(content, metadata)
                    results.append({"status": "success", "message": "Document added"})

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
            manager = self.agent_registry.get_manager(agent_type)
            return await manager.list_projects()
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list {agent_type} agents: {str(e)}",
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
            task_id = args.get("task_id")
            task_type_str = args.get("task_type")
            schedule_str = args.get("schedule")
            cron_expression = args.get("cron_expression")
            priority_str = args.get("priority", "medium")
            config = args.get("config", {})
            description = args.get("description")
            resources_dict = args.get("resources", {})

            # Convert strings to enums
            task_type = TaskType(task_type_str)
            priority = TaskPriority(priority_str)

            # Parse schedule
            schedule = None
            if schedule_str:
                schedule = datetime.fromisoformat(schedule_str)

            # Create task
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
            from dreaming.storage.json_backend import JsonFileBackend

            storage = JsonFileBackend()
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

            from dreaming.storage.json_backend import JsonFileBackend

            storage = JsonFileBackend()

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

            if original_task.type != TaskType.AGENTIC:
                return {
                    "status": "error",
                    "message": f"Task '{task_id}' is not an agentic task (type: {original_task.type.value})",
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
                type=TaskType.AGENTIC,
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

    # ========================================================================
    # Resource Pool Tools
    # ========================================================================

    def _get_resource_manager(self):
        """Get the ResourceManager from the scheduler's executor, lazy-initializing if needed."""
        return self.scheduler.executor._get_resource_manager()

    async def _execute_resource_pool_status(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute resource_pool_status tool"""
        try:
            rm = self._get_resource_manager()
            status = rm.get_status()
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
        """Hook called after LLM config is modified — resets cached executor pipeline."""
        try:
            if hasattr(self, "scheduler") and hasattr(self.scheduler, "executor"):
                self.scheduler.executor.reset_pipeline()
        except Exception:
            pass  # non-critical

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

    async def _execute_config(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch config actions: help, get, set."""
        action = args.get("action")
        module_name = args.get("module")

        # --- help ---
        if action == "help":
            if not module_name:
                # List all modules
                modules = {}
                for name, meta in self._config_modules.items():
                    modules[name] = {
                        "description": meta["description"],
                        "file": meta["file"],
                    }
                return {"status": "success", "modules": modules}
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
                data = self._load_config_file(meta["file"])
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
                data = self._load_config_file(meta["file"])

                # Get old value for reporting
                try:
                    old_value = self._resolve_path(data, path)
                except KeyError:
                    old_value = None

                # Smart validation: LLM model changes on openai-compatible providers
                if module_name == "llm" and validate and _is_llm_model_path(path):
                    # Extract interface name from path like "api_models.lmstudio.model"
                    parts = path.split(".")
                    if len(parts) >= 2:
                        interface_name = parts[1]
                        iface = data.get("api_models", {}).get(interface_name, {})
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

                # Apply the change
                self._set_path(data, path, value)
                self._save_config_file(meta["file"], data)

                # Fire change hook
                if meta.get("on_change"):
                    meta["on_change"]()

                return {
                    "status": "success",
                    "module": module_name,
                    "path": path,
                    "old_value": old_value,
                    "new_value": value,
                    "message": f"Updated {module_name}.{path}: {old_value!r} -> {value!r}",
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to set config: {e}"}

        return {
            "status": "error",
            "message": f"Unknown action '{action}'. Use: help, get, set.",
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
            llm_config = self._load_config_file(self._config_modules["llm"]["file"])
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
            if iface.get("provider") != "openai":
                return {
                    "status": "error",
                    "message": f"Interface '{interface_name}' uses provider '{iface.get('provider')}', not openai. Model listing is only supported for OpenAI-compatible servers.",
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
