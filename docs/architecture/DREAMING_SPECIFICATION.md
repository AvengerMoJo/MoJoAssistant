# Dreaming Specification - Memory Consolidation System

## Overview

Dreaming is a memory consolidation pipeline that reconstructs long-term memory to be 100% accurate. It processes raw conversation data (A), breaks it into semantic chunks with metadata (B), synthesizes a global view (C), and archives old data (D).

## Why Dreaming is Needed

**Current Limitations:**
1. Search is limited to 4000 tokens of context
2. Old conversations lose relevance over time
3. Duplicate memories dilute search results
4. No relationships between different conversations
5. Metadata is basic (just timestamps)

**Goal:** Transform raw conversations into a "perfect" knowledge base where:
- Every relevant fact is discoverable
- Relationships are explicit and navigable
- No contradictions exist
- Search results are always 100% accurate

## Data Model

### Physical Storage Architecture (Recommended)

Use a file-first architecture with DuckDB as the query layer:

1. Append-only JSON archives by conversation/version:
   - `~/.memory/dreams/<conversation_id>/archive_v<version>.json`
2. No separate indexing server or index service.
3. DuckDB reads JSON files directly for OLAP and retrieval views.
4. Existing embedding stores remain in place for semantic recall.
5. Retrieval policy:
   - semantic retrieval via embeddings first
   - structural filtering/ranking via DuckDB metadata (`status`, `storage_location`, `version`)

This keeps operations simple while preserving full history and enabling precise latest/historical queries.

### Hierarchy

```
┌─────────────────────────────────────────┐
│ A: Raw Data (Source of Truth)     │
│ - Today's full conversations           │
│ - 4000-token chunks                 │
│ - As retrieved from memory           │
│                                     │
│ ↓ Dreaming Process                   │
│                                     │
├─────────────────────────────────────────────┤
│ B: Deconstructed Data                 │
│ - Semantic chunks with metadata       │
│ - Rich context labels                 │
│ - Embedding vectors for search        │
│                                     │
│ ↓ (Continuous)                       │
│                                     │
├─────────────────────────────────────────────┤
│ C: Synthesized Data                 │
│ - Global consolidated view           │
│ - Relationships and clusters          │
│ - Cross-conversation patterns        │
│ - Metadata enrichment               │
│                                     │
│ ↓ (Periodic, e.g., nightly)     │
│                                     │
├─────────────────────────────────────────────┤
│ D: Archived Data                    │
│ - Superseded information              │
│ - Versioned pointers               │
│ - Removed embeddings (not searched)  │
│ - Historical traceability              │
│                                     │
└─────────────────────────────────────────────┘
```

### A: Raw Data Structure

**Format:** JSON (existing memory format)

**Content:**
- Full conversation text (within 4000 tokens)
- Timestamps
- Conversation metadata (participants, source)
- Raw as retrieved from memory system

**Example:**
```json
{
  "id": "conv_20250209_001",
  "timestamp": "2025-02-09T10:30:00Z",
  "content": "<full conversation text up to 4000 tokens>",
  "metadata": {
    "source": "conversation",
    "token_count": 3950,
    "participants": ["user", "assistant"],
    "embedding": "<vector>"  // Already computed
  }
}
```

### B: Deconstructed Data

**Purpose:** Break full conversations into semantic pieces with rich metadata.

**Chunking Strategy:**
- **Semantic boundaries** (topics, paragraphs, speaker turns)
- **Context labels** (what is this about? project? feature request?)
- **Speaker attribution** (who said this?)
- **Temporal tags** (time of day, phase of project)
- **Entity extraction** (people, organizations, technical terms)

**B Chunk Examples:**

```json
{
  "id": "chunk_b_001",
  "parent_id": "conv_20250209_001",
  "type": "semantic",
  "content": "We discussed the API architecture for the billing system.",
  "metadata": {
    "labels": ["billing", "architecture", "api"],
    "speaker": "assistant",
    "entities": ["API", "billing system", "architecture"],
    "confidence": 0.92,
    "token_range": [100, 150],
    "position_in_parent": 0.025,
    "embedding": "<new vector>"  // Re-computed
  }
}
```

