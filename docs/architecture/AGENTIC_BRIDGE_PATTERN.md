# Agentic Bridge Pattern

Status: Design Direction  
Date: 2026-05-11  
Related: [MOJO_MODULE_SYSTEM.md](MOJO_MODULE_SYSTEM.md) · [MODULE_IMPLEMENTATION_TODO.md](MODULE_IMPLEMENTATION_TODO.md)

---

## The Problem This Solves

Every time a promising third-party framework appears — a new embedding server,
a vector store, a reranking service, a graph database — someone has to:

1. Read the framework's documentation
2. Write a glue adapter
3. Test it manually
4. Maintain it as the framework evolves

This is integration tax. It scales linearly with the number of integrations and
keeps the system frozen in the choices made at build time. The Agentic Bridge
Pattern eliminates this tax and makes the system self-extending.

---

## Core Idea

**MoJo owns the interface. An agent generates the adapter. The conformance suite
is the judge. No developer writes glue code.**

```
Any external system
(GitHub repo, PyPI package, REST API, local model server, ...)
        │
        ▼
  [MoJo Bridge Agent]
        │  ← probes the target: reads docs, README, API spec, source
        │  ← reads our interface ABC and conformance tests
        │
        ▼
  Generates bridge implementation
        │
        ▼
  Conformance suite runs automatically
        │
    pass ──→ bridge registered, user notified, system starts using it
    fail ──→ agent reports gap → iterates, or escalates to HITL
              (gap also feeds back into interface improvement)
```

The agent is not given a specific target in advance. It is given a task
("find and install a better embedding backend") and a toolset (web search,
code execution, file write, test runner). It discovers candidates, probes
them, attempts bridges, and reports back. The user decides what to keep.

---

## Runtime Probing

The bridge agent does not require a pre-curated list of frameworks. It can
discover candidates at runtime:

1. **By URL or package name** — user says "try this GitHub repo"
2. **By capability search** — agent searches for frameworks matching a need
   (e.g. "sparse embedding server with batch support")
3. **By community feed** — agent checks a shared bridge registry for bridges
   others have already validated (future)

For each candidate the agent evaluates:
- Does it have a public API? (REST, Python, gRPC)
- Does the API surface map onto our interface? (can every method be satisfied?)
- What are the constraints? (requires GPU, requires API key, license, etc.)
- What is the install cost? (pip install, Docker image, model download size)

The agent produces a feasibility report before writing a single line of code.
If the answer is "this framework cannot satisfy the interface," it says so and
explains why. That is also a useful output.

---

## What MoJo Must Provide (The Invariants)

For every pluggable concern, MoJo Core maintains three artifacts:

### 1. The Interface ABC

A Python abstract base class with full docstrings:
- What each method must do (semantics, not implementation)
- What the inputs mean and what valid values look like
- What the output shape must be, field by field
- Explicit invariants (e.g. "results sorted descending by score", "never returns None")

The ABC is the contract. It must be stable and complete enough that an agent
with no other context can understand exactly what a correct implementation
looks like.

### 2. The Conformance Test Suite

A `tests/conformance/test_<interface>_conformance.py` that:
- Is parametrized over all registered implementations
- Covers every method in the ABC
- Tests every stated invariant explicitly
- Includes a `MockBackend` that any new bridge can be compared against
- Can be run standalone with no external dependencies (mocks/stubs for I/O)

**The conformance suite is the specification made executable.** A bridge that
passes is correct by definition. No manual integration testing required.

### 3. The Bridge Installer Prompt

A `docs/bridges/<interface>_bridge_prompt.md` that is:
- **Self-contained** — includes the full ABC and full conformance test suite
  verbatim, not summarized
- **Target-agnostic** — uses `{TARGET}` as a placeholder filled at dispatch time
- **Instruction-complete** — tells the agent exactly where to write the file,
  how to register it, how to run tests, and what to report

Any capable LLM agent dispatched with this prompt and a target can complete
the installation without additional context.

---

## Bridge Lifecycle

### Discovery and Installation (agent-driven)

```
user (or scheduled agent): "explore embedding backends, install the best fit"

MoJo scheduler dispatches Bridge Agent with:
  - bridge_installer_prompt.md for EmbeddingBackend
  - tools: web_search, fetch_url, bash_exec, file_write, pytest

Bridge Agent:
  1. searches for candidate frameworks (or receives a URL/package name)
  2. probes each candidate: reads README, API docs, source if available
  3. produces feasibility report per candidate
  4. selects best candidate (or all feasible ones)
  5. writes bridge implementation(s)
  6. runs conformance suite for each
  7. for passing bridges: registers, writes bridge_manifest entry
  8. reports to user: what was installed, what was attempted, what failed and why

User reviews report → approves or rejects → HITL
```

### Upgrade (agent-driven)

