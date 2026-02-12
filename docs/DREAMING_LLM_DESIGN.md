# Dreaming LLM Integration Design

## Overview

Dreaming pipeline uses LLMs for semantic chunking, with tiered quality levels and progressive enhancement. LLM provider is configured at runtime via task resources, allowing MCP thinking model to optimize for cost/quality.

## Resource Tiers

### Tier 1: Local/Free (Always Available)
```json
{
  "llm_provider": "local",
  "max_tokens": null,
  "model": "llama-3.2-3b"
}
```
- **Cost:** Free (local compute only)
- **Speed:** Fast (~1-2s per conversation)
- **Quality:** Basic (70-80% accuracy)
- **Use Case:** Initial processing, always runs
- **Output:** `quality_level = "basic"`, `needs_upgrade = true`

### Tier 2: Fixed Budget (If Available)
```json
{
  "llm_provider": "anthropic",
  "max_tokens": 50000,
  "model": "claude-haiku-3-5"
}
```
- **Cost:** From existing API quota (leftover tokens)
- **Speed:** Medium (~3-5s per conversation)
- **Quality:** Good (85-95% accuracy)
- **Use Case:** Upgrade low-quality chunks when budget available
- **Output:** `quality_level = "good"`, `needs_upgrade = false`

### Tier 3: Premium (Extra Cost)
```json
{
  "llm_provider": "anthropic",
  "max_tokens": 100000,
  "model": "claude-sonnet-4-5"
}
```
- **Cost:** Dedicated dreaming budget (user-approved)
- **Speed:** Slower (~5-10s per conversation)
- **Quality:** Premium (95-99% accuracy)
- **Use Case:** Critical data, user-requested upgrades
- **Output:** `quality_level = "premium"`, `needs_upgrade = false`

## LLM Provider Interface

### Universal Chunking Prompt

Works across languages (English, Chinese, mixed) and providers (Anthropic, OpenAI, Local):

```
You are a semantic analysis expert. Analyze the following conversation and break it into meaningful semantic chunks.

CONVERSATION:
{conversation_text}

INSTRUCTIONS:
1. Identify natural semantic boundaries (topic shifts, speaker turns, logical breaks)
2. Each chunk should be 100-800 tokens
3. Extract metadata for each chunk:
   - labels: List of topic tags (e.g., ["technical", "architecture", "billing"])
   - speaker: Who is speaking (user/assistant/system)
   - entities: Named entities mentioned (people, products, concepts)
   - summary: One-sentence summary of the chunk

IMPORTANT:
- Preserve the ORIGINAL language of each chunk (do not translate)
- Multi-lingual conversations: Keep each language as-is
- Detect language per chunk: "zh", "en", "ja", etc.

OUTPUT FORMAT (JSON):
{
  "chunks": [
    {
      "content": "<original text, unchanged>",
      "language": "<detected language code>",
      "labels": ["<tag1>", "<tag2>"],
      "speaker": "<user|assistant|system>",
      "entities": ["<entity1>", "<entity2>"],
      "summary": "<one-sentence summary>"
    }
  ]
}

Return ONLY valid JSON, no additional text.
```

### Provider Configuration

```python
class LLMProvider:
    """Abstract LLM provider interface"""

    async def chunk_conversation(
        self,
        text: str,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Chunk conversation using LLM

        Args:
            text: Conversation to chunk
            max_tokens: Budget limit (if applicable)

        Returns:
            Parsed JSON response with chunks
        """
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider"""

    def __init__(self, model: str = "claude-haiku-3-5"):
        self.model = model
        self.client = anthropic.Anthropic()

    async def chunk_conversation(self, text: str, max_tokens: Optional[int] = None):
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or 4096,
            messages=[{"role": "user", "content": CHUNKING_PROMPT.format(text=text)}]
        )
        return json.loads(response.content[0].text)


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.client = openai.OpenAI()

    async def chunk_conversation(self, text: str, max_tokens: Optional[int] = None):
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens or 4096,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": CHUNKING_PROMPT.format(text=text)}]
        )
        return json.loads(response.choices[0].message.content)


class LocalProvider(LLMProvider):
    """Local LLM provider (llama.cpp, ollama, etc.)"""

    def __init__(self, model: str = "llama-3.2-3b"):
        self.model = model
        # TODO: Initialize local model client

    async def chunk_conversation(self, text: str, max_tokens: Optional[int] = None):
        # TODO: Call local model with same prompt
        # For now, fallback to rule-based
        return self._rule_based_fallback(text)
```

## Task Resource Configuration

### Task Creation with Resources

```python
# Scheduler task configuration
task = Task(
    id="dreaming_daily",
    type=TaskType.DREAMING,
    priority=TaskPriority.MEDIUM,
    config={
        "mode": "full_day",  # Process entire day
        "target_date": "2026-02-13"
    },
    resources=TaskResources(
        llm_provider="anthropic",  # or "openai", "local"
        model="claude-haiku-3-5",  # Specific model
        max_tokens=50000,  # Budget limit
        max_duration_seconds=300  # 5 minutes timeout
    )
)
```

