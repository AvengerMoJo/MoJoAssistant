# MoJoAssistant — Event Pitch Deck Brief
## 10-Minute Intro, Demo & Community Invitation

**Version:** v1.4.1-beta  
**Audience:** Developers, AI enthusiasts, open-source contributors  
**Format:** 10-minute session — 2 min intro · 5 min live demo · 3 min community pitch

---

## 1. The Problem We're Solving

### The Current State of AI Assistants

Most AI assistants today share the same fundamental flaw: they are **black boxes controlled by someone else**.

- Your conversations, your memory, your context — all stored on a third-party cloud
- The model changes without your consent; behavior shifts overnight
- You cannot inspect what the AI knows about you
- You cannot replace the model when a better one arrives
- You cannot add a tool that the vendor hasn't approved
- You are a user, not an owner

### The Deeper Problem: Human Agency

When AI makes decisions for you — scheduling your calendar, drafting your emails, managing your tasks — **who is actually in control?**

If the AI is a black box running on someone else's server, answering to someone else's business model, the honest answer is: not you.

### What We Need Instead

An AI assistant that:
- Runs **locally** — your hardware, your data, your rules
- Has **transparent memory** — you can read, edit, or delete everything it knows
- Keeps **humans in the loop** — you decide what it acts on
- Can be **upgraded component by component** — swap the model, the memory store, the notification system, without breaking anything else
- Is **community-built** — no single vendor controls the roadmap

---

## 2. Introducing MoJoAssistant

**MoJoAssistant** is a local-first, modular AI assistant framework built for human agency and AI safety.

It is not a chatbot. It is an **operating system for AI agents** — a platform where autonomous agents work on your behalf, on your hardware, with your explicit oversight at every step.

### Core Philosophy

> **You own it. You can see it. You can replace any part of it.**

- **Local-first**: runs entirely on your machine; no cloud dependency required
- **Modular**: every component — the LLM, the memory backend, the notification system, the agent roles, the sandbox — is independently replaceable
- **Human-in-the-loop**: agents pause and ask before taking consequential actions
- **Community-driven**: roles, tools, and integrations contributed by the community

### Current Status

MoJoAssistant v1.4.1-beta is production-running on AMD ROCm hardware with:
- Multiple LLM backends (LM Studio, vLLM, Ollama, external APIs)
- 6+ specialized agent roles (researcher, developer, network admin, data monitor, community host, reviewer)
- Persistent memory with dreaming consolidation pipeline
- Human-in-the-loop task management with mobile push notifications
- Dashboard for task monitoring
- Voice pipeline (GLM-4-Voice, FunASR)

---

## 3. The Architecture: Every Box Is Swappable

This is the central message of MoJoAssistant: **modularity is the design, not an afterthought**.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Client Layer                      │
│         (Claude Desktop · Open WebUI · Custom)           │
└─────────────────────────┬───────────────────────────────┘
                          │ MCP Protocol