```
framework releases new version
  └─→ Bridge Agent re-probes, rewrites bridge if API changed
      runs conformance → if pass, replaces previous bridge file
      if fail, reports regression and what changed
```

### Verification (automated CI)

Every PR runs the full conformance suite against all registered bridges.
A bridge that regresses is caught before merge, not after.

---

## Bridge Manifest

Every installed bridge is recorded in `mojo_memory/embeddings/bridges/manifest.json`
(or equivalent per interface):

```json
{
  "bridges": [
    {
      "name": "sie",
      "interface": "EmbeddingBackend@1.0",
      "target": "superlinked/sie",
      "target_version": "v1.2.0",
      "installed_at": "2026-05-11T10:00:00Z",
      "installed_by": "bridge_agent",
      "conformance_passed": true,
      "conformance_score": "22/22",
      "limitations": [],
      "notes": "Requires SIE server running at EMBEDDING_SERVER_URL"
    }
  ]
}
```

The manifest is:
- The audit trail of what was installed and why
- The input for the community feedback system (future)
- The source of truth for `config(action="doctor")` bridge health reporting

---

## Agent Prompt Template Structure

```markdown
# Bridge Installation Task: {INTERFACE_NAME}

## Context
You are a MoJo Bridge Agent. Your job is to create a bridge between the MoJo
{INTERFACE_NAME} interface and an external framework or service.

## Target
{TARGET}  ← filled at dispatch time (URL, package name, or "discover best option")

## The interface contract (implement this exactly)
[full ABC pasted verbatim]

## The conformance suite (your bridge must pass all of these)
[full test file pasted verbatim]

## Steps
1. Probe the target. Read its documentation, API, and any available source.
2. Assess feasibility: can every interface method be satisfied?
   If no: report which methods cannot be satisfied and why. Stop here.
3. If feasible: write the bridge class. File location: {OUTPUT_PATH}
4. Register it: call register_{interface}("{name}", {ClassName}())
5. Run: pytest {CONFORMANCE_TEST_PATH} -v
6. If all tests pass: write a manifest entry and report success.
7. If tests fail: report which tests failed, what the gap is, and whether
   another iteration would likely fix it.

## Constraints
- Do not modify the ABC or the test file.
- Use only the target's public API. No internal implementation details.
- Best-effort approximations are allowed; document limitations in docstrings.
- If the target requires credentials or a running server, document that in the
  manifest "notes" field.

## Output
1. Bridge file (if feasible)
2. Manifest entry
3. Conformance test results
4. Feasibility assessment and any discovered limitations
```

---

## Community Feedback Layer (Future)

Once multiple MoJo users are running independently installed bridges, a shared
validation layer becomes possible:

- **Bridge sharing** — a user publishes their passing bridge manifest entry to
  a community registry (opt-in)
- **Community validation** — other users can pull and install a bridge that was
  already validated by the community, skipping the generation step
- **Version tracking** — community registry tracks which bridge version works
  with which target version, surfacing regressions when frameworks update
- **Failure reporting** — if a previously passing bridge fails after a framework
  update, the failure is reported back to the community registry so others
  can update before hitting the same issue

This is the long-term sustainability mechanism. The system improves collectively.
No single user or developer is responsible for maintaining any adapter.

---

## Applicable Interfaces

The pattern applies to every pluggable interface in the module system:

| Interface | Pluggable concern | Example third-party targets |
|-----------|------------------|-----------------------------|
| `EmbeddingBackend` | How text becomes vectors | SIE, Ollama, OpenAI, Cohere, vLLM, TEI |
| `RetrievalStrategy` | How candidates are ranked | FAISS, Qdrant, Weaviate, BM25s |
| `StorageBackend` | How data is persisted | SQLite, PostgreSQL, S3, Lancedb |
| `MemoryModule` | Full memory pipeline | Any ABCD-compatible system |
| `PersonaModule` | Role generation and scoring | Any persona/character framework |
| `GrowthModule` | Role evolution logic | Any RL or feedback-based system |
| `SkillModule` | Tool blueprint catalog | Any agent skill registry |

The pattern is not specific to embeddings. Any future interface defined in
`provider_contracts.py` automatically gets this capability for free — as long
as a conformance suite and bridge installer prompt are written for it.

---

## Design Rules

1. **Never write a bridge by hand if a capable agent can do it.** Dispatch an agent.
2. **Never install a bridge without a passing conformance run.** The suite is the only gate.
3. **Never put framework-specific logic in the ABC.** The interface must stay target-agnostic.
4. **Always version the interface before changing it.** `EmbeddingBackend@2.0` is a new contract.
5. **The bridge installer prompt is a first-class maintained artifact.** Update it when the ABC changes.
6. **Failures are data.** A failed bridge attempt improves the conformance suite and the ABC.
7. **The manifest is the truth.** What is installed, when, by whom, and whether it works — all in the manifest.