**B Chunk Properties:**
- `labels` - List of tags for categorization (array)
- `speaker` - Who said this (user/assistant/system)
- `entities` - Named entities mentioned (array)
- `confidence` - AI confidence in this analysis (0-1)
- `token_range` - Position in parent conversation
- `position_in_parent` - Relative position (0-1)
- `embedding` - Vector for semantic search (re-computed)
- `parent_id` - Link back to source A chunk

**B Chunk Types:**
1. `semantic` - Topic/idea boundaries
2. `speaker_turn` - Each speaker's contribution
3. `entity` - Named entity occurrence
4. `relationship` - Connection between entities

### C: Synthesized Data

**Purpose:** Global consolidated view combining all B chunks.

**Content:**
- Cross-conversation connections
- Topic clusters and themes
- Relationship graphs
- Summarized patterns
- Contradiction resolution

**C Examples:**

```json
{
  "id": "cluster_c_billing_architecture",
  "type": "cluster",
  "content": "Billing system architecture discussions across all conversations",
  "metadata": {
    "theme": "system design",
    "related_chunks": ["chunk_b_001", "chunk_b_042", "chunk_b_155"],
    "participants": ["user", "assistant"],
    "time_span": {
      "start": "2025-01-15T09:00:00Z",
      "end": "2025-02-09T10:00:00Z"
    },
    "confidence": 0.87,
    "contradictions_resolved": ["previous billing API vs new billing API"],
    "embedding": "<consolidated vector>"
  }
}
```

**C Data Types:**
1. `cluster` - Grouped by topic/theme
2. `relationship` - Explicit connections (A knows B)
3. `summary` - High-level overview
4. `timeline` - Chronological progression

### D: Archived Data

**Purpose:** Store old/superseded data with versioning, not deletion.

**Content:**
- Pointers to old versions
- Archive metadata
- Reason for archival (outdated, duplicate, merged)
- Removal from hot search
- Version lineage (`previous_version`, `supersedes_version`)
- Lifecycle state (`status`, `storage_location`)

**D Examples:**

```json
{
  "id": "archive_v1_billing_architecture",
  "type": "archive",
  "status": "superseded",
  "reason": "Merged into cluster_c_billing_architecture_v2",
  "metadata": {
    "archived_at": "2025-02-09T10:00:00Z",
    "new_version_id": "cluster_c_billing_architecture_v2",
    "storage_location": "cold",
    "embedding_removed": true,
    "is_latest": false,
    "previous_version": 1,
    "supersedes_version": 1
  },
  "content": {
    "original_c_id": "cluster_c_billing_architecture",
    "snapshot": "<full C data>",
    "version": 1
  }
}
```

**D Status Types:**
- `superseded` - Replaced by newer version
- `duplicate` - Exact or near-duplicate content
- `obsolete` - Outdated information
- `historical` - Kept for reference only

**Default Retrieval Rule:**
- Latest `active/hot` versions are returned by default.
- `cold/superseded` versions remain queryable for historical reference.

## Dreaming Process Pipeline

### Phase 1: Process A (Today's Data)

**Input:** All A chunks from today

**Steps:**
1. **Load A chunks** - Read today's conversation data
2. **Validate A chunks** - Check embedding vectors exist
3. **Sort by timestamp** - Process in chronological order

**Output:** Ready A chunks for deconstruction

### Phase 2: Deconstruct A → B (Semantic Breakdown)

**Steps:**
1. **Chunk Analysis**
   - Identify semantic boundaries
   - Detect speaker changes
   - Extract named entities
   - Assign topic labels

2. **Metadata Generation**
   - Create rich metadata (labels, entities, confidence)
   - Link to parent A chunk
   - Compute token ranges

3. **Embedding Computation**
   - Generate new vectors for B chunks
   - Store for efficient search

4. **B Storage**
   - Write B chunks to JSON
   - Keep append-only records where possible

**Processing:**
```python
# Process one A chunk at a time (full conversation)
for a_chunk in today_a_chunks:
    # Analyze with LLM
    analysis = analyze_conversation(a_chunk.content)
    
    # Extract semantic pieces
    b_chunks = extract_semantic_chunks(analysis)
    
    # Generate metadata for each B chunk
    for b_chunk in b_chunks:
        b_chunk.metadata = {
            "labels": generate_labels(b_chunk),
            "speaker": detect_speaker(b_chunk),
            "entities": extract_entities(b_chunk),
            "confidence": calculate_confidence(analysis)
        }
        
        # Compute embeddings (may use same LLM)
        b_chunk.embedding = generate_embedding(b_chunk.content)
        
        # Store B chunk
        store_b_chunk(b_chunk)
```