┌─────────────────────────▼───────────────────────────────┐
│                   MoJoAssistant Core                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
│  │Scheduler │  │ Memory   │  │Dashboard │  │  Push   │  │
│  │& Agents  │  │& Dreaming│  │   UI     │  │Adapters │  │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘  │
└─────────────────────────┬───────────────────────────────┘
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐
│  LLM Backend │  │   Sandbox    │  │  External    │
│  (pluggable) │  │  (pluggable) │  │   Agents     │
│              │  │              │  │  (OpenCode   │
│ LM Studio    │  │ Docker       │  │   Claude     │
│ vLLM/ROCm    │  │ Firecracker  │  │   Code, ...) │
│ Ollama       │  │ gVisor       │  └──────────────┘
│ OpenAI API   │  │ Wasmtime     │
└──────────────┘  └──────────────┘
```

### The Six Swappable Modules

#### Module 1: LLM Backend (Resource Pool)
Any OpenAI-compatible endpoint can power MoJo's agents.

- **Today**: Local Qwen3 35B on LM Studio, vLLM with ROCm/AMD GPU
- **Tomorrow**: Gemma, Mistral, LLaMA, or any future model
- **How**: One JSON entry in `resource_pool.json` — no code changes
- **Demo moment**: Task iteration log shows which model ran each step

#### Module 2: Agent Roles (JSON Personality Files)
A role is a JSON file. Anyone can create one and contribute it.

```json
{
  "id": "researcher",
  "name": "Rebecca",
  "purpose": "Deep research and structured reporting",
  "capabilities": ["web", "memory", "knowledge"],
  "model_preference": "qwen3-35b",
  "system_prompt": "You are Rebecca..."
}
```

- Drop the file in `config/roles/` — the role is immediately available
- The community can contribute roles for their domain: legal research, medical literature, code review, security auditing
- **Demo moment**: `role(action='list')` shows all available personalities; open one JSON file to show how simple it is

#### Module 3: Capability Catalog (Tool Registry)
Every tool an agent can use is declared in `capability_catalog.json`.

- New tool = one catalog entry + implementation
- Capability categories: `memory`, `web`, `browser`, `terminal`, `exec`, `file`, `knowledge`
- Roles declare which categories they need; the scheduler resolves exact tools at runtime
- **Demo moment**: Show the catalog entry for `bash_exec` — one declaration, available to every agent with `terminal` capability

#### Module 4: Push Notification Adapters
Notifications are delivered through adapter classes. Each adapter is independent.

- **Today**: ntfy (self-hosted or ntfy.sh) — works on any phone
- **Add**: Slack, Discord, Telegram, email — implement `PushAdapterBase`, register it
- **Demo moment**: HITL notification arrives on phone via ntfy; tap "View Report" to open dashboard

#### Module 5: Sandbox Providers
Code execution by agents runs inside a sandbox. The sandbox is pluggable.

| Sandbox | Isolation | Best For |
|---------|-----------|----------|
| Docker rootless | Medium | General tasks, GPU workloads |
| Firecracker | Maximum (VM) | Sensitive credential handling |
| gVisor | High (syscall) | Kubernetes-native deployments |
| Wasmtime | WASM-native | Browser-compatible tools |

- **Community opportunity**: Port to new sandboxes; contribute ROCm-optimized containers

#### Module 6: Memory & Knowledge Pipeline
Memory is not a single database — it's a pipeline.

- **Conversations** → `add_conversation` → dreaming pipeline → consolidated KnowledgeUnits
- **Research** → task completion → knowledge base → `knowledge_search` for future tasks
- **Role isolation**: each agent's knowledge is scoped — Rebecca's research stays in Rebecca's store
- **Dreaming**: background pipeline that consolidates raw memories into structured facts overnight
- **Community opportunity**: Contribute new chunkers, synthesizers, embedding models

---

## 4. Human-in-the-Loop: You Stay in Control

The most important safety feature of MoJoAssistant is the **HITL (Human-in-the-Loop) system**.

### How It Works

Agents are designed to pause and ask before:
- Taking actions with high risk (deleting files, spending money, sending messages)
- Encountering genuine ambiguity that requires human judgment
- Exhausting their iteration budget without a clear answer

When an agent pauses:
1. A push notification arrives on your phone (ntfy)
2. You see a clean summary + action buttons: **Continue**, **Stop**, **Reply**
3. Your reply resumes the agent from exactly where it stopped — no restart, no lost context

### Why This Matters

This is not a safety guardrail bolted on as an afterthought. It is the **core interaction model**:

> Agents work autonomously on the easy parts. They defer to you on the hard parts. You are always the decision-maker.

This design scales. As models improve, agents need fewer interruptions. But the human override channel is always there — it never goes away.

---

## 5. Live Demo Script (5 Minutes)

### Setup (before demo)
- MoJoAssistant running as systemd user service
- LM Studio loaded with Qwen3 35B
- Dashboard open in browser
- ntfy app open on phone

### Demo Flow

**Step 1 — Dispatch a task (30 seconds)**
```
User (in Claude Desktop): 
"Ask the researcher to find the top 3 open source projects 
that emerged this month in the AI agent space"
```
MoJo dispatches `scheduler(action='add', role_id='researcher', ...)` automatically.
Show: task appears in dashboard with status "running".

**Step 2 — Show it's running locally (30 seconds)**
Open dashboard. Show the iteration log: each row shows the model name (`qwen/qwen3.5-35b`), resource (`lmstudio_qwen35b`), tools called, time elapsed. "This is running on this laptop. No cloud. No API key needed for this step."

**Step 3 — HITL pause (60 seconds)**
Researcher needs clarification: "Should I focus on GitHub stars or real-world deployment signals?"
Notification arrives on phone. Show the phone screen — clean message: "? Should I focus on GitHub stars or real-world deployment signals?"
Tap "Reply" → type "GitHub stars, last 30 days" → task resumes.

**Step 4 — Result in dashboard (60 seconds)**
Task completes. Dashboard shows:
- Final answer with top 3 projects
- Collapsible sections: findings, tool calls, metadata
- Duration, iterations, model used
"Every task is logged. Fully transparent. You can audit every tool call the agent made."

**Step 5 — Show the role (30 seconds)**
Open `config/roles/researcher.json` in a text editor.
"This is all it takes to define an AI personality. A JSON file. Anyone in the community can write one. We already have 6 roles — researcher, developer, network admin, code reviewer, community host, data monitor."

**Step 6 — Show the model swap (30 seconds)**
"What if Qwen3 gets replaced by something better next month? We change one line in resource_pool.json. Every agent immediately uses the new model. No code changes."

---

## 6. What's Already Working (v1.4.1-beta)

### Core Infrastructure ✅
- Scheduler daemon with priority queues and retry logic
- Agentic executor with tool-calling loop (supports Qwen3, Gemma, Mistral, any OpenAI-compatible model)
- Loop detection — agent self-corrects if it gets stuck calling the same tool repeatedly
- Capability gap checker — pre-flight validation before task starts
- Human-in-the-loop with ask_user, push notifications, reply_to_task

### Memory System ✅
- Persistent memory across sessions
- Dreaming pipeline for memory consolidation overnight
- Role-isolated knowledge base
- `get_context` syncs today's date, recent memory, attention inbox at session start

### Role System ✅
- 6 production roles: researcher, developer (Popo), network admin (Ahman), code reviewer, community host, data monitor
- Role design wizard — describe a personality, MoJo builds the JSON
- Capability-based tool access (roles declare needs, system resolves tools)

### Dashboard ✅
- Task list with status badges (completed / failed / waiting)
- Task detail with iteration log per step
- Role chat interface

### Notifications ✅
- ntfy push adapter (self-hosted or ntfy.sh)
- HITL action buttons: Continue / Stop / Reply
- Deep link to task report

### Voice Pipeline ✅ (experimental)
- GLM-4-Voice S2S (Speech-to-Speech) pipeline
- FunASR speech recognition
- Two-brain architecture: fast voice conductor + deep MCP brain running in parallel

### Developer Experience ✅
- Doctor script (`scripts/doctor.py`) validates installation, model connections, all modules
- `--fix` mode walks through setup interactively
- Stable/experimental test markers
- MCP server for Claude Desktop, Open WebUI, any MCP-compatible client

---

## 7. Roadmap: What's Next

### Near Term (next 2 months)

**Bridle — Multi-Agent Communication**

Today, agents coordinate through an orchestrator who explicitly writes the wiring into each goal. Bridle is the layer that makes coordination emergent.

```
TODAY:
  Orchestrator tells Rebecca: "if you hit a technical claim, dispatch to Anna"
  Rebecca dispatches. Wire works. But orchestrator has to say this every time.

