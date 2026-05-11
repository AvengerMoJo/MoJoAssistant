# Agentic Bridge Pattern

Status: Design Direction  
Date: 2026-05-11  
Related: [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md) · [MODULE_IMPLEMENTATION_TODO.md](MODULE_IMPLEMENTATION_TODO.md)

---

## The Problem This Solves

Every time a promising third-party framework appears — a new embedding server, a vector store, a reranking API — someone has to:

1. Read the framework's documentation
2. Write a glue adapter
3. Test it manually
4. Maintain it as the framework evolves

This is integration tax. It scales linearly with the number of integrations. It keeps the team in maintenance mode instead of building.

The Agentic Bridge Pattern eliminates this tax.

---

## Core Idea

**MoJo owns the interface. An agent generates the adapter. The conformance suite is the judge.**

```
Third-party framework
        │
        ▼
  [MoJo Agent]  ← reads our interface ABC + conformance tests
        │         ← reads framework docs / API reference
        │
        ▼
  Bridge implementation (Python file)
        │
        ▼
  Conformance suite runs automatically
        │
    pass ──→ bridge committed to backends/
    fail ──→ agent reports gap, iterates or escalates to HITL
```

No developer needs to touch the third-party framework's API. The agent does it. The conformance tests verify correctness. The bridge is installed only if it passes.

---

## What MoJo Must Provide (The Invariants)

For each pluggable concern, MoJo Core maintains:

### 1. The Interface ABC

A Python abstract base class with full docstrings explaining:
- What each method must do (semantics, not implementation)
- What the inputs mean
- What the output shape must be
- Any invariants (e.g. "results must be sorted descending by score")

Example: `EmbeddingBackend` in `app/services/provider_contracts.py`.

### 2. The Conformance Test Suite

A `tests/conformance/test_<name>_conformance.py` file that:
- Is parametrized over all registered backends
- Tests every method in the interface
- Checks invariants explicitly (ordering, type shapes, empty input handling)
- Includes a `MockBackend` that any new implementation can compare against

**The conformance suite is the specification.** If a bridge passes it, it is correct.

### 3. The Bridge Installer Prompt Template

A `docs/bridges/<interface_name>_bridge_prompt.md` file containing:
- The full interface ABC (pasted verbatim, not summarized)
- The conformance test suite (pasted verbatim)
- Placeholder: `{FRAMEWORK_NAME}` and `{FRAMEWORK_DOCS}`
- Instructions to the agent:
  1. Read the interface carefully
  2. Read the framework documentation
  3. Write a Python class implementing the interface
  4. Register it in the backend registry
  5. Run the conformance suite and report results
  6. If tests pass, output the final file. If not, report what is missing.

---

## Bridge Lifecycle

### Installation (agent-driven)

```
user: "install SIE as an embedding backend"
  └─→ MoJo scheduler dispatches agent with:
        - bridge_installer_prompt.md (filled with SIE docs URL)
        - write permission to mojo_memory/embeddings/backends/
        - permission to run: pytest tests/conformance/test_embedding_backend_conformance.py

  agent:
    1. reads EmbeddingBackend ABC
    2. fetches SIE API docs
    3. writes SIEBackend class
    4. runs conformance tests
    5a. pass → commits sie_backend.py, registers under name "sie"
    5b. fail → reports which tests failed, what the gap is
```

### Upgrade (agent-driven)

When a framework updates its API:
```
user: "SIE released v2, update the bridge"
  └─→ same pattern: agent reads new docs, rewrites bridge, runs conformance
```

### Verification (automated)

CI runs the full conformance suite against all registered backends on every PR. A bridge that was passing and now fails is caught automatically.

---

## What the Agent Prompt Must Include

The bridge installer prompt (`docs/bridges/<name>_bridge_prompt.md`) must contain:

```markdown
# Bridge Installation: {INTERFACE_NAME}

## Your task
Implement `{ClassName}` in Python — a concrete implementation of the
`{InterfaceABC}` abstract base class — that delegates to `{FRAMEWORK_NAME}`.

## The interface you must implement (copy verbatim into your file)
[paste full ABC here]

## The conformance tests you must pass (run these to verify)
[paste full test file here]

## Framework documentation
{FRAMEWORK_DOCS}

## Constraints
- Do not modify the ABC or the test file.
- Your implementation goes in: `mojo_memory/embeddings/backends/{name}_backend.py`
- Register it by calling: `register_backend("{name}", {ClassName}())`
- Use only the framework's public API. Do not access internal implementation details.
- If the framework's API does not support a required method, implement a best-effort
  approximation and note the limitation in a docstring.

## Output
1. The complete Python file
2. The result of running the conformance suite
3. Any limitations or gaps you discovered
```

---

## Current Bridge Targets

| Interface | Status | Candidate Frameworks |
|-----------|--------|----------------------|
| `EmbeddingBackend` | Interface defined (2026-05-11) | SIE, OpenAI, Cohere, Ollama, vLLM |
| `RetrievalStrategy` | Done — built-ins only | FAISS, Qdrant, Weaviate, Pinecone |
| `StorageBackend` | Planned | SQLite, PostgreSQL, S3 |

The bridge prompt for `EmbeddingBackend` lives at:
`docs/bridges/embedding_backend_bridge_prompt.md`

---

## Why This Is Sustainable

**We never maintain adapters.**  
Adapters are generated artifacts. When a framework changes, we regenerate. The conformance suite tells us if it's still correct.

**We never block on third-party timelines.**  
Any framework with a public API or documentation can be bridged. We don't need the framework author to provide a MoJo plugin.

**The interface accumulates value over time.**  
Every bridge that passes conformance is proof the interface is well-designed. Every failure is a spec gap that improves the ABC and the conformance suite. The system gets better with each attempt.

**Any sufficiently capable agent can do it.**  
The prompt is self-contained. No project-specific context is required beyond what's in the prompt. This means any MoJo scheduling agent — or an external Claude Code session — can install a bridge.

---

## Design Rules

1. **Never write a bridge by hand if the framework has public docs.** Dispatch an agent.
2. **Never merge a bridge that doesn't pass conformance.** The suite is the gate.
3. **Never add framework-specific logic to the ABC.** The interface must remain framework-agnostic.
4. **Always version the interface before changing it.** `EmbeddingBackend@2.0` is a new ABC, not a modification.
5. **The bridge installer prompt is a first-class artifact.** Keep it up to date as the interface evolves.