**B Storage Update:**
```python
# For each B chunk, update if similar exists
for new_b_chunk in b_chunks:
    existing_b = find_similar_b(new_b_chunk)
    
    if existing_b:
        # Merge with existing B (extend, don't overwrite)
        existing_b.content = merge_content(existing_b, new_b_chunk)
        existing_b.metadata.labels.extend(new_b.metadata.labels)
        existing_b.entities.extend(new_b.entities)
        update_b_chunk(existing_b)
    else:
        # Create new B chunk
        store_b_chunk(new_b_chunk)
```

### Phase 3: Synthesize B → C (Global View)

**Input:** All B chunks (existing + newly created)

**Steps:**
1. **Cluster Analysis**
   - Find similar B chunks (similarity threshold)
   - Identify themes and topics
   - Group into clusters

2. **Relationship Detection**
   - Find connections across conversations
   - Identify recurring patterns
   - Detect contradictions and resolve them

3. **C Generation**
   - Create cluster summaries
   - Build relationship graphs
   - Enrich with timeline data

4. **C Storage**
   - Write C clusters
   - Preserve lineage metadata
   - Create version pointers

**Processing:**
```python
# Load all B chunks
all_b_chunks = load_all_b_chunks()

# Cluster by similarity
clusters = cluster_by_similarity(all_b_chunks, threshold=0.85)

# Detect relationships
relationships = detect_relationships(all_b_chunks, clusters)

# Generate C
for cluster in clusters:
    c_cluster = {
        "id": f"cluster_{cluster.id}",
        "type": "cluster",
        "content": summarize_cluster(cluster),
        "metadata": {
            "theme": cluster.theme,
            "related_chunks": cluster.chunk_ids,
            "confidence": cluster.avg_confidence,
            "relationships": find_relationships(cluster)
        }
    }
    store_c_cluster(c_cluster)
```

### Phase 4: Archive D (Old Data)

**Input:** C clusters + existing C data

**Steps:**
1. **Identify Superseded Data**
   - Old C clusters that conflict with new ones
   - Duplicate content
   - Outdated information

2. **Create Version Pointers**
   - New C IDs point to superseded old C IDs
   - Maintain traceability

3. **Move to Archive**
   - Remove embeddings from hot search
   - Move to cold storage (D structure)
   - Keep original content for reference
   - Preserve immutable version snapshots

**Archival Logic:**
```python
for old_c in existing_c_data:
    for new_c in newly_created_c_data:
        if is_superseded(old_c, new_c):
            # Create D archive entry
            d_entry = {
                "id": f"archive_v{old_c.version}_{old_c.id}",
                "type": "archive",
                "status": "superseded",
                "reason": f"Replaced by {new_c.id}",
                "new_version_id": new_c.id,
                "content": old_c.to_json()
            }
            store_d_entry(d_entry)
            
            # Remove old C from hot search
            remove_embedding(old_c.embedding)
```

## OLAP Queries (DuckDB)

### Why DuckDB?

**Requirements:**
- JSON storage format
- Fast OLAP queries on JSON files
- No separate database server
- Python-only dependencies
- No dedicated indexing service required

### Storage Layout

```text
~/.memory/
  dreams/
    <conversation_id>/
      archive_v1.json
      archive_v2.json
      archive_v3.json
```

### Retrieval Views (Conceptual)

```sql
-- Latest active version per conversation
SELECT *
FROM dream_archives
WHERE is_latest = true
  AND status = 'active'
  AND storage_location = 'hot';

-- Full history for audit/debug
SELECT *
FROM dream_archives
WHERE conversation_id = ?
ORDER BY version DESC;
```

### Query Templates

