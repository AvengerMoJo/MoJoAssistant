"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""

from typing import Dict, Any, List
import time
import threading
import asyncio
from datetime import datetime
from app.git.git_service import GitService


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

        # Initialize OpenCode manager
        from app.mcp.opencode.manager import OpenCodeManager

        self.opencode_manager = OpenCodeManager(logger=logger)

        # Initialize Scheduler
        from app.scheduler.core import Scheduler

        self.scheduler = Scheduler(logger=logger)
        self.scheduler_thread = None

        # Auto-start scheduler in background thread
        self._start_scheduler_daemon()

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
            "opencode_stop_mcp_tool": {
                "template": "Stop the global opencode-mcp-tool instance",
                "examples": [
                    "Stop the global opencode-mcp-tool",
                    "Terminate the MCP tool that serves all OpenCode projects",
                ],
                "usage_tip": "Use when you need to manually stop the global MCP tool, even when there are active projects running.",
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
        if self.scheduler_thread and self.scheduler_thread.is_alive() and self.scheduler.running:
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
                    self.logger.info("[ToolRegistry] Scheduler daemon thread exiting normally")
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
            daemon=True  # Dies when main thread exits
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
        was_running = self.scheduler.running or (self.scheduler_thread and self.scheduler_thread.is_alive())

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
                "name": "add_git_repository",
                "description": "Register a private git repository for code analysis and retrieval. When to use: Use when you want to give the memory system access to a private codebase for future reference and understanding. How it works: Clones repository using SSH key authentication and stores it locally for file access. Why useful: Enables code-aware conversations and allows storing code insights in memory. IMPORTANT: SSH key must NOT have a passphrase. If your key has a passphrase, remove it first with: ssh-keygen -p -f <key_path>",
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
                "name": "get_git_file_content",
                "description": "Retrieve file content from a registered git repository. When to use: Use when you need to read the actual code content of specific files for analysis or reference. How it works: Retrieves current or historical file content directly from the git repository. Why useful: Provides access to actual code for detailed analysis and understanding.",
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
                "name": "list_git_repositories",
                "description": "List all registered git repositories. When to use: Use to see which repositories are available for code analysis and their current status. How it works: Shows all registered repositories with their URLs, branches, and status. Why useful: Helps you understand what codebases are available for analysis.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            # OpenCode Manager Tools (Phase 3: git_url-based)
            {
                "name": "opencode_project_start",
                "description": "Start an OpenCode project by git URL. The project name is auto-generated from the repository (e.g., git@github.com:user/repo.git becomes 'user-repo'). Creates base directory at ~/.opencode-projects/{owner}-{repo} by default. SECRETS ARE NEVER PASSED - they're read from .env files. Use this when you need to start working on a codebase with AI assistance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL (SSH or HTTPS format, will be normalized to SSH). Example: git@github.com:user/repo.git or https://github.com/user/repo",
                            "minLength": 1,
                        },
                        "user_ssh_key": {
                            "type": "string",
                            "description": "Optional: Path to user's SSH key (will auto-generate if not provided)",
                        },
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_project_status",
                "description": "Check the status of an OpenCode project by git URL. Shows if processes are running, ports, PIDs, and health status. Use this to verify a project is running correctly.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_project_stop",
                "description": "Stop an OpenCode project by git URL. Terminates the OpenCode server process. The base directory and files remain intact. Use this to free up resources when not actively working on a project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_project_restart",
                "description": "Restart an OpenCode project by git URL. Stops and starts the process. Useful when processes have crashed or need to reload configuration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_project_destroy",
                "description": "⚠️ DESTRUCTIVE: Stop project and DELETE base directory by git URL. This permanently removes all local code, worktrees, and configuration. The remote Git repository is NOT affected. Use only when you're completely done with a project and want to free up disk space.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_project_list",
                "description": "List all OpenCode projects. Shows git URLs, project names, running status, ports, and base directory locations. Use this to see what projects are available.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            # Sandbox/Worktree Management Tools (Phase 2)
            {
                "name": "opencode_sandbox_create",
                "description": "Create a git worktree (sandbox) for isolated development. Worktrees share the same .git database but have separate working directories and can be on different branches. Perfect for testing changes without affecting your main workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        },
                        "name": {
                            "type": "string",
                            "description": "Worktree name (unique within project, alphanumeric with hyphens/underscores)",
                            "minLength": 1,
                            "pattern": "^[a-zA-Z0-9_-]+$",
                        },
                        "branch": {
                            "type": "string",
                            "description": "Optional: Branch to checkout (default: current branch)",
                        },
                        "start_command": {
                            "type": "string",
                            "description": "Optional: Command to run after worktree creation",
                        },
                    },
                    "required": ["git_url", "name"],
                },
            },
            {
                "name": "opencode_sandbox_list",
                "description": "List all worktrees (sandboxes) for a project. Shows worktree paths and their status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            {
                "name": "opencode_sandbox_delete",
                "description": "Delete a git worktree (sandbox). This removes the worktree directory but does not affect the main repository or other worktrees.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        },
                        "name": {
                            "type": "string",
                            "description": "Worktree name to delete",
                            "minLength": 1,
                        },
                    },
                    "required": ["git_url", "name"],
                },
            },
            {
                "name": "opencode_sandbox_reset",
                "description": "Reset a worktree to clean state (default branch). Discards all uncommitted changes and resets to the default branch. Use this to start fresh in a sandbox.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        },
                        "name": {
                            "type": "string",
                            "description": "Worktree name to reset",
                            "minLength": 1,
                        },
                    },
                    "required": ["git_url", "name"],
                },
            },
            {
                "name": "opencode_mcp_status",
                "description": "Get status of the global opencode-mcp-tool instance that serves all projects. Shows PID, port, number of active projects, and health status. Use this to check if the MCP tool is running.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "opencode_mcp_restart",
                "description": "Manually restart the global opencode-mcp-tool instance. Useful after updating the opencode-mcp-tool repository or when the MCP tool needs to reload configuration. Will only restart if there are active projects.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "opencode_stop_mcp_tool",
                "description": "Manually stop the global opencode-mcp-tool instance. Can be used even when there are active projects. Useful for maintenance or when the MCP tool needs to be completely stopped.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "opencode_llm_config",
                "description": "Get the global OpenCode LLM configuration: current default model, available providers, and their configured models. This shows what AI models OpenCode can use.",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "opencode_llm_set_model",
                "description": "Set the default LLM model for all OpenCode instances. The model format is 'provider-id/model-id' (e.g., 'MoJoLLM/zai-org/glm-4.7-flash'). Use opencode_llm_config to see available providers and models first.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Model identifier in format 'provider-id/model-id'",
                            "minLength": 1,
                        }
                    },
                    "required": ["model"],
                },
            },
            # SSH Deploy Key Management (Phase 4)
            {
                "name": "opencode_get_deploy_key",
                "description": "Get the SSH public key for a git repository. Use this to retrieve the deploy key that OpenCode generated, which you need to add to your repository's deploy keys on GitHub/GitLab. The key is auto-generated when you first start a project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "git_url": {
                            "type": "string",
                            "description": "Git repository URL",
                            "minLength": 1,
                        }
                    },
                    "required": ["git_url"],
                },
            },
            # Diagnostic & Cleanup Tools (Phase 5)
            {
                "name": "opencode_detect_duplicates",
                "description": "Detect duplicate projects (same git repository running in multiple OpenCode instances). Provides recommendations on which instance to keep and suggests converting others to worktrees. Useful for cleaning up resource usage and avoiding session confusion.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "opencode_cleanup_orphaned",
                "description": "Detect and clean up orphaned OpenCode processes. An orphaned process is one where the PID in state doesn't exist (process crashed or was killed), but the project is still marked as running. This tool will automatically update the state to reflect reality.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            # Scheduler Tools
            {
                "name": "scheduler_add_task",
                "description": "Add a new task to the scheduler queue. Supports immediate execution, scheduled execution (specific datetime), and recurring execution (cron expression). Use this to schedule background tasks like memory consolidation (dreaming), periodic maintenance, or custom jobs.",
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
                            "enum": ["dreaming", "scheduled", "agent", "custom"],
                            "description": "Type of task (dreaming=memory consolidation, scheduled=calendar event, agent=OpenCode/OpenClaw, custom=shell command)",
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
                            "enum": ["pending", "running", "completed", "failed", "cancelled"],
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
        ]

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools (excludes placeholders)"""
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
                "add_git_repository",
                "get_git_file_content",
                "list_git_repositories",
            ]:
                categories["git"].append(tool)
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
            "add_git_repository": "medium",
            "get_git_file_content": "medium",
            "list_git_repositories": "medium",
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
            "opencode": "OpenCode project management tools for managing coding agent projects and the global MCP tool",
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
        elif name == "get_current_day":
            return await self._execute_get_current_day(args)
        elif name == "get_current_time":
            return await self._execute_get_current_time(args)
        elif name == "add_git_repository":
            return await self._execute_add_git_repository(args)
        elif name == "get_git_file_content":
            return await self._execute_get_git_file_content(args)
        elif name == "list_git_repositories":
            return await self._execute_list_git_repositories(args)
        # OpenCode Project Lifecycle (Phase 3: git_url-based)
        elif name == "opencode_project_start":
            return await self._execute_opencode_project_start(args)
        elif name == "opencode_project_status":
            return await self._execute_opencode_project_status(args)
        elif name == "opencode_project_stop":
            return await self._execute_opencode_project_stop(args)
        elif name == "opencode_project_restart":
            return await self._execute_opencode_project_restart(args)
        elif name == "opencode_project_destroy":
            return await self._execute_opencode_project_destroy(args)
        elif name == "opencode_project_list":
            return await self._execute_opencode_project_list(args)
        # OpenCode Sandbox Management (Phase 2)
        elif name == "opencode_sandbox_create":
            return await self._execute_opencode_sandbox_create(args)
        elif name == "opencode_sandbox_list":
            return await self._execute_opencode_sandbox_list(args)
        elif name == "opencode_sandbox_delete":
            return await self._execute_opencode_sandbox_delete(args)
        elif name == "opencode_sandbox_reset":
            return await self._execute_opencode_sandbox_reset(args)
        # OpenCode Global MCP Tool
        elif name == "opencode_mcp_status":
            return await self._execute_opencode_mcp_status(args)
        elif name == "opencode_mcp_restart":
            return await self._execute_opencode_mcp_restart(args)
        elif name == "opencode_stop_mcp_tool":
            return await self._execute_opencode_stop_mcp_tool(args)
        # OpenCode LLM Configuration
        elif name == "opencode_llm_config":
            return await self._execute_opencode_llm_config(args)
        elif name == "opencode_llm_set_model":
            return await self._execute_opencode_llm_set_model(args)
        # OpenCode SSH Deploy Key
        elif name == "opencode_get_deploy_key":
            return await self._execute_opencode_get_deploy_key(args)
        # OpenCode Diagnostic & Cleanup Tools
        elif name == "opencode_detect_duplicates":
            return await self._execute_opencode_detect_duplicates(args)
        elif name == "opencode_cleanup_orphaned":
            return await self._execute_opencode_cleanup_orphaned(args)
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
                    "message": f"Repository '{repo_name}' not registered. Register it first with add_git_repository.",
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

    async def _execute_add_git_repository(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add git repository"""
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

    async def _execute_get_git_file_content(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute get git file content"""
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

    async def _execute_list_git_repositories(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute list git repositories"""
        try:
            result = self.git_service.list_repositories()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list repositories: {str(e)}",
            }

    # ========================================================================
    # OpenCode Manager execution methods (Phase 3: git_url-based)
    # ========================================================================

    # Project Lifecycle Methods
    async def _execute_opencode_project_start(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_start tool (Phase 3)"""
        git_url = args.get("git_url")
        user_ssh_key = args.get("user_ssh_key")

        try:
            result = await self.opencode_manager.start_project(
                git_url, user_ssh_key
            )
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start project: {str(e)}",
            }

    async def _execute_opencode_project_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_status tool (Phase 3)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.get_status(git_url)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get status: {str(e)}",
            }

    async def _execute_opencode_project_stop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_stop tool (Phase 3)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.stop_project(git_url)
            return result
        except Exception as e:
            # Check if it's an OpenCodeError with formatted response
            from app.mcp.opencode.errors import OpenCodeError
            if isinstance(e, OpenCodeError):
                return e.to_dict()

            # Generic error
            return {
                "status": "error",
                "message": f"Failed to stop project: {str(e)}",
            }

    async def _execute_opencode_project_restart(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_restart tool (Phase 3)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.restart_project(git_url)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to restart project: {str(e)}",
            }

    async def _execute_opencode_project_destroy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_destroy tool (Phase 3)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.destroy_project(git_url)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to destroy project: {str(e)}",
            }

    async def _execute_opencode_project_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_project_list tool (Phase 3)"""
        try:
            result = await self.opencode_manager.list_projects()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list projects: {str(e)}",
            }

    # Sandbox/Worktree Management Methods (Phase 2)
    async def _execute_opencode_sandbox_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_sandbox_create tool (Phase 2)"""
        git_url = args.get("git_url")
        name = args.get("name")
        branch = args.get("branch")
        start_command = args.get("start_command")

        try:
            result = await self.opencode_manager.create_sandbox(
                git_url, name, branch, start_command
            )
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create sandbox: {str(e)}",
            }

    async def _execute_opencode_sandbox_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_sandbox_list tool (Phase 2)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.list_sandboxes(git_url)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list sandboxes: {str(e)}",
            }

    async def _execute_opencode_sandbox_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_sandbox_delete tool (Phase 2)"""
        git_url = args.get("git_url")
        name = args.get("name")

        try:
            result = await self.opencode_manager.delete_sandbox(git_url, name)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to delete sandbox: {str(e)}",
            }

    async def _execute_opencode_sandbox_reset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute opencode_sandbox_reset tool (Phase 2)"""
        git_url = args.get("git_url")
        name = args.get("name")

        try:
            result = await self.opencode_manager.reset_sandbox(git_url, name)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to reset sandbox: {str(e)}",
            }

    async def _execute_opencode_mcp_status(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_mcp_status tool"""
        try:
            result = await self.opencode_manager.get_mcp_status()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get MCP status: {str(e)}",
            }

    async def _execute_opencode_mcp_restart(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_mcp_restart tool"""
        try:
            result = await self.opencode_manager.restart_mcp_tool()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to restart MCP tool: {str(e)}",
            }

    async def _execute_opencode_stop_mcp_tool(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_stop_mcp_tool tool"""
        try:
            result = await self.opencode_manager.stop_mcp_tool()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to stop MCP tool: {str(e)}",
            }

    async def _execute_opencode_llm_config(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_llm_config tool"""
        try:
            result = await self.opencode_manager.get_llm_config()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get LLM config: {str(e)}",
            }

    async def _execute_opencode_llm_set_model(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_llm_set_model tool"""
        model = args.get("model")
        try:
            result = await self.opencode_manager.set_llm_model(model)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to set LLM model: {str(e)}",
            }

    # SSH Deploy Key Management (Phase 4)
    async def _execute_opencode_get_deploy_key(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_get_deploy_key tool (Phase 4)"""
        git_url = args.get("git_url")

        try:
            result = await self.opencode_manager.get_deploy_key(git_url)
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get deploy key: {str(e)}",
            }

    # Diagnostic & Cleanup Tools (Phase 5)
    async def _execute_opencode_detect_duplicates(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_detect_duplicates tool (Phase 5)"""
        try:
            result = await self.opencode_manager.detect_duplicates()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to detect duplicates: {str(e)}",
            }

    async def _execute_opencode_cleanup_orphaned(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute opencode_cleanup_orphaned tool (Phase 5)"""
        try:
            result = await self.opencode_manager.cleanup_orphaned_processes()
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to cleanup orphaned processes: {str(e)}",
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

            # Convert strings to enums
            task_type = TaskType(task_type_str)
            priority = TaskPriority(priority_str)

            # Parse schedule
            schedule = None
            if schedule_str:
                schedule = datetime.fromisoformat(schedule_str)

            # Create task
            task = Task(
                id=task_id,
                type=task_type,
                schedule=schedule,
                cron_expression=cron_expression,
                priority=priority,
                config=config,
                description=description
            )

            # Add to scheduler
            success = self.scheduler.add_task(task)

            if success:
                return {
                    "status": "success",
                    "message": f"Task {task_id} added to scheduler",
                    "task": task.to_dict()
                }
            else:
                return {
                    "status": "error",
                    "message": f"Task {task_id} already exists"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to add task: {str(e)}"
            }

    async def _execute_scheduler_list_tasks(self, args: Dict[str, Any]) -> Dict[str, Any]:
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
                status=status_filter,
                priority=priority_filter,
                limit=limit
            )

            # Convert to dict
            tasks_data = [task.to_dict() for task in tasks]

            return {
                "status": "success",
                "tasks": tasks_data,
                "total": len(tasks_data)
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list tasks: {str(e)}"
            }

    async def _execute_scheduler_get_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_get_status tool"""
        try:
            status = self.scheduler.get_status()
            return {
                "status": "success",
                "scheduler": status
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get scheduler status: {str(e)}"
            }

    async def _execute_scheduler_get_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_get_task tool"""
        try:
            task_id = args.get("task_id")
            task = self.scheduler.get_task(task_id)

            if task:
                return {
                    "status": "success",
                    "task": task.to_dict()
                }
            else:
                return {
                    "status": "error",
                    "message": f"Task {task_id} not found"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get task: {str(e)}"
            }

    async def _execute_scheduler_remove_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_remove_task tool"""
        try:
            task_id = args.get("task_id")
            success = self.scheduler.remove_task(task_id)

            if success:
                return {
                    "status": "success",
                    "message": f"Task {task_id} removed from scheduler"
                }
            else:
                return {
                    "status": "error",
                    "message": f"Task {task_id} not found"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to remove task: {str(e)}"
            }

    # ========================================================================
    # Scheduler Daemon Control execution methods
    # ========================================================================

    async def _execute_scheduler_start_daemon(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_start_daemon tool"""
        try:
            success = self._start_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon started",
                    "running": self.scheduler.running,
                    "tick_count": self.scheduler.tick_count,
                    "thread_alive": self.scheduler_thread.is_alive() if self.scheduler_thread else False
                }
            else:
                return {
                    "status": "error",
                    "message": "Scheduler daemon is already running"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start scheduler daemon: {str(e)}"
            }

    async def _execute_scheduler_stop_daemon(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_stop_daemon tool"""
        try:
            success = self._stop_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon stopped gracefully",
                    "running": self.scheduler.running
                }
            else:
                return {
                    "status": "error",
                    "message": "Scheduler daemon was not running"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to stop scheduler daemon: {str(e)}"
            }

    async def _execute_scheduler_restart_daemon(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_restart_daemon tool"""
        try:
            success = self._restart_scheduler_daemon()

            if success:
                return {
                    "status": "success",
                    "message": "Scheduler daemon restarted",
                    "running": self.scheduler.running,
                    "tick_count": self.scheduler.tick_count,
                    "thread_alive": self.scheduler_thread.is_alive() if self.scheduler_thread else False
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to restart scheduler daemon"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to restart scheduler daemon: {str(e)}"
            }

    async def _execute_scheduler_daemon_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute scheduler_daemon_status tool"""
        try:
            thread_alive = self.scheduler_thread.is_alive() if self.scheduler_thread else False

            # Get scheduler statistics
            status = self.scheduler.get_status()

            return {
                "status": "success",
                "daemon": {
                    "running": self.scheduler.running,
                    "thread_alive": thread_alive,
                    "thread_name": self.scheduler_thread.name if self.scheduler_thread else None,
                },
                "scheduler": status,
                "message": f"Scheduler daemon is {'running' if thread_alive and self.scheduler.running else 'stopped'}"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get scheduler daemon status: {str(e)}"
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

            # Initialize dreaming pipeline
            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(config_file=self.config.get("llm_config_path", "config/llm_config.json"))

            # Set active interface for dreaming
            if 'qwen-coder-small' in llm.interfaces:
                llm.set_active_interface('qwen-coder-small')

            pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level=quality_level,
                logger=self.logger
            )

            # Process conversation
            results = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata=metadata
            )

            if results.get('status') == 'success':
                return {
                    "status": "success",
                    "conversation_id": conversation_id,
                    "quality_level": quality_level,
                    "stages": results.get('stages', {}),
                    "message": f"Successfully processed conversation {conversation_id}"
                }
            else:
                return {
                    "status": "error",
                    "message": results.get('error', 'Unknown error during processing')
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Dreaming processing failed: {str(e)}"
            }

    async def _execute_dreaming_list_archives(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute dreaming_list_archives tool"""
        try:
            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(config_file=self.config.get("llm_config_path", "config/llm_config.json"))

            pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level="basic",
                logger=self.logger
            )

            archives = pipeline.list_archives()

            return {
                "status": "success",
                "archives": archives,
                "count": len(archives),
                "message": f"Found {len(archives)} archived conversations"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to list archives: {str(e)}"
            }

    async def _execute_dreaming_get_archive(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute dreaming_get_archive tool"""
        try:
            conversation_id = args.get("conversation_id")
            version = args.get("version")

            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(config_file=self.config.get("llm_config_path", "config/llm_config.json"))

            pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level="basic",
                logger=self.logger
            )

            archive = pipeline.get_archive(conversation_id=conversation_id, version=version)

            if archive:
                return {
                    "status": "success",
                    "archive": archive,
                    "message": f"Retrieved archive for {conversation_id}"
                }
            else:
                return {
                    "status": "error",
                    "message": f"Archive not found for conversation {conversation_id}"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to get archive: {str(e)}"
            }

    async def _execute_dreaming_upgrade_quality(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute dreaming_upgrade_quality tool"""
        try:
            conversation_id = args.get("conversation_id")
            target_quality = args.get("target_quality")

            from app.dreaming.pipeline import DreamingPipeline
            from app.llm.llm_interface import LLMInterface

            llm = LLMInterface(config_file=self.config.get("llm_config_path", "config/llm_config.json"))

            pipeline = DreamingPipeline(
                llm_interface=llm,
                quality_level="basic",  # Will be upgraded
                logger=self.logger
            )

            results = await pipeline.upgrade_quality(
                conversation_id=conversation_id,
                target_quality=target_quality
            )

            if results.get('status') == 'success':
                return {
                    "status": "success",
                    "conversation_id": conversation_id,
                    "upgraded_from": results.get('upgraded_from'),
                    "upgraded_to": results.get('upgraded_to'),
                    "stages": results.get('stages', {}),
                    "message": f"Successfully upgraded {conversation_id} to {target_quality}"
                }
            else:
                return {
                    "status": "error",
                    "message": results.get('error', 'Unknown error during upgrade')
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Quality upgrade failed: {str(e)}"
            }