### Runtime Provider Selection

```python
# MCP thinking model decides at runtime
def select_llm_provider(
    budget_available: int,
    quality_required: str,
    time_available: int
) -> TaskResources:
    """
    Select optimal LLM provider based on constraints

    Logic:
    - If budget_available == 0: Use local
    - If quality_required == "premium": Use Sonnet (if budget allows)
    - If time_available < 60s: Use Haiku (faster)
    - Default: Use Haiku for cost efficiency
    """
    if budget_available == 0:
        return TaskResources(llm_provider="local", max_tokens=None)

    elif quality_required == "premium" and budget_available > 100000:
        return TaskResources(
            llm_provider="anthropic",
            model="claude-sonnet-4-5",
            max_tokens=100000
        )

    else:
        return TaskResources(
            llm_provider="anthropic",
            model="claude-haiku-3-5",
            max_tokens=budget_available
        )
```

## B Chunk Quality Tracking

### Extended BChunk Model

```python
@dataclass
class BChunk:
    # ... existing fields ...

    # Quality tracking
    quality_level: str = "basic"  # basic/good/premium
    needs_upgrade: bool = True
    llm_used: Optional[str] = None  # e.g., "claude-haiku-3-5"
    llm_provider: Optional[str] = None  # e.g., "anthropic"
    language: Optional[str] = None  # Detected language: "en", "zh", "ja"

    # Cost tracking
    tokens_used: int = 0
    processing_time_ms: int = 0
```

### Quality Level Semantics

```python
QUALITY_LEVELS = {
    "basic": {
        "accuracy": "70-80%",
        "cost": "free",
        "needs_upgrade": True,
        "description": "Rule-based or local LLM, may miss nuances"
    },
    "good": {
        "accuracy": "85-95%",
        "cost": "low ($0.001-0.01)",
        "needs_upgrade": False,
        "description": "Cloud LLM (Haiku/Mini), reliable for most cases"
    },
    "premium": {
        "accuracy": "95-99%",
        "cost": "medium ($0.01-0.10)",
        "needs_upgrade": False,
        "description": "Best model (Sonnet/Opus), highest accuracy"
    }
}
```

## Progressive Enhancement Workflow

### Stage 1: Initial Processing (Always Runs)

```python
# Nightly dreaming task (3 AM)
task_initial = Task(
    id="dreaming_daily_initial",
    type=TaskType.DREAMING,
    priority=TaskPriority.MEDIUM,
    schedule=datetime(2026, 2, 14, 3, 0, 0),
    config={
        "mode": "full_day",
        "stage": "initial"
    },
    resources=TaskResources(
        llm_provider="local",  # Free tier
        max_tokens=None
    )
)

# Output:
# - All conversations chunked with quality_level="basic"
# - needs_upgrade=true for all chunks
# - Memory is immediately searchable (better than nothing)
```

### Stage 2: Upgrade Tasks (If Budget Available)

```python
# Check remaining API quota
remaining_tokens = check_api_quota()  # e.g., 50000 tokens left this month

if remaining_tokens > 10000:
    # Create upgrade task
    task_upgrade = Task(
        id="dreaming_upgrade_basic_to_good",
        type=TaskType.DREAMING,
        priority=TaskPriority.LOW,  # Lower priority than initial
        schedule=datetime(2026, 2, 14, 4, 0, 0),  # Run after initial
        config={
            "mode": "upgrade",
            "filter": "quality_level=basic AND needs_upgrade=true",
            "target_quality": "good",
            "limit": 100  # Upgrade up to 100 chunks
        },
        resources=TaskResources(
            llm_provider="anthropic",
            model="claude-haiku-3-5",
            max_tokens=remaining_tokens
        )
    )
```

### Stage 3: Premium Upgrades (User-Requested)

```python
# User asks: "Improve quality of my billing architecture memories"
task_premium = Task(
    id="dreaming_upgrade_billing_premium",
    type=TaskType.DREAMING,
    priority=TaskPriority.HIGH,
    config={
        "mode": "upgrade",
        "filter": "labels CONTAINS 'billing' AND quality_level != 'premium'",
        "target_quality": "premium"
    },
    resources=TaskResources(
        llm_provider="anthropic",
        model="claude-sonnet-4-5",
        max_tokens=100000  # Dedicated budget
    )
)
```

## Cost Tracking & Budget Management

### Per-Task Cost Recording

```python
@dataclass
class DreamingTaskResult:
    """Result of dreaming task execution"""

    # Chunks processed
    chunks_created: int
    chunks_upgraded: int

    # Quality distribution
    quality_counts: Dict[str, int]  # {"basic": 50, "good": 30, "premium": 5}

    # Cost tracking
    tokens_consumed: int
    estimated_cost_usd: float
    processing_time_seconds: float

    # Provider used
    llm_provider: str
    llm_model: str
```

