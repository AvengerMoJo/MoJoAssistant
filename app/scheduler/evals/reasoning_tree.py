"""
Reasoning-tree auditing for multi-role sub-task synthesis.

HOW IT WORKS (plain English)
─────────────────────────────
When Paul dispatches two or more reviewers on the same artifact and collects
their final answers, he has a bias problem: if Carl and Popo both say "looks
fine" but Rebecca says "type error on line 29," a naive LLM synthesis drifts
toward the majority — and Rebecca's correct finding gets buried.

This module fixes that by doing three things before Paul synthesizes:

  1. ATOMIZE — split each final_answer into individual claims
     (each bullet point, numbered item, or standalone sentence becomes one claim)

  2. GROUP — cluster claims by subject across all reports
     (all claims about "test_buffer_backend.py imports" land in one bucket)

  3. DETECT CDPs — find buckets where reviewers say contradictory things
     (one role says positive/ok, another says negative/broken = Conflict/Divergence Point)

The output is a structured text block that shows Paul exactly where reviewers
agree (convergences) and where they contradict each other (CDPs), with a
resolution guide that tells him to weight specific-line-number evidence above
generic "looks fine" responses.

Paul's LLM resolves CDPs using that structure — no extra LLM call needed.

WHY THIS BEATS MAJORITY VOTE
──────────────────────────────
The mcp-buffer example: Carl couldn't read files (env blocked → unknown),
Popo pointed at the wrong path (wrong assumption → unknown/positive), Rebecca
read the actual files and found specific bugs (line-level evidence → negative).
Majority vote: 2 unknown/ok vs 1 negative = synthesis says "maybe fine."
CDP detection: surfaces the Rebecca/Popo conflict with guidance that
line-specific evidence beats generic responses → Paul correctly sides with Rebecca.

TOKEN SAVINGS
──────────────
Without this tool: Paul must read 3 full session logs to understand disagreements.
A 20-iteration session ≈ 8 000 tokens each → 24 000 tokens minimum.
With this tool: structured CDP summary ≈ 400–800 tokens → Paul resolves inline.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─── Positive/negative indicator words ────────────────────────────────────────
# Used to infer whether a claim is asserting "this works" or "this is broken."

_NEGATIVE_PATTERNS = re.compile(
    r"\b(error|bug|missing|broken|fail|wrong|incorrect|invalid|undefined|"
    r"never|not found|does not exist|no such|cannot|blocked|issue|problem|"
    r"should be|needs to be|must be changed|fix needed|mismatch|typo)\b",
    re.IGNORECASE,
)

_POSITIVE_PATTERNS = re.compile(
    r"\b(works|correct|fine|ok|good|valid|passes|looks right|no issue|"
    r"registered|linked|connected|properly|successfully)\b",
    re.IGNORECASE,
)

# Subject-extraction: pull the most specific noun phrase from a claim line.
# Strategy: take the first noun phrase (up to 6 words) before a verb or colon.
_SUBJECT_RE = re.compile(r"^([A-Za-z0-9_./:@\- ]{3,50?}?)(?:\s*[:—–]|\s+(?:is|are|has|have|does|do|should|must|will|can|cannot)\b)", re.IGNORECASE)


@dataclass
class Claim:
    role_id: str
    text: str           # the raw claim sentence/bullet
    subject: str        # normalized subject key
    polarity: str       # "positive" | "negative" | "unknown"


@dataclass
class CDP:
    """
    Conflict/Divergence Point — roles contradicted each other here.

    Example:
      subject: "tools.py handler registration"
      claims:
        carl:    "handler functions appear to be registered" (positive)
        rebecca: "handler functions never linked to tool schemas" (negative)
    """
    subject: str
    claims: List[Claim]


@dataclass
class ReasoningTreeResult:
    """
    Full audit result for a set of role reports.

    cdps         — places where roles contradict each other (need resolution)
    convergences — places where all roles agree (trust these directly)
    summary_text — ready-to-paste text block for Paul's synthesis prompt
    token_savings_estimate — rough token count saved vs reading full session logs
    """
    cdps: List[CDP]
    convergences: List[Claim]
    summary_text: str
    token_savings_estimate: int = 0


# ─── Extraction helpers ────────────────────────────────────────────────────────

def _extract_claims(role_id: str, final_answer: str) -> List[Claim]:
    """
    Split a final_answer into atomic claims.

    Splits on:
      - Markdown bullet points (- item, * item, • item)
      - Numbered list items (1. item, 2. item)
      - Sentences ending in period/exclamation followed by whitespace+capital letter
      (short fragments under 10 chars are discarded)
    """
    # Normalize line endings
    text = final_answer.replace("\r\n", "\n").replace("\r", "\n")

    # Split on bullet/number list items first
    lines: List[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        # strip leading bullet/number markers
        stripped = re.sub(r"^[-*•·]\s+", "", stripped)
        stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
        if len(stripped) < 10:
            continue
        lines.append(stripped)

    claims: List[Claim] = []
    for line in lines:
        # further split long lines on sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10:
                continue
            subject = _extract_subject(sent)
            polarity = _infer_polarity(sent)
            claims.append(Claim(
                role_id=role_id,
                text=sent,
                subject=subject,
                polarity=polarity,
            ))

    return claims


def _extract_subject(text: str) -> str:
    """
    Pull the subject from a claim sentence.

    Priority:
      1. Filename reference anywhere in the sentence (most stable grouping key)
         e.g. "tools.py handler functions" and "tools.py: never linked" both → "tools.py"
      2. Regex match for "noun phrase: rest" or "noun phrase is/are/has..."
      3. First 5 words as fallback

    Filename wins over structured extraction because it's a concrete anchor that
    two reviewers talking about the same file will always share, even if one says
    "tools.py: broken" and the other says "handler functions in tools.py look fine."
    """
    # Filename reference — check anywhere in the sentence first
    file_match = re.search(r"\b([\w/]+\.\w{2,4})(?::\d+)?\b", text)
    if file_match:
        return file_match.group(1).lower()

    # Try structured subject extraction
    m = _SUBJECT_RE.match(text)
    if m:
        return m.group(1).strip().lower()

    # Fallback: first 5 words
    words = text.split()[:5]
    return " ".join(words).lower().rstrip(".,:")


def _infer_polarity(text: str) -> str:
    """
    Classify claim polarity from indicator words.

    Negative always wins when both patterns fire — "never linked", "not connected",
    "properly registered but broken" are all negative in review contexts.
    Positive indicators in isolation signal an ok finding.
    """
    neg = bool(_NEGATIVE_PATTERNS.search(text))
    pos = bool(_POSITIVE_PATTERNS.search(text))
    if neg:
        return "negative"
    if pos:
        return "positive"
    return "unknown"


# ─── CDP detection ─────────────────────────────────────────────────────────────

def _find_cdps(
    all_claims: List[List[Claim]],
) -> Tuple[List[CDP], List[Claim]]:
    """
    Group all claims by subject, then split into CDPs (conflict) and
    convergences (agreement or all-unknown).

    Two claims are in conflict when at least one role says "positive" and
    another says "negative" about the same subject.
    """
    # Normalize subject for grouping: strip punctuation, lowercase
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()

    by_subject: Dict[str, List[Claim]] = {}
    for role_claims in all_claims:
        for claim in role_claims:
            key = _norm(claim.subject)
            by_subject.setdefault(key, []).append(claim)

    cdps: List[CDP] = []
    convergences: List[Claim] = []

    for subject, claims in by_subject.items():
        if len(claims) < 2:
            convergences.extend(claims)
            continue

        # Check for polarity conflict across different roles
        role_polarities: Dict[str, str] = {}
        for c in claims:
            # last-write-wins per role for this subject
            role_polarities[c.role_id] = c.polarity

        polarities = set(role_polarities.values())
        has_conflict = "positive" in polarities and "negative" in polarities

        if has_conflict:
            # Keep one claim per role (the one with the most decisive polarity)
            seen_roles: Dict[str, Claim] = {}
            for c in claims:
                prev = seen_roles.get(c.role_id)
                if prev is None or (prev.polarity == "unknown" and c.polarity != "unknown"):
                    seen_roles[c.role_id] = c
            cdps.append(CDP(subject=subject, claims=list(seen_roles.values())))
        else:
            # No conflict — use the most specific claim (negative > positive > unknown)
            representative = min(claims, key=lambda c: {"negative": 0, "positive": 1, "unknown": 2}[c.polarity])
            convergences.append(representative)

    return cdps, convergences


# ─── Summary text builder ──────────────────────────────────────────────────────

def _build_summary(
    cdps: List[CDP],
    convergences: List[Claim],
    report_count: int,
) -> str:
    """
    Build the ready-to-paste text block for Paul's synthesis.
    Clearly labeled so Paul's LLM knows what to do with each section.
    """
    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║           REASONING TREE AUDIT — multi-reviewer summary     ║",
        "╚══════════════════════════════════════════════════════════════╝",
        f"Reports audited: {report_count}  |  CDPs (conflicts): {len(cdps)}  |  Agreements: {len(convergences)}",
        "",
    ]

    if convergences:
        lines.append("── AGREEMENTS (all reviewers align — include directly) ──")
        seen_subjects = set()
        for c in convergences:
            subj_key = c.subject[:60]
            if subj_key in seen_subjects:
                continue
            seen_subjects.add(subj_key)
            polarity_tag = f"[{c.polarity.upper()}]" if c.polarity != "unknown" else ""
            lines.append(f"  • {c.subject}: {c.text[:120]} {polarity_tag}")
        lines.append("")

    if cdps:
        lines.append("── CONFLICTS (CDPs — resolve before synthesizing) ──")
        lines.append(
            "  Resolution guide: specific line-number evidence > file-level evidence > generic assessments.\n"
            "  A 'blocked' or 'env issue' response has no evidentiary weight.\n"
        )
        for i, cdp in enumerate(cdps, 1):
            lines.append(f"  CDP {i}: {cdp.subject}")
            for c in cdp.claims:
                lines.append(f"    [{c.role_id}] ({c.polarity.upper()}) {c.text[:150]}")
            lines.append(f"    → YOUR TASK: decide which claim is correct and explain why.")
            lines.append("")
    else:
        lines.append("  No conflicts detected — all reviewers are consistent.")
        lines.append("")

    lines.append(
        "── HOW TO USE THIS AUDIT ──\n"
        "  1. Accept all AGREEMENTS as confirmed findings.\n"
        "  2. For each CDP, apply the resolution guide above.\n"
        "  3. Build your final synthesis from confirmed + resolved findings.\n"
        "  4. Do NOT default to majority opinion — one role with a line number beats two generics."
    )

    return "\n".join(lines)


# ─── Public API ───────────────────────────────────────────────────────────────

def reason_tree_audit(
    reports: List[Dict[str, str]],
) -> ReasoningTreeResult:
    """
    Full pipeline: atomize → find CDPs → build summary.

    Args:
        reports: list of {"role_id": "...", "final_answer": "..."}

    Returns:
        ReasoningTreeResult with cdps, convergences, summary_text, token_savings_estimate
    """
    if not reports:
        return ReasoningTreeResult(
            cdps=[],
            convergences=[],
            summary_text="No reports provided.",
        )

    all_claims: List[List[Claim]] = []
    for r in reports:
        role_id = r.get("role_id", "unknown")
        final_answer = r.get("final_answer", "")
        claims = _extract_claims(role_id, final_answer)
        all_claims.append(claims)

    cdps, convergences = _find_cdps(all_claims)
    summary = _build_summary(cdps, convergences, len(reports))

    # rough estimate: each session log is ~8 000 tokens; this tool returns ~500
    savings = max(0, len(reports) * 8000 - 500)

    return ReasoningTreeResult(
        cdps=cdps,
        convergences=convergences,
        summary_text=summary,
        token_savings_estimate=savings,
    )
