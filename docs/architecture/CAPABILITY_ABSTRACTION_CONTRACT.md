# Capability Abstraction Contract

Date: 2026-04-30  
Status: Implemented — v1.2.10+

## Goal

Define a provider-agnostic capability model so MoJoAssistant can validate and debug any user-defined tool/capability setup without relying on hardcoded tool names.

The framework must answer:
1. What does a task *need*? (intent classes)
2. What does a role/system *provide*? (capability providers)
3. What is *actually runnable now*? (runtime proofs)

## 1. Intent Classes (task-side requirements)

Intent classes are semantic needs, independent of implementation.

Core classes:
- `observe` — inspect state/metadata
- `read` — retrieve content/data
- `write` — persist or mutate content/data
- `execute` — run commands/procedures
- `interact` — interactive control/session operations
- `external_lookup` — fetch from external sources
- `escalate` — request user input/approval
- `finalize` — produce contract-compliant completion output

A task declares required classes, e.g.:
```json
{
  "required_intent_classes": ["execute", "read", "finalize"]
}
```

## 2. Capability Providers (role/system supply)

A capability provider is any tool/plugin/integration that claims to satisfy one or more intent classes.

Provider metadata contract:
```json
{
  "provider_id": "custom.shell.runner",
  "intent_classes": ["execute"],
  "preconditions": ["binary:curl", "network:egress"],
  "trust_boundary": "local",
  "side_effect_level": "medium",
  "health_probe": {
    "type": "command",
    "spec": "curl --version"
  }
}
```

Required fields:
- `provider_id`
- `intent_classes[]`
- `trust_boundary` (`local` | `external` | `hybrid`)
- `health_probe`

Optional fields:
- `preconditions[]`
- `side_effect_level`
- `rate_limits`
- `timeout_policy`

## 3. Runtime Proof (environment truth)

Before dispatch, framework runs preflight proofs per required class:

1. Resolve providers mapped to required intent class.
2. Execute each provider's health probe.
3. Mark class healthy if at least one provider passes.
4. If class unhealthy, block task with structured gap report.

No silent fallback. No hidden substitutions.

## 4. Preflight Output Contract

```json
{
  "task_id": "...",
  "role_id": "...",
  "ok": false,
  "required_classes": ["execute", "finalize"],
  "class_status": {
    "execute": {
      "ok": false,
      "providers_checked": ["custom.shell.runner"],
      "passing_providers": [],
      "failures": ["binary:curl missing"]
    },
    "finalize": {
      "ok": true,
      "providers_checked": ["framework.final_answer_contract"],
      "passing_providers": ["framework.final_answer_contract"],
      "failures": []
    }
  },
  "remediation": [
    "Install provider prerequisites for class 'execute'",
    "Or attach an alternate provider mapped to 'execute'"
  ]
}
```

## 5. Planner/Executor Behavior Rules

1. If any required class is unhealthy -> hard fail task pre-dispatch.
2. If class healthy, executor may choose any passing provider.
3. `escalate` may only be used when required classes are unhealthy *or* policy requires approval.
4. Final answer accepted only when `finalize` contract passes.

## 6. Data Boundary and Policy Integration

Policy checks run orthogonally to class health:
- A provider can be healthy but disallowed by policy (sensitive domain, local-only role, trust boundary violation).
- Preflight must report both capability gaps and policy blocks distinctly.

## 7. Why this avoids user-specific brittleness

This contract decouples framework correctness from:
- specific model names
- specific tool names
- specific provider brands (LM Studio/Ollama/vLLM/etc.)
- personal custom tools

Users can define any providers, as long as they declare intent classes and pass health proofs.

## 8. Rollout Plan

1. Add provider metadata schema and loader.
2. Add intent-class preflight validator.
3. Attach preflight report to task list/dashboard debug.
4. Enforce pre-dispatch hard-fail on unhealthy required class.
5. Add regression suite with synthetic user-defined providers.
