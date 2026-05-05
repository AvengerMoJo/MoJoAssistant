# Autonomous Development Pipeline

**Status:** Design
**Date:** 2026-05-05
**Goal:** Enable MoJoAssistant to autonomously build software with human oversight at merge time.

---

## The Vision

MoJoAssistant can autonomously:
1. **Provision** a sandbox environment (Docker, Portainer, or tmux)
2. **Install** OpenCode server and configure local LLM
3. **Build** 24/7 using PoPo driving OpenCode
4. **Commit** PR to a dedicated branch (not main)
5. **HITL** final merge approval

---

## Architecture

### Layer 1: Sandbox Provisioning
```
┌─────────────────────────────────────────────────┐
│                Sandbox Manager                   │
├─────────────────────────────────────────────────┤
│  Docker Mode:                                   │
│    - Create container from base image           │
│    - Mount project directory                     │
│    - Expose ports for OpenCode (4173, 4199)     │
│    - Health check until ready                    │
│                                                 │
│  Tmux Mode:                                     │
│    - Create tmux session                         │
│    - Install dependencies                        │
│    - Start OpenCode server                       │
│    - Monitor health                              │
└─────────────────────────────────────────────────┘
```

### Layer 2: Environment Setup
```
┌─────────────────────────────────────────────────┐
│              Environment Bootstrap               │
├─────────────────────────────────────────────────┤
│  1. Clone/update project repo                    │
│  2. Install OpenCode MCP server                  │
│  3. Configure local LLM (qwen3.5-35b-a3b)       │
│  4. Start OpenCode server on port 4173           │
│  5. Verify health endpoint                       │
│  6. Register with MoJoAssistant                  │
└─────────────────────────────────────────────────┘
```

### Layer 3: Autonomous Building
```
┌─────────────────────────────────────────────────┐
│              PoPo Orchestrator                    │
├─────────────────────────────────────────────────┤
│  1. Receive task from Paul (PM)                  │
│  2. Create/checkout feature branch               │
│  3. Send instructions to OpenCode                │
│  4. Monitor progress via tmux                    │
│  5. Run tests                                    │
│  6. Commit to feature branch                     │
│  7. Notify completion                            │
└─────────────────────────────────────────────────┘
```

### Layer 4: Git Workflow
```
┌─────────────────────────────────────────────────┐
│              Git Branch Strategy                 │
├─────────────────────────────────────────────────┤
│  main ────────────────────────────────────────   │
│    │                                              │
│    ├── feature/daily-news-digest ──────── PR ──▶ │
│    │                                              │
│    ├── feature/agent-learning-loop ───── PR ──▶  │
│    │                                              │
│    └── feature/bonsai-growth ──────────── PR ──▶ │
│                                                 │
│  Each feature:                                   │
│    - Isolated branch per feature                 │
│    - Commit after each logical step              │
│    - PR created automatically                     │
│    - HITL reviews before merge                   │
└─────────────────────────────────────────────────┘
```

### Layer 5: HITL Merge
```
┌─────────────────────────────────────────────────┐
│              HITL Review Process                 │
├─────────────────────────────────────────────────┤
│  1. PoPo creates PR with description             │
│  2. HITL notification sent to Alex               │
│  3. Alex reviews changes                         │
│  4. Approves or requests changes                 │
│  5. If approved: merge to main                   │
│  6. Sandbox cleaned up                          │
└─────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Sandbox Manager
- Create `app/scheduler/sandbox_manager.py`
- Docker container provisioning
- Tmux session provisioning
- Health monitoring

### Phase 2: Environment Bootstrap
- OpenCode server installation
- LLM configuration
- Project setup

### Phase 3: Git Workflow
- Branch creation per feature
- Auto-commit after logical steps
- PR creation via GitHub API

### Phase 4: HITL Merge
- PR review notifications
- Merge approval workflow
- Post-merge cleanup

---

## Key Design Decisions

1. **Sandbox isolation** — Each feature gets its own sandbox to prevent conflicts
2. **Branch per feature** — Clean git history, easy rollback
3. **Auto-commit** — Commit after each logical step, not just at the end
4. **HITL at merge** — Human reviews before code enters main
5. **24/7 building** — PoPo can work overnight, HITL reviews in morning
