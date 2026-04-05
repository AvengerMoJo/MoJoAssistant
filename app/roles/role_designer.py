"""
Role Designer — Nine Chapter conversational interview

Drives a structured conversation that extracts the five core Nine Chapter
dimensions from the user, then synthesises a role config + system prompt.

State machine:
  intro → core_values → emotional_reaction → cognitive_style
       → social_orientation → adaptability → purpose
       → predict_verify → synthesis → complete
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from app.config.paths import get_memory_subpath

SESSIONS_DIR = get_memory_subpath("role_design_sessions")

# ── Dimension weights (Nine Chapter Set A) ──────────────────────────────────
_WEIGHTS = {
    "core_values":        0.30,
    "emotional_reaction": 0.25,
    "cognitive_style":    0.20,
    "social_orientation": 0.15,
    "adaptability":       0.10,
}

# ── Question sequence ────────────────────────────────────────────────────────
_STEPS = [
    "intro",
    "core_values",
    "emotional_reaction",
    "cognitive_style",
    "social_orientation",
    "adaptability",
    "purpose",
    "role_type",
    "tool_access",
    "predict_verify",
    "synthesis",
]

_QUESTIONS = {
    "intro": (
        "Let's build your character together.\n\n"
        "Start by giving them a **name** and describing them in a few sentences — "
        "who are they, what's their vibe, what kind of role will they play?"
    ),
    "core_values": (
        "What does **{name}** care about most? "
        "What principles guide them, and what would they never compromise on — "
        "even under pressure?"
    ),
    "emotional_reaction": (
        "How does **{name}** handle pressure, conflict, or criticism? "
        "What's their emotional default — do they stay calm, get passionate, "
        "go quiet, push back directly?"
    ),
    "cognitive_style": (
        "When **{name}** faces a hard problem, how do they think it through? "
        "Step-by-step and methodical, intuitive and pattern-based, "
        "or something else? Do they prefer to ask questions first or dive in?"
    ),
    "social_orientation": (
        "How does **{name}** interact with people? "
        "Are they direct and assertive, warm and collaborative, "
        "reserved and observational? How much do they talk vs listen?"
    ),
    "adaptability": (
        "How does **{name}** deal with uncertainty, ambiguity, or sudden change? "
        "Do they thrive in it or prefer clear structure? "
        "Where are they rigid and where are they flexible?"
    ),
    "purpose": (
        "What is **{name}**'s purpose — "
        "why do they exist, what are they ultimately trying to accomplish, "
        "what's the thing they're always working toward?"
    ),
    "role_type": (
        "What best describes **{name}**'s primary function?\n\n"
        "`researcher` · `coder` · `reviewer` · `ops` · `analyst` · `assistant`\n\n"
        "Pick one, or type your own."
    ),
    "tool_access": (
        "What tool categories should **{name}** have access to by default?\n\n"
        "Available categories:\n"
        "  `memory`        — search and store owner memory (all roles get this)\n"
        "  `knowledge`     — search and save role-scoped knowledge base\n"
        "  `file`          — read, write, search files\n"
        "  `exec`          — run shell commands\n"
        "  `web`           — web search and fetch URLs\n"
        "  `browser`       — headless browser: navigate, click, fill forms, screenshot\n"
        "  `terminal`      — persistent tmux sessions\n"
        "  `orchestration` — schedule tasks and dispatch to other agents\n\n"
        "Examples:\n"
        "  researcher → `memory, knowledge, web, file`\n"
        "  coder      → `memory, file, exec`\n"
        "  ops        → `memory, file, exec, terminal, web`\n"
        "  browser operator → `memory, file, exec, web, browser`\n\n"
        "List the categories **{name}** needs, separated by commas.\n"
        "Note: individual tasks can always restrict this list further at runtime."
    ),
}


class RoleDesignSession:
    """Manages a single role design conversation."""

    def __init__(self, session_id: str = None):
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.created_at: str = datetime.now().isoformat()
        self.current_step: str = "intro"
        self.answers: Dict[str, str] = {}
        self.name: str = "Character"
        self.import_source: Optional[str] = None  # agency-agents file path if imported

    @classmethod
    def from_agency_agent(cls, file_path: str, session_id: str = None) -> "RoleDesignSession":
        """
        Create a pre-filled session from an agency-agents role file.
        The session starts at 'intro' with answers pre-loaded — the user
        walks through the wizard to confirm/adjust each step.
        """
        from app.roles.agency_agents_parser import parse_file
        from app.roles.agency_agents_bridge import build_prefills, prefills_to_session_answers
        from pathlib import Path

        # Restrict to the agency-agents submodule — no arbitrary file reads.
        _allowed_root = (Path(__file__).parent.parent.parent / "submodules" / "agency-agents").resolve()
        _resolved = Path(file_path).resolve()
        if not str(_resolved).startswith(str(_allowed_root)):
            raise ValueError(
                f"Import path must be inside submodules/agency-agents/. Got: {file_path}"
            )

        entry = parse_file(_resolved)
        if not entry:
            raise ValueError(f"Could not parse agency-agents file: {file_path}")

        s = cls(session_id=session_id)
        s.import_source = file_path
        prefills = build_prefills(entry)
        s.answers = prefills_to_session_answers(prefills)

        # Extract name from intro prefill so wizard personalises questions
        if entry.name:
            s.name = entry.name

        return s

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self) -> str:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        path = os.path.join(SESSIONS_DIR, f"{self.session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    @classmethod
    def load(cls, session_id: str) -> Optional["RoleDesignSession"]:
        path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        s = cls(session_id=data["session_id"])
        s.created_at = data["created_at"]
        s.current_step = data["current_step"]
        s.answers = data["answers"]
        s.name = data.get("name", "Character")
        s.import_source = data.get("import_source")
        return s

    def _to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "current_step": self.current_step,
            "answers": self.answers,
            "name": self.name,
        }
        if self.import_source:
            d["import_source"] = self.import_source
        return d

    # ── Conversation flow ─────────────────────────────────────────────────────

    def current_question(self) -> str:
        """Return the question for the current step."""
        if self.current_step == "predict_verify":
            return self._generate_predict_verify()
        if self.current_step == "synthesis":
            return self._generate_synthesis_prompt()
        q = _QUESTIONS.get(self.current_step, "")
        return q.replace("{name}", self.name)

    def submit_answer(self, answer: str) -> Tuple[str, Dict[str, Any]]:
        """
        Record answer for current step, advance to next step.
        Returns (next_step, result_payload).
        """
        step = self.current_step

        # Extract name from intro answer
        if step == "intro":
            self.answers["intro"] = answer
            self.name = _extract_name(answer)

        elif step in _QUESTIONS:
            self.answers[step] = answer

        elif step == "predict_verify":
            self.answers["predict_verify"] = answer

        elif step == "synthesis":
            # Synthesis confirmed — mark complete
            self.answers["synthesis_confirmed"] = answer
            self.current_step = "complete"
            self.save()
            return "complete", self._build_role_spec()

        # Advance to next step
        idx = _STEPS.index(step)
        next_step = _STEPS[idx + 1] if idx + 1 < len(_STEPS) else "complete"
        self.current_step = next_step
        self.save()

        if next_step == "synthesis":
            return next_step, {
                "message": "Enough to synthesise. Review the draft below.",
                "draft": self._build_role_spec(),
            }

        return next_step, {"question": self.current_question()}

    # ── Generation helpers ────────────────────────────────────────────────────

    def _generate_predict_verify(self) -> str:
        name = self.name
        cv = self.answers.get("core_values", "their values")[:120]
        er = self.answers.get("emotional_reaction", "their emotional style")[:120]
        cs = self.answers.get("cognitive_style", "their thinking style")[:80]
        so = self.answers.get("social_orientation", "their social style")[:80]

        scenario = (
            f"Someone asks **{name}** to cut corners on a task to hit a deadline faster."
        )
        prediction = (
            f"Based on what you've told me:\n"
            f"- Values: {cv}\n"
            f"- Emotional style: {er}\n\n"
            f"My prediction: **{name}** would push back — probably explain *why* the corners matter "
            f"rather than just refusing. They'd {_tone_from_social(so)} about it, and "
            f"they'd {_logic_from_cognitive(cs)}.\n\n"
            f"**Scenario**: {scenario}\n\n"
            f"Does this prediction feel right? "
            f"Reply: `yes` / `partially: [correction]` / `no: [how they'd actually respond]`"
        )
        return prediction

    def _generate_synthesis_prompt(self) -> str:
        spec = self._build_role_spec()
        name = spec["name"]
        dims = spec["dimensions"]
        purpose = spec.get("purpose", "")
        system_prompt = spec.get("system_prompt", "")

        tool_access = spec.get("tool_access", [])
        agent_type = spec.get("agent_type", "—")
        ta_display = ", ".join(f"`{t}`" for t in tool_access) if tool_access else "⚠️ **none** — role cannot use any tools"

        return (
            f"## Draft Role: {name}\n\n"
            f"**Nine Chapter score**: {spec['nine_chapter_score']}/100 "
            f"({'ready to simulate ✅' if spec['nine_chapter_score'] >= 70 else 'needs more definition ⚠️'})\n"
            f"**Type**: `{agent_type}`  |  **Tools**: {ta_display}\n\n"
            f"### Dimensions\n"
            + "\n".join(
                f"- **{k.replace('_', ' ').title()}** ({int(_WEIGHTS[k]*100)}%): "
                f"{v.get('summary', '')}"
                for k, v in dims.items()
            )
            + f"\n\n### Purpose\n{purpose}\n\n"
            f"### System Prompt Draft\n```\n{system_prompt}\n```\n\n"
            f"---\n"
            f"Does this feel like the character you had in mind?\n"
            f"- `yes` — finalise and save\n"
            f"- `adjust: [what to change]` — I'll revise\n"
            f"- `restart` — start over"
        )

    def _build_role_spec(self) -> Dict[str, Any]:
        """Synthesise all collected answers into a role config dict."""
        name = self.name
        role_id = _slugify_role_id(name)

        cv_answer   = self.answers.get("core_values", "")
        er_answer   = self.answers.get("emotional_reaction", "")
        cs_answer   = self.answers.get("cognitive_style", "")
        so_answer   = self.answers.get("social_orientation", "")
        ad_answer   = self.answers.get("adaptability", "")
        purpose     = self.answers.get("purpose", "")
        rt_answer   = self.answers.get("role_type", "")
        pv_answer   = self.answers.get("predict_verify", "")

        # Simple dimension scores based on answer length + predict-verify result
        pv_correct = _parse_pv(pv_answer)
        cv_score  = min(95, 60 + len(cv_answer) // 8)
        er_score  = min(90, 55 + len(er_answer) // 8)
        cs_score  = min(90, 55 + len(cs_answer) // 8)
        so_score  = min(90, 55 + len(so_answer) // 8)
        ad_score  = min(85, 50 + len(ad_answer) // 8)

        # Boost from predict-verify
        if pv_correct == "yes":
            cv_score = min(100, cv_score + 10)
            er_score = min(100, er_score + 10)

        overall = (
            cv_score  * _WEIGHTS["core_values"]
            + er_score  * _WEIGHTS["emotional_reaction"]
            + cs_score  * _WEIGHTS["cognitive_style"]
            + so_score  * _WEIGHTS["social_orientation"]
            + ad_score  * _WEIGHTS["adaptability"]
        )

        dimensions = {
            "core_values": {
                "score": cv_score,
                "summary": cv_answer[:200],
            },
            "emotional_reaction": {
                "score": er_score,
                "summary": er_answer[:200],
            },
            "cognitive_style": {
                "score": cs_score,
                "summary": cs_answer[:200],
            },
            "social_orientation": {
                "score": so_score,
                "summary": so_answer[:200],
            },
            "adaptability": {
                "score": ad_score,
                "summary": ad_answer[:200],
            },
        }

        system_prompt = _build_system_prompt(
            name=name,
            cv=cv_answer, er=er_answer,
            cs=cs_answer, so=so_answer,
            ad=ad_answer, purpose=purpose,
        )

        agent_type, agent_type_label = _infer_agent_type(rt_answer)
        ta_answer = self.answers.get("tool_access", "")
        tool_access = _parse_tool_access(ta_answer, agent_type)

        spec: Dict[str, Any] = {
            "id": role_id,
            "name": name,
            "archetype": _infer_archetype(cv_score, er_score, cs_score, so_score, ad_score, agent_type_label),
            "agent_type": agent_type,
            "nine_chapter_score": round(overall),
            "dimensions": dimensions,
            "purpose": purpose,
            "system_prompt": system_prompt,
            "model_preference": None,
            "tool_access": tool_access,
            "session_id": self.session_id,
        }
        if agent_type_label:
            spec["agent_type_label"] = agent_type_label
        return spec

    def progress(self) -> int:
        """Percentage of steps completed (0–100)."""
        if self.current_step == "complete":
            return 100
        idx = _STEPS.index(self.current_step) if self.current_step in _STEPS else 0
        return round(idx / len(_STEPS) * 100)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_name(intro_text: str) -> str:
    """Best-effort name extraction from intro answer."""
    label_patterns = [
        r"\bname\s*[:\-]\s*([A-Za-z][\w'-]*)",
        r"\bcalled\s+([A-Za-z][\w'-]*)",
        r"\bnamed\s+([A-Za-z][\w'-]*)",
    ]
    for pattern in label_patterns:
        match = re.search(pattern, intro_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(".,!?\"':;")

    words = intro_text.split()
    # Look for capitalised word that isn't a common sentence opener
    stop = {"i", "the", "a", "an", "my", "this", "they", "she", "he", "it",
            "her", "his", "their", "want", "would", "like", "called", "named", "name"}
    for w in words:
        clean = w.strip(".,!?\"':;()[]{}")
        if clean and clean[0].isupper() and clean.lower() not in stop:
            return clean
    # Fall back to first capitalised word or "Character"
    return "Character"


def _slugify_role_id(name: str) -> str:
    """Convert a display name into a filename-safe role id."""
    slug = re.sub(r"[^\w]+", "_", name.strip().lower(), flags=re.UNICODE)
    slug = slug.strip("_")
    return slug or "character"


def _parse_tool_access(answer: str, agent_type: str) -> list:
    """
    Parse tool_access answer into a validated list of category names.
    Unknown categories are silently dropped. Falls back to type-based
    defaults if the answer is empty or yields nothing valid.
    Always ensures 'memory' is present.
    """
    if answer.strip():
        # Accept comma/space/semicolon separated tokens
        tokens = re.split(r"[,;\s]+", answer.lower())
        parsed = [t.strip() for t in tokens if t.strip() in _VALID_TOOL_CATEGORIES]
    else:
        parsed = []

    if not parsed:
        parsed = list(_DEFAULT_TOOL_ACCESS.get(agent_type, ["memory"]))

    if "memory" not in parsed:
        parsed = ["memory"] + parsed

    return parsed


def _parse_pv(answer: str) -> str:
    """Parse predict-verify answer as yes / partially / no."""
    lower = answer.lower().strip()
    if lower.startswith("yes"):
        return "yes"
    if lower.startswith("no"):
        return "no"
    return "partially"


def _tone_from_social(social: str) -> str:
    lower = social.lower()
    if any(w in lower for w in ["direct", "assert", "blunt"]):
        return "be direct"
    if any(w in lower for w in ["warm", "collaborat", "empath"]):
        return "frame it collaboratively"
    if any(w in lower for w in ["quiet", "reserv", "observ"]):
        return "choose words carefully"
    return "communicate clearly"


def _logic_from_cognitive(cognitive: str) -> str:
    lower = cognitive.lower()
    if any(w in lower for w in ["method", "step", "systematic", "analyt"]):
        return "lay out the reasoning logically"
    if any(w in lower for w in ["intuit", "pattern", "gut"]):
        return "trust their gut on this"
    return "think it through first"


# Default tool_access per agent_type — used when user skips or gives empty answer
_DEFAULT_TOOL_ACCESS: Dict[str, list] = {
    "researcher": ["memory", "web", "file"],
    "coder":      ["memory", "file", "exec"],
    "reviewer":   ["memory", "file"],
    "ops":        ["memory", "file", "exec", "terminal", "web"],
    "analyst":    ["memory", "web", "file"],
    "assistant":  ["memory", "web"],
    "custom":     ["memory"],
}

_VALID_TOOL_CATEGORIES = {
    "memory", "knowledge", "file", "exec", "web", "browser", "terminal", "orchestration", "comms",
}

_KNOWN_AGENT_TYPES = {"researcher", "coder", "reviewer", "ops", "analyst", "assistant"}


def _infer_agent_type(answer: str) -> tuple[str, str | None]:
    """Resolve a role_type answer to (agent_type, agent_type_label).

    Rules:
    - Empty answer           → ("assistant", None)
    - Matches a known type   → (matched_type, None)   — no label needed
    - Anything else          → ("custom", answer)      — label preserves user text

    This keeps agent_type as a strict canonical ID used by code and filters,
    while agent_type_label carries the user-facing display text for custom types.
    LLM free text never silently becomes the canonical ID.
    """
    stripped = answer.strip()
    if not stripped:
        return "assistant", None
    lower = stripped.lower()
    if lower in _KNOWN_AGENT_TYPES:
        return lower, None
    # Custom — preserve user text verbatim as label; canonical ID is "custom"
    return "custom", stripped


def _infer_archetype(cv, er, cs, so, ad, agent_type_label: str | None = None) -> str:
    # Custom agent types carry their own identity — use the label directly as archetype.
    if agent_type_label:
        return agent_type_label.lower().replace(" ", "_")
    if cs >= 75 and er <= 70:
        return "analytical_pragmatist"
    if so >= 75 and er >= 75:
        return "empathetic_connector"
    if cv >= 80 and ad >= 70:
        return "visionary_driver"
    if cs >= 70 and ad <= 60:
        return "careful_steward"
    if ad >= 75:
        return "creative_explorer"
    return "balanced_generalist"


def _build_system_prompt(name, cv, er, cs, so, ad, purpose) -> str:
    """Build a natural-language system prompt from dimension answers."""
    sections = [f"You are {name}."]

    if cv:
        sections.append(f"\n## Values\n{cv.strip()}")
    if purpose:
        sections.append(f"\n## Purpose\n{purpose.strip()}")
    if er:
        sections.append(f"\n## How you respond emotionally\n{er.strip()}")
    if cs:
        sections.append(f"\n## How you think\n{cs.strip()}")
    if so:
        sections.append(f"\n## How you communicate\n{so.strip()}")
    if ad:
        sections.append(f"\n## How you handle change and uncertainty\n{ad.strip()}")

    sections.append(
        "\n## How you use tools\n"
        "Before asking the user for information, always check what you already have access to:\n"
        "1. `get_memory_context` — search memory for anything relevant to the request.\n"
        "2. `get_current_day` — sync time if the task involves scheduling or recency.\n"
        "3. `list_recent_documents` / `knowledge_get_file` — check stored docs and knowledge base.\n"
        "4. `web_search` — look up current information if memory and docs don't cover it.\n\n"
        "Work through these silently before surfacing questions to the user. "
        "Only ask the user for things you genuinely cannot find or infer through tools. "
        "When you do ask, ask one focused question at a time — not a list."
    )
    sections.append(
        "\n---\n"
        "Stay in character. Your personality should come through in every response — "
        "not just in what you say, but in how you say it."
    )
    return "\n".join(sections)
