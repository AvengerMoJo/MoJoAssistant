# MoJoAssistant Onboarding Guide

**Version:** 1.4.0  
**Last Updated:** 2026-05-05  
**Audience:** New users and developers

---

## Welcome to MoJoAssistant

MoJoAssistant is a **local-first AI assistant platform** that keeps your memory, context, and workflow state on your own machine. It's not just another chatbot — it's a team of specialized AI agents that work together to help you accomplish complex tasks.

### Core Philosophy

- **Privacy-first**: All data stays on your machine
- **Agent-based**: Specialized roles for different tasks
- **Autonomous**: Agents can work 24/7 with human oversight
- **Memory-driven**: Experiences compound into institutional knowledge

---

## The Agent Team

| Agent | Role | Specialty |
|-------|------|-----------|
| **Alex** | Owner | You — the human in the loop |
| **Paul** | Product Manager | PRD creation, agent coordination |
| **PoPo** | Coding Specialist | Implementation, small capabilities |
| **Ahman** | Infrastructure Guardian | Sandbox, Docker, security |
| **Bao** | Browser Operator | Web automation, Playwright |
| **Scott** | Researcher | News, market analysis |
| **Rebecca** | Researcher | Deep research, comparative analysis |

---

## Module Spotlight: Dreaming

The **Dreaming Module** is MoJoAssistant's memory consolidation system. It transforms raw conversations into structured, searchable knowledge.

### How Dreaming Works

```
Raw Conversation → Chunks → Clusters → Archive → Knowledge Base
     (A)              (B)       (C)        (D)          (E)
```

**Stage A: Input**
- Raw conversation text or document

**Stage B: Chunking**
- Semantic chunking into meaningful segments
- Entity extraction, key fact identification

**Stage C: Synthesis**
- Clusters chunks by theme
- Extracts patterns, relationships, insights

**Stage D: Archival**
- Versioned storage with lineage tracking
- Hot/cold storage management

**Stage E: Knowledge Base**
- Indexed into searchable vector store
- Accessible via `memory_search` and `_orient_from_memory`

### Why Dreaming Matters

Without dreaming:
- Conversations dissolve into raw text
- Patterns are lost
- Agents start fresh every time

With dreaming:
- Experiences become institutional knowledge
- Patterns emerge across conversations
- Agents learn from past successes and failures

---

## Case Study: Optimizing Dreaming with Paul

Let's see how Paul (Product Manager) can use the agent team to optimize the dreaming module.

### Step 1: Paul Creates a PRD

Paul identifies that dreaming quality could be improved by:
1. Better chunking algorithms
2. More sophisticated synthesis
3. Cross-session pattern detection

### Step 2: PoPo Implements

PoPo (Coding Specialist) implements the improvements:
- Enhanced chunking with NLP
- Theme-aware synthesis
- Pattern extraction across sessions

### Step 3: Scott Validates

Scott (Researcher) benchmarks the improvements:
- Compares old vs new quality metrics
- Measures search accuracy improvement
- Documents findings

### Step 4: Alex Reviews

Alex (You) reviews the PR and merges when satisfied.

---

## Getting Started

### 1. Installation

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
./scripts/install.sh
```

### 2. Configuration

```bash
cp .env.example .env
# Edit .env with your API keys and preferences
```

### 3. Start the Server

```bash
# HTTP mode (recommended)
python unified_mcp_server.py --mode http --port 8000

# Or as a service
./scripts/install_service.sh
```

### 4. Access the Dashboard

Open `http://localhost:8000/dashboard` in your browser.

---

## Key Concepts

### Memory Tiers
1. **Working** — Current conversation context
2. **Active** — Recent interactions, searchable
3. **Archival** — Historical records, compressed
4. **Knowledge** — Distilled insights, patterns

### Roles & Capabilities
Each role has specific capabilities (tools it can use) and NineChapter dimensions that define its personality.

### Policy Pipeline
Every tool call passes through safety checkers before execution:
- Static rules (denied tools, allowed tools)
- Content patterns (credentials, C2, exfiltration)
- Data boundary (local_only enforcement)
- Context awareness (violation history)

### Bonsai Growth
Assistants evolve through:
1. **Growth** — Memory accumulation
2. **Direction** — One-on-one calibration
3. **DNA** — Dream-driven personality updates
4. **Presentation** — HITL validation

---

## Next Steps

1. **Explore the dashboard** — See your agents in action
2. **Run a test task** — Try dispatching to different agents
3. **Customize your roles** — Edit `~/.memory/roles/{role_id}.json`
4. **Set up notifications** — Configure ntfy for push alerts
5. **Read the architecture docs** — Understand the full system

---

*This guide was created by the MoJoAssistant agent team.*