NEAR TERM (Bridle wire):
  dispatch_subtask(consult=True) — lightweight peer consult, no task overhead
  collaboration map in role JSON — Rebecca knows to ask Anna for feasibility questions
  Orchestrators write negotiation recipes, not custom code

LONG TERM (Bonsai trigger):
  After Rebecca's report fails cross-verification on a technical claim,
  Bonsai adds Anna to Rebecca's collaboration map.
  Next time: Rebecca self-triggers without being told.
```

The wire enables communication. Bonsai teaches the agent WHEN to use it.

Three communication patterns that emerge without new plugins:
- **Peer-to-Peer**: `dispatch_subtask(consult=True)` — ask a peer mid-task, one LLM call, no scheduler overhead
- **Negotiation**: orchestrator loop over consult calls — structured ACCEPT/COUNTER/REJECT convergence
- **Broadcast**: `add_conversation(scope='framework')` already works for knowledge sharing; `broadcast_capability` for tool catalog changes

**Bonsai self-regulation**: agents auto-calibrate iteration budgets AND collaboration patterns from historical performance. The system gets more efficient and more cooperative over time — without human tuning.

**One-on-one growth sessions**: weekly check-in between owner and each role — what did you learn, where are you stuck, what collaborations would help you?

**Sandbox orchestration**: route tasks to Docker, Firecracker, or gVisor based on declared isolation needs.

### Medium Term (3–6 months)
- **Self-hosted mesh VPN**: agents register nodes, get stable `*.mojo.internal` hostnames — no port forwarding, no cloud relay
- **Coding agent integration**: OpenCode / Claude Code as first-class scheduler tasks — MoJo owns the task queue, coding agents own the implementation
- **Voice first-class citizen**: voice sessions as the primary interaction mode, not a side experiment
- **Community role marketplace**: submit a role, get it reviewed, ship it to everyone

### Long Term Vision
MoJoAssistant becomes the **operating system layer** between humans and AI:
- You own the memory, the agents, the rules
- Models improve underneath you — you upgrade without losing context
- Community builds the capabilities — you choose what to install
- Agents learn to cooperate — Bonsai grows the collaboration graph from real task outcomes
- Human agency is the invariant — AI capability is the variable

---

## 8. Community Contribution Model

### Why Contribute?

MoJoAssistant is built on a simple bet: **the best AI assistant won't be designed by one team**. It will be assembled from contributions by people who understand their own domains better than any vendor ever will.

A security researcher knows what a security audit role needs better than we do.
A physician knows what a medical literature role should prioritize.
A trader knows what a market monitor role should watch.

The framework is the contribution. The roles, tools, and integrations are yours to build.

### How to Contribute

**Easiest entry points:**
1. **Write a role** — a JSON file defining a new agent personality for your domain
2. **Add a capability** — wire a new tool into the capability catalog
3. **Build a push adapter** — Slack, Discord, Telegram, email
4. **Write a workflow template** — teach a role WHEN to communicate with peers, not just HOW
5. **Improve a module** — better chunker for the dreaming pipeline, new sandbox provider, faster embedding model

**Bridle communication patterns** — well-scoped, documented, community-owned:
- `dispatch_subtask(consult=True)` — one parameter, depth-limit bypass, ephemeral execution
- `broadcast_capability` — single new tool, pure data write, no LLM
- Collaboration map injection — role JSON field + one executor change
- Negotiation recipe — workflow template, no code required

**Harder but high-impact:**
- Bonsai integration — wire the self-regulation engine into the executor; teach it to generate collaboration map entries from task failure signals
- Voice pipeline improvements — better STT/TTS models, lower latency
- Sandbox routing — Docker/Firecracker/gVisor selection logic
- Network provider — Headscale/WireGuard integration for mesh VPN

### Community Structure (Current)
- GitHub: `github.com/AvengerMoJo/MoJoAssistant`
- Coding rules documented in `AGENTS.md` and `docs/DEVELOPMENT_RULES_AI_FIRST_COMMUNITY.md`
- Each agent role has a designated human owner — roles are maintained, not abandoned
- Discord: [community channel — TBD]

---

## 9. Key Messages for Slides

### One-liner
> "Your AI. Your hardware. Your rules. Every part replaceable."

### Three pillars
1. **Local-first** — your data never leaves your machine
2. **Modular** — swap any component without breaking the rest
3. **Human-in-the-loop** — you decide what the AI acts on

### For developers
> "Pick a module. Make it better. Or invent one we haven't thought of."

### For AI safety people
> "Human agency is the invariant. AI capability is the variable."

### For the skeptics
> "It's running right now, on this laptop, on a local model. No API key. No cloud. Watch."

---

## 10. Slide Structure Suggestion for NotebookLM

1. **Title slide** — MoJoAssistant · Your AI, Your Rules
2. **The problem** — black box AI, locked to vendor, no agency
3. **The vision** — local-first, modular, human-in-the-loop
4. **Architecture overview** — the six swappable modules diagram
5. **Module 1: LLM Backend** — any model, one config line
6. **Module 2: Roles** — JSON personality files, community-contributed
7. **Module 3: Capabilities** — catalog-driven tool registry
8. **Module 4: HITL** — agents pause, you decide, agent resumes
9. **Module 5: Push Adapters** — ntfy today, anything tomorrow
10. **Module 6: Memory & Dreaming** — persistent, transparent, yours
11. **Live demo recap** — task → HITL → dashboard → result
12. **What's working today** — v1.4.1-beta feature checklist
13. **Bridle: how agents communicate** — wire (dispatch patterns) vs. trigger (Bonsai learns)
14. **Roadmap** — Bridle wire, Bonsai trigger, sandbox routing, voice, mesh VPN
15. **Community model** — how to contribute, entry points (wire patterns are bounded, well-documented)
16. **Call to action** — GitHub link, Discord, "Pick a module or teach a role to cooperate"

---

*Document prepared for event presentation — MoJoAssistant v1.4.1-beta — 2026-06-01*
