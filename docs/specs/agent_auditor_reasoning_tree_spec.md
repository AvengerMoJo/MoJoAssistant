# Spec: AgentAuditor Reasoning Tree Integration

## Why It Helps

When Paul dispatches two reviewers (e.g. Carl and Rebecca) on the same artifact,
he currently reads both final answers and synthesizes them himself via LLM. This
has two failure modes:

1. **Majority bias.** If Carl and Popo both say "looks fine" but Rebecca says
   "type error on line 29," Paul's synthesis prompt leans toward the majority.
   Rebecca's minority-correct finding is silently dropped. In practice, this is
   exactly the mcp-buffer bug scenario: Carl couldn't read the files, Popo
   repeated the same misread, and Rebecca had the actual correct answer.

2. **Full-log token waste.** To investigate a disagreement, Paul (or the user)
   has to read full session logs. A 20-iteration Carl session can be 40 KB of
   LLM output. Most of it is irrelevant to the single disputed line.

The AgentAuditor paper measured exactly this pattern. Reasoning tree auditing
recovered the minority-correct answer **65% of the time** vs 0% for majority
vote, while cutting token consumption by **44.8%** at validation time by
auditing only the disputed evidence packets instead of full logs.

In MoJoAssistant terms: instead of feeding all three final answers to Paul's
synthesis call, we atomize each final answer into semantic steps, find where
they disagree (Conflict/Divergence Points = CDPs), then run a targeted LLM
audit only on the CDP evidence — not the full session logs.

---

## What a CDP Is

A **Conflict/Divergence Point** is a pair of atomic claims, one from each
report, that assert contradictory things about the same subject:

```
Carl:    "tools.py: handler functions are registered correctly"
Rebecca: "tools.py: handler functions are defined but never linked to tool schemas"
```

These share the subject "tools.py handler function registration." They assert
opposite facts. That is a CDP.

CDPs that are not contradictions (Carl says "file X missing import" and Rebecca
says "file Y has wrong range") are **Convergence Points** — both agree there's
a problem but name different files. Those get included directly without auditing.

---

## Where It Plugs In

Rebecca's recommendation was: "不需要修改 Scheduler 核心邏輯" — no core
Scheduler changes needed. The integration point is the synthesis step inside
capability_registry.py's `_dispatch_subtask` return path, or more precisely
in the role prompt + a new utility module.

**File to create:** `app/scheduler/evals/reasoning_tree.py`

**Called from:** Paul's synthesis role prompt, after `dispatch_subtask` returns
for all sub-tasks in a multi-reviewer dispatch.

Paul's current synthesis call (rough sketch of current prompt):
```
You dispatched Carl, Rebecca, and Popo to review mcp-buffer.
Their results: [carl_final_answer] [rebecca_final_answer] [popo_final_answer]
Synthesize findings and produce a final review.
```

With AgentAuditor:
```
You dispatched Carl, Rebecca, and Popo to review mcp-buffer.
Before synthesizing, run: reason_tree_audit(reports=[carl, rebecca, popo])
Use the audit result to resolve CDPs. Then produce a final review.
```

