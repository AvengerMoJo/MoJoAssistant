# MoJoAssistant Vision & Architecture

**Purpose**: True AI assistance through memory, agency, scheduling, and security

---

## The Four Pillars of Assistance

MoJoAssistant is built on four foundational pillars that enable **real assistance**, not just text responses:

### 1. **Memory System** 🧠 (Foundation)

**Purpose**: Extendable memory architecture that understands context, relationships, and policies

**Capabilities**:
- **Entity Relationship Mapping**: Who knows what, who has access to what
- **Security Policy Enforcement**: What can be public, what must be private
- **Context Preservation**: Remember user preferences, project state, historical decisions
- **Monitoring & Auditing**: Track changes, understand patterns, detect anomalies

**Examples**:
- "My color preference is blue" → Public information, no auth needed
- "My bank PIN is 1234" → Never store, always require explicit auth
- "I prefer approach X for problem Y" → Learning from past decisions
- "Project A is related to Client B" → Entity relationship for context

**Status**: Core memory system exists, needs extension for security policies

---

### 2. **Agent Manager** 🤖 (Current Focus)

**Purpose**: Manage AI agents and tools for both internal optimization and external user needs

**Why This Matters**:
- **Internal Tools**: Prevent GPU waste by creating lightweight tools for common operations
- **External Tools**: Enable users to take actions, not just get text responses
- **Resource Optimization**: Smart routing to appropriate agents/tools
- **Lifecycle Management**: Start, stop, monitor, and recover agents automatically

#### OpenCode Manager (v1.1 Beta) ← **You are here**

**First Implementation** of the Agent Management Pattern:
- N:1 architecture (one manager serves multiple agents)
- Process lifecycle management (start/stop/health checks)
- Hot-reload configuration
- Security-focused credential handling

**Pattern Established**:
```
Agent Manager
├─ Lifecycle: Start/Stop/Monitor/Recover
├─ Configuration: Hot-reload, versioned, secure
├─ Health Checks: Automated monitoring
├─ Resource Management: Port allocation, process limits
└─ Security: Credential isolation, permission enforcement
```

**Future Agents** (using same pattern):
- **Gemini CLI Manager**: Manage Google AI coding sessions
- **Custom Tool Manager**: Internal optimization tools
- **Third-party MCP Servers**: External integrations
- **Multi-agent Orchestration**: Coordinate between agents

**Status**: ✅ Pattern established with OpenCode (v1.1 beta)

---

### 3. **Scheduler** 📅 (Future)

**Purpose**: Intelligent task management, background processing, and resource optimization

**Capabilities**:
- **Task Tracking**: Monitor requirements, dependencies, and progress
- **Routine Checks**: Automated verification loops (e.g., "did we meet the requirements?")
- **Dreaming**: Background reflection and optimization while idle
- **User Notifications**: Smart alerts when decisions are needed
- **Resource Optimization**:
  - Which agent is free vs busy?
  - Which approach is costly but effective?
  - When to use GPU vs CPU?
  - Memory-driven decision making (what worked before?)

**Examples**:
- "Check if all tests pass every hour, notify if failures"
- "Review open tasks nightly, suggest priorities"
- "Optimize memory usage during idle times"
- "Route complex questions to expensive models, simple ones to cheap models"

**Integration with Memory**:
- Learn which approaches work for which problems
- Remember user preferences for different scenarios
- Track cost/effectiveness of different strategies

**Status**: Not yet implemented, design phase

---

### 4. **Security & Entity Policies** 🔒 (Future)

**Purpose**: Fine-grained permission system with context-aware authorization

**Capabilities**:
- **Permission Granularity**: Per-entity, per-action, per-context
- **Public vs Private Information**:
  - Color preference → Public (no auth needed)
  - API keys → Private (always require auth)
  - Bank PIN → Never store
  - Project secrets → Encrypted at rest
- **Smart Authorization**:
  - Don't ask every time for low-risk actions
  - Multi-factor for high-risk operations
  - Context-aware (e.g., "you just authenticated 5 minutes ago")
- **Entity Relationships**:
  - User A can access Project B
  - AI Agent C can modify File D
  - Client E has read-only access to Report F

**Examples**:
- "Remember my GitHub token" (encrypted, auto-use for git operations)
- "Never store my bank password" (policy: never persist)
- "Anyone can see my preferred editor" (public metadata)
- "Only I can approve deployments" (explicit user action required)

**Integration with Memory**:
- Security policies stored as structured memory
- Entity relationships maintained in knowledge graph
- Audit trail of all permission checks

**Status**: Not yet implemented, design phase

---

## Current State & Roadmap

### ✅ Implemented

1. **Memory System** (Core):
   - Vector-based semantic memory
   - Embedding storage (Qdrant)
   - Context retrieval
   - Knowledge persistence

2. **Agent Manager** (v1.1 Beta):
   - OpenCode Manager with N:1 architecture
   - Process lifecycle management
   - Configuration hot-reload
   - Security improvements (bearer token protection)

### 🚧 In Progress