**1. Find Related Memories (Context Building)**
```sql
-- Given a conversation, find all related topics
WITH related_topics AS (
  SELECT chunk_id, labels, metadata
  FROM 'b_chunks.json'
  WHERE metadata->>'entities' && array_contains(metadata->>'entities', 'billing')
)
SELECT c.chunk_id, c.theme, c.content, c.confidence
FROM 'c_clusters.json' c
JOIN related_topics rt ON array_contains(c.related_chunks, rt.chunk_id)
WHERE c.confidence > 0.8;
```

**2. Timeline of a Topic (Temporal Analysis)**
```sql
-- Show evolution of a topic over time
SELECT 
    date_trunc('month', A.timestamp) AS month,
    count(*) AS num_discussions,
    avg(B.confidence) AS avg_relevance
FROM 'a_chunks.json' A
WHERE array_contains(A.metadata->>'labels', 'billing')
GROUP BY 1
ORDER BY month;
```

**3. Contradiction Detection**
```sql
-- Find conflicting information
SELECT 
    c1.content AS version_1,
    c2.content AS version_2,
    c1.id AS cluster_1,
    c2.id AS cluster_2
FROM 'c_clusters.json' c1
JOIN 'c_clusters.json' c2 
  ON c1.theme = c2.theme 
WHERE c1.content != c2.content
  AND c1.confidence > 0.7 
  AND c2.confidence > 0.7;
```

**4. Entity Co-occurrence Network**
```sql
-- Find how entities appear together
SELECT 
    unnest(metadata->>'entities') AS entity,
    count(*) AS co_occurrence,
    array_agg(DISTINCT timestamp) AS mentions
FROM 'b_chunks.json'
WHERE metadata->>'entities' IS NOT NULL
GROUP BY entity
ORDER BY co_occurrence DESC
LIMIT 50;
```

## Configuration

### Storage Paths

```env
DREAMING_INPUT_PATH=.memory/conversations/      # A: Raw data
DREAMING_B_PATH=.memory/b_chunks/         # B: Deconstructed
DREAMING_C_PATH=.memory/c_clusters/        # C: Synthesized
DREAMING_D_PATH=.memory/archive/          # D: Archived
DREAMING_LOG_PATH=.memory/dreaming.log
```

### Runtime Settings

```json
{
  "dreaming": {
    "enabled": true,
    "schedule": "0 3 * * *",  // 3 AM daily
    "processing_mode": "full_day",  // Process entire day
    "chunking": {
      "method": "semantic_llm",
      "llm_provider": "local",  // Use local LLM for chunking
      "max_chunk_size": 800,  // tokens per B chunk
      "overlap": 0.1  // 10% overlap
    },
    "clustering": {
      "method": "similarity",
      "threshold": 0.85,
      "min_cluster_size": 3
    },
    "synthesis": {
      "llm_provider": "local",
      "max_c_size": 50  // chunks per cluster
    }
  },
  "archival": {
    "enabled": true,
    "superseded_after": "30 days",  // Archive C after 30 days
    "keep_original": true  // Keep A for reference
    "cold_storage": true  // Remove embeddings from hot search
  },
  "olap": {
    "engine": "duckdb",
    "cache_enabled": true,
    "max_cache_size_mb": 100
  }
}
```

### LLM Provider Configuration

**For Dreaming Process:**
```json
{
  "providers": {
    "chunking": {
      "model": "local",
      "model_path": "/path/to/local/model",
      "temperature": 0.1,  // Low temperature for consistency
      "max_tokens": 4000
    },
    "synthesis": {
      "model": "local",
      "model_path": "/path/to/local/model",
      "temperature": 0.3,  // Higher for creativity
      "max_tokens": 8000
    }
  }
}
```

## API Interface

### CLI Integration

```python
# Dreaming is integrated with MemoryService
from app.memory.memory_service import MemoryService

# Auto-triggered at 3 AM via scheduler
# Can also be triggered manually:
memory_service.trigger_dreaming()
```

### MCP Tools

```python
{
  "name": "dreaming_start",
  "description": "Trigger memory consolidation (Dreaming)",
  "inputSchema": {
    "type": "object",
    "properties": {
      "mode": {
        "type": "string",
        "enum": ["full_day", "incremental"],
        "default": "full_day"
      }
    }
  }
}

{
  "name": "dreaming_status",
  "description": "Check dreaming status and results",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}

{
  "name": "dreaming_config",
  "description": "Configure dreaming behavior",
  "inputSchema": {
    "type": "object",
    "properties": {
      "schedule": {
        "type": "string",
        "description": "Cron expression (e.g., '0 3 * * *')"
      },
      "processing_mode": {
        "type": "string",
        "enum": ["full_day", "incremental", "continuous"]
      }
    }
  }
}
```

