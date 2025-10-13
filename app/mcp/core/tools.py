"""
Tool definitions and execution logic
File: app/mcp/core/tools.py
"""
from typing import Dict, Any, List
import time


class ToolRegistry:
    """Registry of available tools and their execution"""
    
    def __init__(self, memory_service):
        self.memory_service = memory_service
        self.tools = self._define_tools()
    
    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define all available tools with comprehensive descriptions"""
        return [
            {
                "name": "get_memory_context",
                "description": """COMPREHENSIVE MEMORY SEARCH - Primary tool for retrieving relevant context across all memory tiers.

WHEN TO USE:
- User asks questions that might relate to past conversations, documents, or knowledge
- You need background context to provide better responses
- User references something from "before", "earlier", or "we discussed"
- Any query that could benefit from historical context or factual information

HOW IT WORKS:
- Searches ALL memory tiers in PARALLEL for maximum speed and coverage:
  • Working Memory: Current conversation context
  • Active Memory: Recent conversations (days/weeks)
  • Archival Memory: All historical conversations (semantic search)
  • Knowledge Base: Documents and factual information
- Returns comprehensive results with metadata for intelligent filtering
- Uses advanced semantic search with multiple embedding models

WHY USE THIS:
- Provides rich context for more accurate and personalized responses
- Leverages the full power of MoJoAssistant's human-like memory architecture
- Essential for maintaining conversation continuity and referencing past discussions
- Enables factual accuracy by accessing stored documents and knowledge

PARAMETERS:
- query: Natural language search query (be specific for better results)
- max_results: Maximum items to return (default: 50 for comprehensive context)

RETURNS: Rich contextual data with relevance scores, sources, timestamps, and metadata for intelligent selection.""",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query - be specific for better semantic matching"
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 50,
                            "minimum": 1,
                            "maximum": 200,
                            "description": "Maximum results to return - modern LLMs can handle large context, so don't be conservative"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "add_conversation",
                "description": """CONVERSATION MEMORY STORAGE - Store conversation turns into MoJoAssistant's memory system.

WHEN TO USE:
- At the end of meaningful conversation exchanges
- When you want to ensure important information is preserved for future reference
- Before context window limits are reached
- When transitioning between conversation topics

HOW IT WORKS:
- Stores messages in Working Memory (immediate context)
- Automatically flows to Active Memory and eventually Archival Memory
- Maintains conversation continuity and enables future retrieval
- Supports both user and assistant message types

WHY USE THIS:
- Enables long-term memory and conversation continuity
- Allows future conversations to reference past interactions
- Essential for building personalized assistant experience
- Preserves important decisions, preferences, and context

PARAMETERS:
- messages: Array of conversation messages with type (user/assistant) and content

RETURNS: Confirmation of storage with message counts and processing details.""",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "description": "Array of conversation messages to store",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["user", "assistant"],
                                        "description": "Message type: 'user' for human messages, 'assistant' for AI responses"
                                    },
                                    "content": {
                                        "type": "string",
                                        "description": "The actual message content - preserve formatting and context"
                                    }
                                },
                                "required": ["type", "content"]
                            }
                        }
                    },
                    "required": ["messages"]
                }
            },
            {
                "name": "add_knowledge",
                "description": """KNOWLEDGE BASE STORAGE - Add documents and factual information to the knowledge base.

WHEN TO USE:
- User provides documents, articles, or reference materials
- You need to store factual information for future retrieval
- User shares important specifications, documentation, or guides
- Building a personal knowledge repository

HOW IT WORKS:
- Processes and indexes documents with semantic embeddings
- Stores in dedicated Knowledge Base tier for factual retrieval
- Supports rich metadata for categorization and organization
- Enables precise document-based question answering

WHY USE THIS:
- Creates persistent knowledge repository beyond conversations
- Enables fact-based responses with source attribution
- Supports document Q&A and reference lookup
- Essential for professional and educational use cases

PARAMETERS:
- content: Document text content
- metadata: Optional metadata (title, source, type, tags, etc.)