- **Agent Manager**: Testing and stabilization
- **Memory**: Extension for security policies and entity relationships

### 📋 Planned

3. **Scheduler**:
   - Task tracking system
   - Background processing ("dreaming")
   - Resource optimization
   - Memory-driven decision making

4. **Security & Entity Policies**:
   - Fine-grained permissions
   - Context-aware authorization
   - Public/private information classification
   - Encrypted credential storage

---

## Why This Architecture?

### Problem: Traditional AI Assistants Are Limited

**They can only**:
- Generate text responses
- Execute pre-defined tools
- Forget context quickly
- Treat all actions equally (no security model)

**They cannot**:
- Remember long-term preferences and policies
- Manage complex multi-step workflows
- Optimize their own resource usage
- Make smart authorization decisions
- Create new tools dynamically
- Learn from past decisions

### Solution: MoJoAssistant's Integrated Approach

**Memory** provides context and learning
↓
**Agent Manager** enables actions and optimization
↓
**Scheduler** orchestrates complex workflows
↓
**Security** ensures safe, smart authorization

**Result**: True assistance that is:
- **Contextual**: Remembers and learns
- **Actionable**: Does things, not just says things
- **Efficient**: Optimizes resource usage
- **Secure**: Smart permission management
- **Autonomous**: Handles multi-step workflows independently

---

## Design Principles

### 1. **Reusable Patterns**
- Establish patterns with first implementation (OpenCode Manager)
- Extend patterns to new agents (Gemini CLI, custom tools)
- Don't reinvent the wheel each time

### 2. **Memory-First**
- All decisions informed by memory
- Learn from past successes and failures
- Build up organizational knowledge over time

### 3. **Security by Default**
- Credentials never in process listings
- Fine-grained permissions
- Audit trails for all sensitive operations

### 4. **Progressive Enhancement**
- Start simple (OpenCode Manager)
- Add capabilities incrementally (Scheduler, Security)
- Each component works independently but better together

### 5. **User in Control**
- Explicit consent for sensitive operations
- Transparent decision-making
- Override capabilities when needed

---

## The Agent Manager Pattern (Established)

The OpenCode Manager establishes a **reusable pattern** for managing AI agents:

### Core Components

```
Agent Manager
├─ Config Manager: Hot-reload, versioned JSON
├─ Process Manager: Start/stop, health checks, recovery
├─ State Manager: Persistent state, auto-migration
├─ Environment Manager: Secure credential handling
└─ SSH/Auth Manager: Key generation, validation
```

### Lifecycle Model

```
N Projects → 1 Global Agent → MCP Clients

Project Lifecycle:
1. Bootstrap (create sandbox, generate credentials)
2. Start (launch processes, health checks)
3. Monitor (health checks, auto-recovery)
4. Stop (graceful shutdown)
5. Destroy (cleanup resources)

Global Agent Lifecycle:
- Start: When first project starts (0 → 1 projects)
- Run: While any projects active (count > 0)
- Stop: When last project stops (1 → 0 projects)
```

### Security Model

- Credentials in environment variables (not CLI)
- File permissions: 0600 for sensitive files
- Process isolation (future: systemd user services)
- Audit logging for all operations

### Configuration Model

- Hot-reload: Changes detected automatically
- Versioned: State format migrations
- Validated: Schema enforcement
- Secure: Proper file permissions

---

## Next Steps

### Immediate (v1.1 Beta Testing)

1. **Test OpenCode Manager** with real workflows
2. **Verify security** in production-like environments
3. **Document learnings** for next agent implementation

### Short-term (Next Agent)

1. **Implement Gemini CLI Manager** using established pattern
2. **Refactor common code** into reusable base classes
3. **Extend memory** for agent metadata and relationships

### Medium-term (Scheduler)

1. **Design task tracking** system
2. **Implement background processing** ("dreaming")
3. **Build resource optimization** logic
4. **Integrate with memory** for learning

### Long-term (Security & Policies)

1. **Design permission system** with memory integration
2. **Implement entity relationships** in knowledge graph
3. **Build context-aware authorization**
4. **Add encrypted credential storage**

---

## Success Metrics

### For Agent Manager (Current)
- ✅ Pattern established and documented
- ✅ Security audit passed
- [ ] Successfully extended to second agent (Gemini CLI)
- [ ] Zero credential leaks in production

### For MoJoAssistant (Overall)
- [ ] Remembers user preferences across sessions
- [ ] Creates tools dynamically based on user needs
- [ ] Optimizes resource usage automatically
- [ ] Makes smart authorization decisions
- [ ] Handles multi-day, multi-step tasks autonomously

---

## Conclusion

The OpenCode Manager (v1.1 beta) is **not the end goal** - it's the **first building block** in a much larger vision. It establishes the Agent Manager pattern that will enable MoJoAssistant to:

1. Manage multiple types of AI agents
2. Create tools dynamically for optimization
3. Integrate with memory for context and learning
4. Build toward true autonomous assistance

**Current Status**: ✅ Foundation laid, pattern established, ready for beta testing
**Next Step**: Extend pattern to additional agents and integrate with scheduler