## Performance Considerations

### Resource Usage

**Memory:**
- B chunks: ~5KB per chunk (800 tokens ≈ 5-10 chunks per conversation)
- C clusters: ~50KB per cluster
- Embeddings: 1.5KB per 384-dim vector
- Total per 100 conversations: ~50MB

**Compute:**
- Chunking: 1-2 seconds per 800 tokens (local LLM)
- Clustering: 5-10 seconds for 100 chunks
- Synthesis: 10-30 seconds per 50 chunks
- Archival: 1-5 seconds per cluster
- Total per day: ~5-10 minutes (depends on conversation volume)

**Storage:**
- A (raw): ~200KB per day
- B (deconstructed): ~5MB per day
- C (synthesized): ~2.5MB per day
- D (archived): ~1MB per day (after 30-day threshold)
- Growth rate: ~8.5MB per day active use

### Optimization Strategies

**Chunking Optimization:**
- Cache embedding model
- Process chunks in parallel batches
- Reuse embeddings when possible
- Vector quantization (reduce memory)

**Storage Optimization:**
- Compress old A data after 7 days
- Lazy load embeddings only when needed
- Use B+ indexes for fast search
- Archive D to separate file to keep JSON small

**Query Optimization:**
- DuckDB query cache (100MB)
- Materialized views for common queries
- Index on frequently accessed fields
- Limit result sets to top 100

## Error Handling

**Chunking Failures:**
- **Symptom:** LLM returns malformed JSON or fails
- **Recovery:** Use rule-based chunking as fallback
- **Retry:** Up to 3 attempts with different LLM
- **Logging:** Log full LLM prompt and response

**Clustering Failures:**
- **Symptom:** No clusters formed (all singletons)
- **Recovery:** Lower similarity threshold, force minimum clusters
- **Logging:** Document why clustering failed

**Storage Failures:**
- **Symptom:** Disk full, permission errors
- **Recovery:** Retry with backoff, alert user
- **Logging:** Log storage path, available space, permissions

## Testing Strategy

### Unit Tests

```python
def test_chunking():
    # Verify chunks maintain semantic integrity
    assert_chunks_cover_conversation()
    assert_metadata_complete()
    assert_embeddings_valid()

def test_clustering():
    # Verify similar content grouped together
    assert_similar_in_same_cluster()
    assert_different_clusters_different()

def test_synthesis():
    # Verify C captures global patterns
    assert_relationships_detected()
    assert_summaries_accurate()
    assert_no_dangling_references()

def test_archival():
    # Verify D doesn't lose data
    assert_superseded_data_archived()
    assert_pointers_valid()
    assert_embeddings_removed_from_hot_search()
```

### Integration Tests

```python
def test_full_pipeline():
    # Run A→B→C→D pipeline end-to-end
    # Verify search results improve
    # Verify no data corruption
    # Test performance within limits
    assert_pipeline_completes_successfully()
    assert_search_quality_improves()
```

## Migration Path

**From v1.1.0 to v1.2.0:**

1. **Install scheduler module** - `pip install -r requirements.txt`
2. **Configure dreaming** - Set up schedule, LLM provider
3. **Enable in memory service** - Add dreaming integration
4. **Run initial dreaming** - Process existing A data
5. **Verify search improvement** - Test memory accuracy

**Data Migration:**
- Existing A (conversations) remain as-is
- Dreaming creates B, C, D structures
- No breaking changes to memory API
- Backward compatible with current search

## Future Enhancements

**Planned v1.3.0 Features:**
- Real-time dreaming (continuous processing)
- Dreaming triggers (token threshold, new topics)
- Multi-modal dreaming (include images, code)
- User-directed dreaming (ask to analyze specific topics)
- Dreaming visualization (graph of memory)

**Research Topics:**
- Better chunking algorithms (NER, topic modeling)
- Relationship graph algorithms (knowledge graphs)
- Contradiction detection (formal logic)
- Compression techniques for long-term storage