RETURNS: Confirmation of storage with document ID and processing details.""",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Document content to store in knowledge base"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata for organization and retrieval",
                            "properties": {
                                "title": {"type": "string", "description": "Document title"},
                                "source": {"type": "string", "description": "Source URL or reference"},
                                "type": {"type": "string", "description": "Document type (article, spec, guide, etc.)"},
                                "tags": {"type": "array", "items": {"type": "string"}, "description": "Categorization tags"},
                                "author": {"type": "string", "description": "Document author"},
                                "date": {"type": "string", "description": "Document date"}
                            },
                            "additionalProperties": True
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "get_memory_stats",
                "description": """MEMORY SYSTEM DIAGNOSTICS - Get comprehensive statistics about the memory system state.

WHEN TO USE:
- User asks about memory usage, system status, or available information
- Debugging memory-related issues or performance
- Understanding the scope of stored information
- System health monitoring

HOW IT WORKS:
- Provides detailed statistics across all memory tiers
- Shows embedding model information and performance metrics
- Includes storage usage, item counts, and system health
- Reports on parallel retrieval performance

WHY USE THIS:
- Transparency into memory system operation
- Helps users understand available information scope
- Enables system optimization and troubleshooting
- Provides confidence in memory system reliability

RETURNS: Comprehensive system statistics with tier-by-tier breakdowns, performance metrics, and health indicators.""",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "description": "No parameters required - returns full system statistics"
                }
            }
        ]
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools"""
        return self.tools
    
    async def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""

        if name == "get_memory_context":
            return await self._execute_get_memory_context(args)
        elif name == "add_conversation":
            return await self._execute_add_conversation(args)
        elif name == "add_knowledge":
            return await self._execute_add_knowledge(args)
        elif name == "get_memory_stats":
            return await self._execute_get_memory_stats(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def _execute_get_memory_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory context search with comprehensive metadata"""
        start_time = time.time()
        query = args.get("query", "")
        max_results = args.get("max_results", 50)  # Increased default for comprehensive context

        # Get raw results from parallel memory search
        raw_results = self.memory_service.get_context_for_query(query, max_items=max_results)

        # Enhance results with richer metadata
        enhanced_results = []
        tier_counts = {"working_memory": 0, "active_memory": 0, "archival_memory": 0, "knowledge_base": 0}

        for result in raw_results:
            source = result.get("source", "unknown")
            tier_counts[source] = tier_counts.get(source, 0) + 1

            enhanced_result = {
                "content": result.get("content", ""),
                "source": source,
                "relevance_score": result.get("relevance", 0.0),
                "metadata": {
                    "original_metadata": result.get("metadata", {}),
                    "timestamp": result.get("timestamp", ""),
                    "content_length": len(str(result.get("content", ""))),
                    "content_preview": str(result.get("content", ""))[:200] + "..." if len(str(result.get("content", ""))) > 200 else str(result.get("content", "")),
                    "tier_specific_data": self._get_tier_specific_metadata(result, source)
                }
            }
            enhanced_results.append(enhanced_result)

        processing_time = time.time() - start_time

        return {
            "query": query,
            "results": enhanced_results,
            "summary": {
                "total_results": len(enhanced_results),
                "results_by_tier": tier_counts,
                "processing_time_seconds": processing_time,
                "search_strategy": "parallel_all_tiers",
                "max_requested": max_results,
                "query_timestamp": time.time()
            },
            "recommendations": {
                "high_relevance_count": len([r for r in enhanced_results if r["relevance_score"] > 0.7]),
                "tier_diversity": len([k for k, v in tier_counts.items() if v > 0]),
                "suggested_follow_up": self._suggest_follow_up_searches(enhanced_results, query)
            },
            # Keep backward compatibility
            "count": len(enhanced_results),
            "timestamp": time.time()
        }
    
    async def _execute_add_conversation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add conversation with detailed processing info"""
        start_time = time.time()
        messages = args.get("messages", [])

        processed_messages = []
        for i, msg in enumerate(messages):
            try:
                if msg["type"] == "user":
                    self.memory_service.add_user_message(msg["content"])
                else:
                    self.memory_service.add_assistant_message(msg["content"])

                processed_messages.append({
                    "index": i,
                    "type": msg["type"],
                    "content_length": len(msg["content"]),
                    "status": "stored"
                })
            except Exception as e:
                processed_messages.append({
                    "index": i,
                    "type": msg.get("type", "unknown"),
                    "status": "error",
                    "error": str(e)
                })

        processing_time = time.time() - start_time

        return {
            "status": "success",
            "summary": {
                "messages_added": len([m for m in processed_messages if m["status"] == "stored"]),
                "total_messages": len(messages),
                "processing_time_seconds": processing_time,
                "user_messages": len([m for m in messages if m.get("type") == "user"]),
                "assistant_messages": len([m for m in messages if m.get("type") == "assistant"])
            },
            "processed_messages": processed_messages,
            "memory_state": {
                "working_memory_size": len(self.memory_service.working_memory.get_messages()) if hasattr(self.memory_service, 'working_memory') else 0,
                "conversation_length": len(self.memory_service.current_conversation) if hasattr(self.memory_service, 'current_conversation') else 0
            },
            # Backward compatibility
            "messages_added": len(messages),
            "timestamp": time.time()
        }
    
    async def _execute_add_knowledge(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute add knowledge with comprehensive tracking"""
        start_time = time.time()
        content = args.get("content", "")
        metadata = args.get("metadata", {})

        try:
            # Add to knowledge base
            self.memory_service.add_to_knowledge_base(content, metadata)

            processing_time = time.time() - start_time

            return {
                "status": "success",
                "summary": {
                    "content_length": len(content),
                    "processing_time_seconds": processing_time,
                    "metadata_provided": bool(metadata),
                    "metadata_keys": list(metadata.keys()) if metadata else []
                },
                "document_info": {
                    "content_preview": content[:200] + "..." if len(content) > 200 else content,
                    "estimated_tokens": len(content.split()),  # Rough estimate
                    "metadata": metadata,
                    "storage_tier": "knowledge_base",
                    "indexed_timestamp": time.time()
                },
                "recommendations": {
                    "suggested_tags": self._extract_suggested_tags(content),
                    "content_type": self._detect_content_type(content, metadata),
                    "related_queries": self._suggest_related_queries(content)
                },
                "timestamp": time.time()
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "content_length": len(content),
                "timestamp": time.time()
            }

    async def _execute_get_memory_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get memory statistics with enhanced details"""
        start_time = time.time()

        try:
            # Get base stats from memory service
            if hasattr(self.memory_service, 'get_memory_stats'):
                base_stats = self.memory_service.get_memory_stats()
            elif hasattr(self.memory_service, 'get_statistics'):
                base_stats = self.memory_service.get_statistics()
            else:
                base_stats = {}

            processing_time = time.time() - start_time

            # Enhanced stats with system information
            enhanced_stats = {
                "memory_tiers": base_stats,
                "system_info": {
                    "retrieval_optimization": "parallel_async_enabled",
                    "embedding_models": self._get_embedding_model_info(),
                    "performance_metrics": {
                        "last_query_time": getattr(self.memory_service, 'last_query_time', 0),
                        "stats_generation_time": processing_time,
                        "parallel_retrieval_available": True
                    }
                },
                "usage_insights": {
                    "total_stored_items": self._calculate_total_items(base_stats),
                    "tier_distribution": self._calculate_tier_distribution(base_stats),
                    "storage_efficiency": self._calculate_storage_efficiency(base_stats)
                },
                "capabilities": {
                    "semantic_search": True,
                    "parallel_retrieval": True,
                    "multi_tier_memory": True,
                    "conversation_continuity": True,
                    "document_storage": True,
                    "metadata_support": True
                },
                "timestamp": time.time()
            }

            return enhanced_stats

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "timestamp": time.time()
            }

    def _get_tier_specific_metadata(self, result: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Get tier-specific metadata for enhanced context"""
        tier_data = {"tier": source}

        if source == "working_memory":
            tier_data.update({
                "recency": "current_session",
                "importance": "high",
                "context_type": "immediate"
            })
        elif source == "active_memory":
            tier_data.update({
                "recency": "recent",
                "importance": "medium",
                "context_type": "short_term"
            })
        elif source == "archival_memory":
            tier_data.update({
                "recency": "historical",
                "importance": "contextual",
                "context_type": "long_term"
            })
        elif source == "knowledge_base":
            tier_data.update({
                "recency": "persistent",
                "importance": "factual",
                "context_type": "reference"
            })

        return tier_data

    def _suggest_follow_up_searches(self, results: List[Dict[str, Any]], query: str) -> List[str]:
        """Suggest follow-up searches based on results"""
        suggestions = []

        # If low result count, suggest broader searches
        if len(results) < 3:
            suggestions.append(f"Broader search related to: {query}")

        # If many results from one tier, suggest specific tier searches
        tier_counts = {}
        for result in results:
            tier = result.get("source", "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        dominant_tier = max(tier_counts.items(), key=lambda x: x[1])[0] if tier_counts else None
        if dominant_tier and tier_counts[dominant_tier] > len(results) * 0.7:
            suggestions.append(f"Search other memory tiers for: {query}")

        return suggestions[:3]  # Limit to 3 suggestions

    def _extract_suggested_tags(self, content: str) -> List[str]:
        """Extract suggested tags from content"""
        # Simple keyword extraction - could be enhanced with NLP
        words = content.lower().split()
        common_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        keywords = [word for word in words if len(word) > 3 and word not in common_words]
        return list(set(keywords[:5]))  # Return top 5 unique keywords

    def _detect_content_type(self, content: str, metadata: Dict[str, Any]) -> str:
        """Detect the type of content"""
        content_lower = content.lower()

        if metadata.get("type"):
            return metadata["type"]
        elif "http" in content_lower and ("www" in content_lower or ".com" in content_lower):
            return "url_reference"
        elif content.count("\n") > 10:
            return "document"
        elif "def " in content or "function" in content or "class " in content:
            return "code"
        else:
            return "text"

    def _suggest_related_queries(self, content: str) -> List[str]:
        """Suggest related queries for the content"""
        # Simple approach - could be enhanced with semantic analysis
        content_preview = content[:100].lower()
        suggestions = []

        if "api" in content_preview:
            suggestions.append("API documentation")
        if "function" in content_preview or "method" in content_preview:
            suggestions.append("function implementation")
        if "error" in content_preview or "bug" in content_preview:
            suggestions.append("troubleshooting guide")

        return suggestions

    def _get_embedding_model_info(self) -> Dict[str, Any]:
        """Get embedding model information"""
        try:
            if hasattr(self.memory_service, 'get_embedding_info'):
                return self.memory_service.get_embedding_info()
            elif hasattr(self.memory_service, 'embedding'):
                return {
                    "model_name": getattr(self.memory_service.embedding, 'model_name', 'unknown'),
                    "backend": getattr(self.memory_service.embedding, 'backend', 'unknown')
                }
            else:
                return {"status": "no_embedding_info"}
        except Exception:
            return {"status": "error_retrieving_info"}

    def _calculate_total_items(self, stats: Dict[str, Any]) -> int:
        """Calculate total items across all tiers"""
        total = 0
        for tier_name, tier_data in stats.items():
            if isinstance(tier_data, dict):
                if "items" in tier_data:
                    total += tier_data["items"]
                elif "messages" in tier_data:
                    total += tier_data["messages"]
        return total

    def _calculate_tier_distribution(self, stats: Dict[str, Any]) -> Dict[str, float]:
        """Calculate percentage distribution across tiers"""
        total = self._calculate_total_items(stats)
        if total == 0:
            return {}

        distribution = {}
        for tier_name, tier_data in stats.items():
            if isinstance(tier_data, dict):
                tier_items = tier_data.get("items", tier_data.get("messages", 0))
                distribution[tier_name] = round((tier_items / total) * 100, 1)

        return distribution

    def _calculate_storage_efficiency(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate storage efficiency metrics"""
        return {
            "total_tiers_active": len([t for t, data in stats.items() if isinstance(data, dict) and (data.get("items", 0) > 0 or data.get("messages", 0) > 0)]),
            "average_tier_utilization": "calculated_based_on_usage",
            "memory_balance": "distributed" if len(stats) > 1 else "concentrated"
        }