### Budget Enforcement

```python
class DreamingExecutor:
    async def execute_with_budget(
        self,
        conversations: List[str],
        max_tokens: int
    ) -> DreamingTaskResult:
        """
        Execute dreaming with token budget enforcement

        Stops when:
        - All conversations processed
        - max_tokens reached
        - Time limit exceeded
        """
        tokens_used = 0
        results = []

        for conversation in conversations:
            if tokens_used >= max_tokens:
                self._log(f"Budget exhausted: {tokens_used}/{max_tokens} tokens")
                break

            # Estimate tokens needed
            estimated_tokens = len(conversation.split()) * 1.5  # Rough estimate

            if tokens_used + estimated_tokens > max_tokens:
                self._log(f"Skipping conversation (would exceed budget)")
                continue

            # Process conversation
            result = await self.chunker.chunk_conversation(
                conversation,
                llm_provider=self.llm_provider,
                max_tokens=int(estimated_tokens)
            )

            tokens_used += result.tokens_used
            results.append(result)

        return DreamingTaskResult(
            chunks_created=len(results),
            tokens_consumed=tokens_used,
            estimated_cost_usd=tokens_used * COST_PER_TOKEN[self.llm_provider]
        )
```

## Example: Complete Dreaming Flow

```python
# Day 1: Initial processing with local LLM (free)
dreaming_initial = await scheduler.execute_task(Task(
    id="dreaming_2026_02_13",
    type=TaskType.DREAMING,
    resources=TaskResources(llm_provider="local")
))
# Result: 100 conversations → 500 B chunks (quality="basic")

# Day 2: API quota check shows 50k tokens available
remaining = check_anthropic_quota()  # 50000 tokens

if remaining > 10000:
    dreaming_upgrade = await scheduler.execute_task(Task(
        id="dreaming_upgrade_2026_02_13",
        type=TaskType.DREAMING,
        config={"mode": "upgrade", "filter": "needs_upgrade=true", "limit": 50},
        resources=TaskResources(
            llm_provider="anthropic",
            model="claude-haiku-3-5",
            max_tokens=50000
        )
    ))
    # Result: 50 chunks upgraded (quality="basic" → "good")
    # Tokens used: 45000
    # Cost: ~$0.05

# Day 30: User requests premium upgrade for important topics
dreaming_premium = await scheduler.execute_task(Task(
    id="dreaming_premium_billing",
    type=TaskType.DREAMING,
    config={
        "mode": "upgrade",
        "filter": "labels CONTAINS 'billing' OR labels CONTAINS 'architecture'",
        "target_quality": "premium"
    },
    resources=TaskResources(
        llm_provider="anthropic",
        model="claude-sonnet-4-5",
        max_tokens=100000
    )
))
# Result: 20 chunks upgraded (quality="good" → "premium")
# Tokens used: 80000
# Cost: ~$2.40
```

## Future: MCP Thinking Model Integration

```python
# MCP thinking model analyzes context and picks optimal provider
class MCPThinkingOptimizer:
    def select_dreaming_resources(
        self,
        conversations_count: int,
        user_budget: float,
        urgency: str,
        quality_requirements: Dict[str, str]
    ) -> TaskResources:
        """
        AI-driven resource selection

        Considers:
        - User's monthly budget vs. spending so far
        - Importance of conversations (mentioned in recent queries?)
        - Time constraints (EOD deadline vs. background processing)
        - Quality requirements per topic
        """

        # Think through tradeoffs
        if urgency == "high" and user_budget > 10:
            # User needs results now, budget allows
            return TaskResources(
                llm_provider="anthropic",
                model="claude-sonnet-4-5",
                max_tokens=200000
            )

        elif conversations_count < 10:
            # Small batch, worth using good quality
            return TaskResources(
                llm_provider="anthropic",
                model="claude-haiku-3-5",
                max_tokens=50000
            )

        else:
            # Large batch, start with free tier
            return TaskResources(
                llm_provider="local",
                max_tokens=None
            )
```

## Implementation Priority

1. **Phase 1 (Current):** Basic LLM integration
   - Implement provider interface (Anthropic, OpenAI, Local)
   - Universal chunking prompt
   - Quality tracking in B chunks
   - Cost tracking

2. **Phase 2:** Progressive enhancement
   - Upgrade task logic
   - Budget enforcement
   - Quality filtering

3. **Phase 3:** MCP thinking integration
   - AI-driven provider selection
   - Dynamic budget allocation
   - Quality optimization

## Summary

- **Provider-agnostic:** Works with any LLM (Anthropic, OpenAI, Local)
- **Multi-language:** Preserves original language, no translation
- **Tiered quality:** basic → good → premium (progressive enhancement)
- **Cost-aware:** Budget tracking, token limits, cost estimation
- **Runtime configuration:** MCP thinking model picks provider dynamically
- **Graceful degradation:** Always works (falls back to local/free)
