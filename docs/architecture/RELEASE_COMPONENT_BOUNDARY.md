# Release Component Boundary

## Purpose

MoJoAssistant is still evolving quickly.

That is useful for discovery, but dangerous for release planning.

New ideas can easily pull the project toward:

- CI/CD expansion
- community contribution workflows
- AI-first automation
- broader framework ambitions
- new orchestration patterns

before the actual product core is stable.

This document defines the release boundary.

It is meant to answer one question:

**What must be stable before release, what can remain experimental, and what should be explicitly deferred?**

## Rule

Release should be based on:

- stable product behavior
- stable security boundaries
- stable memory/runtime architecture
- stable modular seams for future extraction

Release should **not** be based on:

- every interesting idea being complete
- community workflows being mature
- automation being fully built out
- every internal subsystem already extracted into submodules

## Bucket 1: Release Core

These are the areas that should be stable enough before release.

### 1. Personal assistant product boundary

MoJoAssistant must be clearly defined as:

- a personal assistant
- owner-centric
- security-conscious
- memory-based
- role-capable

The release should have a clean answer to:

- what the assistant is for
- what data boundary it respects
- what surfaces are private vs shared

### 2. Security posture

Before release, the system needs a defensible baseline for:

- personal data boundaries
- role-private memory isolation
- tool access boundaries
- policy/security gates for agentic execution
- safe defaults

This does not require perfect security.
It does require a coherent security model.

### 3. Memory architecture

The memory system must be stable enough that the release can honestly say:

- what persistent memory means
- how role-private memory works
- how dreaming fits into the system
- what is experimental vs production-ready

ABCD does not need to be complete in its final theoretical form.
But the release must not misrepresent it.

### 4. Scheduler/runtime reliability

The scheduler and internal agent runtime need to be reliable enough for normal product use:

- task execution
- resumption
- user input continuation
- resource routing
- MCP integration lifecycle
- safe failure behavior

This does not require every runtime feature to be generalized yet.
It does require the runtime to be trustworthy.

### 5. Modular boundaries for true core components

Release should have clear boundaries for which components are:

- product-specific
- reusable core
- still experimental

At minimum, the architecture should be ready for:

- dreaming-memory pipeline as a true core component
- scheduler/runtime moving toward a true core component

Even if extraction is not fully complete, the seams must be real.

## Bucket 2: Experimental but Kept

These can stay in the repo and even ship in some form, but they should not define release readiness.

### 1. Advanced ABCD evolution

Examples:

- full D ontology surfacing
- stronger cluster semantics
- richer C relationship types
- generalized benchmark corpus

These are important, but still in active discovery.

### 2. Bonsai / taste shaping

This is one of the most differentiated long-term directions in the project.

It is also still conceptually evolving.

It should remain:

- important
- documented
- protected

but not treated as a fully finished release contract yet.

### 3. Framework-level modular extraction beyond the first cores

Examples:

- generalized policy package
- generalized role orchestration framework
- generalized knowledge/truth engine

These are plausible future extractions, but they should not be forced prematurely.

### 4. Benchmark expansion

Benchmarking is necessary.
But large benchmark coverage is not the release gate by itself.

What matters for release is:

- honest claims
- known limits
- useful benchmark-driven refinement

not “every benchmark is already excellent.”

## Bucket 3: Deferred

These should be explicitly treated as post-beta or post-release unless they become truly critical.

### 1. Community contribution workflow

Examples:

- polished contributor guidelines
- public issue triage model
- generalized contribution automation
- open collaboration workflow maturity

These are valuable after the product and core architecture are stable.

They are not the main blocker now.

### 2. Full CI/CD maturity

Basic CI matters.

But complete CI/CD maturity is not required before the architecture itself is stable.

Deferred items include:

- broad release automation
- complex deployment pipelines
- extensive matrix testing beyond what the current product actually needs

### 3. AI-first automation everywhere

This should not become a release trap.

If some automation is still manual, that is acceptable.

The release should not wait for every internal workflow to become agentic.

### 4. General framework ambitions beyond current proof

The project may become a broader agentic framework over time.

That does not mean every framework dream must be made real before release.

The correct discipline is:

- extract what is already real
- keep experimenting on what is not

## Release Discipline

When a new idea appears, classify it immediately:

- `Release Core`
- `Experimental but Kept`
- `Deferred`

If it is not clearly in Release Core, it should not move the release target.

This prevents idea velocity from silently rewriting the roadmap.

## Current Recommendation

The current release path should focus on:

1. personal assistant product clarity
2. security and boundary correctness
3. memory architecture honesty and stability
4. scheduler/runtime reliability
5. clean modular seams for the first true core components

The current release path should **not** depend on:

1. perfect CI/CD
2. community contribution maturity
3. automation of every internal workflow
4. every framework extraction already being complete

## Practical Next Step

Use this boundary together with:

- [SCHEDULER_SUBMODULE_PLAN.md](/home/alex/Development/Personal/MoJoAssistant/docs/architecture/SCHEDULER_SUBMODULE_PLAN.md)
- [ABCD_CONCEPT_CLARIFICATION.md](/home/alex/Development/Personal/MoJoAssistant/submodules/dreaming-memory-pipeline/docs/ABCD_CONCEPT_CLARIFICATION.md)
- [ABCD_MINIMAL_INFRA_PLAN.md](/home/alex/Development/Personal/MoJoAssistant/submodules/dreaming-memory-pipeline/docs/ABCD_MINIMAL_INFRA_PLAN.md)

That gives a concrete rule:

- stabilize the real product core
- keep experimental ideas alive without letting them redefine release
- extract only the components that have earned clean boundaries