The `reason_tree_audit` tool (new, added to Paul's tool set) calls the new
module and returns a structured audit result — CDPs resolved, convergences
confirmed — that Paul includes in his synthesis.

---

## Implementation Plan

### 1. New module: `app/scheduler/evals/reasoning_tree.py`

```python
"""
Reasoning-tree auditing for multi-role sub-task synthesis.

Atomizes role final_answers into semantic claims, detects CDPs,
runs targeted audits on disputed evidence.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


@dataclass
class Claim:
    role_id: str
    subject: str       # normalized subject key (e.g. "tools.py:handler_registration")
    assertion: str     # the actual claim text
    polarity: str      # "positive" | "negative" | "neutral"
    source_excerpt: str


@dataclass
class CDP:
    subject: str
    claims: List[Claim]        # one per disagreeing role
    audit_result: Optional[str] = None   # filled by targeted audit LLM call
    resolved_to: Optional[str] = None    # which claim won, or "unresolved"


@dataclass
class ReasoningTreeResult:
    cdps: List[CDP]
    convergences: List[Claim]  # claims all roles agree on
    token_savings_estimate: int = 0


async def atomize_report(role_id: str, final_answer: str, llm_client) -> List[Claim]:
    """
    Ask the LLM to decompose a final_answer into atomic (subject, assertion)
    pairs. Returns a list of Claims.
    """
    prompt = (
        "Extract atomic factual claims from this review report. "
        "For each claim output JSON: {\"subject\": \"...\", \"assertion\": \"...\", \"polarity\": \"positive|negative|neutral\"}\n\n"
        f"Report:\n{final_answer}"
    )
    # one LLM call per report — typically <500 tokens
    raw = await llm_client.complete(prompt, max_tokens=512)
    claims = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                claims.append(Claim(
                    role_id=role_id,
                    subject=obj.get("subject", ""),
                    assertion=obj.get("assertion", ""),
                    polarity=obj.get("polarity", "neutral"),
                    source_excerpt=final_answer[:200],
                ))
            except json.JSONDecodeError:
                pass
    return claims


def find_cdps(all_claims: List[List[Claim]]) -> tuple[List[CDP], List[Claim]]:
    """
    Group claims by subject. Where roles disagree on polarity → CDP.
    Where they agree → convergence.
    """
    by_subject: Dict[str, List[Claim]] = {}
    for role_claims in all_claims:
        for claim in role_claims:
            by_subject.setdefault(claim.subject, []).append(claim)

    cdps = []
    convergences = []
    for subject, claims in by_subject.items():
        polarities = {c.polarity for c in claims if c.polarity != "neutral"}
        if len(polarities) > 1:
            cdps.append(CDP(subject=subject, claims=claims))
        else:
            convergences.extend(claims[:1])  # one representative per convergent subject

    return cdps, convergences


async def audit_cdp(cdp: CDP, llm_client) -> CDP:
    """
    Single targeted audit call for one CDP.
    Provides only the disputed claims as evidence — not the full session logs.
    """
    evidence = "\n".join(
        f"[{c.role_id}] {c.assertion}" for c in cdp.claims
    )
    prompt = (
        f"These reviewers disagree about: {cdp.subject}\n\n"
        f"Evidence:\n{evidence}\n\n"
        "Which claim is correct? Reply with the role_id of the correct claim "
        "and one sentence of reasoning. If truly ambiguous, reply 'unresolved'."
    )
    raw = await llm_client.complete(prompt, max_tokens=128)
    cdp.audit_result = raw.strip()
    # parse "role_id: ..." or "unresolved"
    for claim in cdp.claims:
        if claim.role_id in raw:
            cdp.resolved_to = claim.role_id
            break
    else:
        cdp.resolved_to = "unresolved"
    return cdp


async def reason_tree_audit(
    reports: List[Dict[str, str]],   # [{"role_id": "carl", "final_answer": "..."}, ...]
    llm_client,
) -> ReasoningTreeResult:
    """
    Full pipeline: atomize → find CDPs → audit CDPs.
    Returns a ReasoningTreeResult ready for Paul to include in synthesis.
    """
    all_claims = []
    for r in reports:
        claims = await atomize_report(r["role_id"], r["final_answer"], llm_client)
        all_claims.append(claims)

    cdps, convergences = find_cdps(all_claims)

    audited_cdps = []
    for cdp in cdps:
        audited = await audit_cdp(cdp, llm_client)
        audited_cdps.append(audited)

    # token_savings: we read ~128 tokens per CDP instead of full session logs
    # a 20-iter session ≈ 8000 tokens → savings = (8000 - 128) * len(cdps)
    savings = max(0, (8000 - 128) * len(audited_cdps))

    return ReasoningTreeResult(
        cdps=audited_cdps,
        convergences=convergences,
        token_savings_estimate=savings,
    )
```

### 2. New tool: `reason_tree_audit`

Add to `app/scheduler/capability_registry.py` in the Paul-role tool set
(or any orchestrator role that does multi-reviewer dispatch):

```python
{
    "type": "function",
    "function": {
        "name": "reason_tree_audit",
        "description": (
            "Audit multiple sub-task reports for conflicts. "
            "Atomizes each report into claims, finds where reviewers disagree "
            "(CDPs), runs a targeted LLM audit on each CDP. "
            "Returns resolved CDPs and convergences. "
            "Use this before synthesizing findings from 2+ reviewers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reports": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role_id": {"type": "string"},
                            "final_answer": {"type": "string"}
                        },
                        "required": ["role_id", "final_answer"]
                    },
                    "description": "List of role reports to audit"
                }
            },
            "required": ["reports"]
        }
    }
}
```

Handler in capability_registry.py `_dispatch_tool_call`:

```python
elif tool_name == "reason_tree_audit":
    from app.scheduler.evals.reasoning_tree import reason_tree_audit
    result = await reason_tree_audit(
        reports=args["reports"],
        llm_client=self._llm_client,
    )
    cdp_lines = []
    for cdp in result.cdps:
        resolved = cdp.resolved_to or "unresolved"
        cdp_lines.append(
            f"- **{cdp.subject}**: resolved to `{resolved}` — {cdp.audit_result}"
        )
    conv_lines = [f"- {c.subject}: {c.assertion}" for c in result.convergences]
    return {
        "success": True,
        "cdps_resolved": len(result.cdps),
        "convergences": len(result.convergences),
        "token_savings_estimate": result.token_savings_estimate,
        "cdp_summary": "\n".join(cdp_lines) or "(no conflicts)",
        "convergence_summary": "\n".join(conv_lines) or "(no agreements)",
    }
```

### 3. Paul's dispatch pattern (role prompt update)

Add to Paul's role prompt system section, after the `dispatch_subtask` guidance:

```
When you dispatch 2 or more reviewers on the same artifact:
1. Collect all final_answers from dispatch_subtask calls.
2. Call reason_tree_audit with all reports before synthesizing.
3. CDPs resolved by the audit take precedence over majority opinion.
4. Include the audit summary in your final synthesis.
```

---

## Token Cost Breakdown

| Step | Tokens |
|------|--------|
| Atomize one 500-word report | ~400 in + ~300 out = 700 |
| Atomize 3 reports | ~2 100 |
| Audit one CDP (128 out) | ~200 in + 128 out = 328 |
| Audit 3 CDPs | ~984 |
| **Total audit cost** | **~3 100** |
| Current: Paul reads 3 full session logs (3 × 8 000 tok) | **24 000** |
| **Net saving** | **~20 900 tokens (87%)** |

The 44.8% figure from the paper is conservative — it averages across tasks
where many reports are short. For MoJoAssistant's long-form review tasks the
saving is higher because session logs include tool call round-trips.

---

## Minority-Correct Recovery

Example: mcp-buffer review (June 2026)

| Role | Claim | Correct? |
|------|-------|----------|
| Carl | "cannot access files — environment blocked" | Partial (env issue) |
| Popo | "files look fine at ~/mcp-buffer/" | Wrong path |
| Rebecca | "Path import missing line 9; entry_id vs entry.id line 29" | Correct |

Current Paul synthesis: 2 "ok or unknown" vs 1 "bugs found" → synthesis
drifts toward "needs env fix, maybe bugs." Rebecca's specific line numbers
are buried.

With reason_tree_audit:
- CDP detected: `mcp_buffer/tests/test_buffer_backend.py:imports`
  - Carl: "unknown (env blocked)"
  - Popo: "no issue"
  - Rebecca: "Path import missing line 9"
- Audit call on that CDP: reads only those 3 claims (~200 tokens)
  → resolves to Rebecca (specific line number is more authoritative than
    generic "looks fine" or "env blocked")
- Paul's synthesis now leads with Rebecca's findings.

This is the 65% recovery rate: when one role has specific evidence and others
have generic or blocked responses, the targeted audit picks the specific one.

---

## What We Do NOT Change

- No changes to `Task`, `TaskResult`, or `TaskStatus` models.
- No changes to the scheduler dispatch loop.
- No changes to how sub-tasks are created or polled.
- No changes to any executor (agentic or coding_agent).
- The tool is opt-in — only roles whose prompts instruct them to use it will
  call it. Paul is the first target; other orchestrators can be added later.

---

## Acceptance Criteria

1. `reason_tree_audit` tool callable from Paul's session with 2+ reports.
2. For the mcp-buffer test case (3 reports, 1 correct minority), audit resolves
   the CDP to Rebecca's line-number finding.
3. Token savings logged in task session as `audit_token_savings`.
4. No regression: single-reviewer tasks (no multi-dispatch) are unaffected.

---

## Implementation Size

- New file: `app/scheduler/evals/reasoning_tree.py` (~120 lines)
- `app/scheduler/capability_registry.py`: +1 tool schema + ~25 lines handler
- Paul role prompt: +4 lines

No new config. No new DB schema. No changes to core scheduler.
