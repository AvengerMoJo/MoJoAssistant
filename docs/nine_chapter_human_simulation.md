# Nine Chapter Human Simulation Framework
# 九章心格人格模拟框架

> Consolidated from: NINE_CHAPTER_README, NINE_CHAPTER_SYSTEM, NINE_CHAPTER_SYSTEM_DOCUMENTATION,
> NINE_CHAPTER_COMPLETE_WORKFLOW, NINE_CHAPTER_CHATBOT_DESIGN, NINE_CHAPTER_WORKFLOW
> Source project: YiAi/GetToKnow

---

## What It Is

Nine Chapter (九章心格) is a psychological profiling framework that builds a **digital twin** of a
person's psychology through progressive assessment. The core insight: once you understand someone
across nine developmental dimensions to ≥70% confidence, you can reliably simulate how they would
respond to novel situations.

The system was built as a chatbot — asking targeted questions, predicting how the person would
answer (then verifying), iterating until the understanding threshold is crossed. At that point the
profile drives behavior simulation rather than just description.

**For MoJoAssistant**: the same framework applies to AI roles. Instead of profiling a human, you
use the nine dimensions to *define* a role's personality — giving it consistent, predictable
behavior that feels coherent rather than prompt-engineered.

---

## The Two Dimension Sets

The project uses two overlapping dimension sets. Both matter for role design.

### Set A — Five Scoring Dimensions (operational weights)

Used for scoring and simulation gating. These are the weights the AI uses when evaluating how well
it understands a subject (or, in role design, how strongly each dimension governs a role's
behavior).

| Dimension | Chinese | Weight | What It Governs |
|---|---|---|---|
| Core Values | 核心价值观 | **30%** | Fundamental beliefs, ethical principles, life priorities |
| Emotional Reaction | 情绪反应 | **25%** | Stress response, emotional regulation, conflict handling |
| Cognitive Style | 认知风格 | **20%** | Decision-making patterns, information processing, problem approach |
| Social Orientation | 社交取向 | **15%** | Interpersonal preferences, communication style, collaboration |
| Adaptability | 适应能力 | **10%** | Change tolerance, learning agility, flexibility |

**Total: 100%.** Core Values dominates — it is the anchor from which everything else derives
consistency. Emotional Reaction is second because it colors *how* values are expressed under
pressure.

### Set B — Nine Developmental Chapters (the full arc)

These are the nine areas a person (or role) develops through. They map onto Set A but add depth:
purpose, growth orientation, and integration as higher-order layers.

| # | Chapter | Chinese | Dev Weight | Maps to Set A |
|---|---|---|---|---|
| 1 | Self-Awareness | 自我认知 | 15% | Cognitive Style, Emotional Reaction |
| 2 | Emotional Regulation | 情绪管理 | 20% | Emotional Reaction |
| 3 | Cognitive Style | 认知风格 | 10% | Cognitive Style |
| 4 | Social Orientation | 社会取向 | 15% | Social Orientation |
| 5 | Adaptability | 适应能力 | 10% | Adaptability |
| 6 | Core Values | 核心价值观 | 30% | Core Values |
| 7 | Purpose & Meaning | 人生意义 | 25% | Core Values (direction layer) |
| 8 | Growth Mindset | 成长心态 | 15% | Adaptability, Cognitive Style |
| 9 | Integration & Wholeness | 整合完整 | 20% | All — coherence across dimensions |

Chapter 9 (Integration) is the meta-dimension: it measures whether the other eight form a
*coherent whole* rather than contradicting each other. A well-designed role needs this — its
values, emotional responses, and social style should feel like the same entity.

---

## The 70% Simulation Threshold

The original system gates behavior simulation at **≥70% overall understanding score**:

```
overall_score = (core_values × 0.30) + (emotional_reaction × 0.25)
              + (cognitive_style × 0.20) + (social_orientation × 0.15)
              + (adaptability × 0.10)
```

Below 70%: the profile is descriptive only — you know *about* the person but can't reliably predict
their behavior.

Above 70%: simulation is unlocked — given a new stimulus, the profile generates a response
consistent with all five dimensions simultaneously.

**For role design**: instead of building up to 70% through Q&A, you *define* a role at 70%+ from
the start by explicitly specifying all five dimensions. The threshold becomes a completeness
requirement — a role spec that doesn't address all five dimensions isn't ready to run.

### Developmental Stages

| Score Range | Stage | Meaning for Roles |
|---|---|---|
| < 55% | beginning_explorer | Under-specified, unpredictable |
| 55–65% | developing_learner | Partial — some behaviors consistent |
| 65–75% | proficient_developer | Mostly consistent, some gaps |
| 75–85% | advanced_integrator | Reliable, coherent personality |
| ≥ 85% | master_integrator | Fully integrated, highly predictable |

---

## How Simulation Works

Given a complete profile, the simulation engine generates responses by applying all five dimensions
simultaneously:

```python
def simulate_response(stimulus, profile):
    emotional_response  = apply_emotional_reaction(stimulus, profile)
    cognitive_framing   = apply_cognitive_style(stimulus, profile)
    value_filter        = apply_core_values(stimulus, profile)
    social_tone         = apply_social_orientation(stimulus, profile)
    flexibility_bounds  = apply_adaptability(stimulus, profile)

    return synthesize(emotional_response, cognitive_framing,
                      value_filter, social_tone, flexibility_bounds)
```

The key is that **all five dimensions apply to every response** — not sequentially but as
simultaneous constraints. A role with high Core Values (integrity-focused) + low Social Orientation
(introverted/direct) + high Cognitive Style (analytical) will give an analytically framed, blunt,
integrity-first answer to any question, regardless of topic.

### Prediction + Verification Loop

The original chatbot used a "predict then verify" loop to build understanding:

```
AI predicts: "I think you would say X about this topic"
User confirms: ✅ correct / 🤔 partially / ❌ wrong
AI asks: "What I most want to understand about you is: [curiosity question]"
User answers → profile updates → score rises
```

This loop is directly applicable to role calibration: instead of a user confirming AI predictions,
you run test scenarios against a role spec and verify whether outputs match the intended personality.

---

## Profile Data Structure

A complete Nine Chapter profile for a person or role:

```json
{
  "id": "profile_id",
  "overall_score": 76.8,
  "can_simulate": true,
  "developmental_stage": "advanced_integrator",

  "dimensions": {
    "core_values": {
      "score": 85.0,
      "completeness": 90,
      "dominant_values": ["integrity", "efficiency", "quality"],
      "value_hierarchy": "results > process > relationships",
      "behavioral_patterns": "will sacrifice speed for correctness"
    },
    "emotional_reaction": {
      "score": 70.0,
      "completeness": 70,
      "typical_responses": "calm under pressure, direct when frustrated",
      "stress_management": "retreats to analysis before responding",
      "conflict_style": "addresses conflict directly, dislikes avoidance"
    },
    "cognitive_style": {
      "score": 81.0,
      "completeness": 85,
      "decision_pattern": "data-first, then intuition check",
      "problem_approach": "systematic decomposition",
      "learning_style": "learn by doing, then read theory"
    },
    "social_orientation": {
      "score": 74.5,
      "completeness": 75,
      "communication_style": "direct, concise, dislikes small talk",
      "collaboration_preference": "independent work + sync at milestones",
      "relationship_pattern": "few deep vs many shallow"
    },
    "adaptability": {
      "score": 79.0,
      "completeness": 80,
      "change_tolerance": "embraces change when rationale is clear",
      "learning_agility": "fast learner in new domains",
      "flexibility_bounds": "flexible on method, inflexible on values"
    }
  },

  "integration": {
    "coherence_score": 82.0,
    "dominant_archetype": "analytical_pragmatist",
    "tension_points": ["efficiency vs thoroughness"],
    "strengths": ["clear reasoning", "consistent values", "adaptable execution"],
    "blind_spots": ["underestimates emotional dimension in others"]
  }
}
```

---

## Mapping to AI Role Design

The framework maps directly to what an AI role needs to be consistent:

| Nine Chapter Dimension | Role Config Field | What It Controls |
|---|---|---|
| Core Values | `values`, `principles` | What the role refuses to do; what it always prioritizes |
| Emotional Reaction | `tone`, `stress_response` | How it responds under pressure, criticism, ambiguity |
| Cognitive Style | `reasoning_approach`, `decision_style` | How it structures answers, level of detail, logic vs intuition |
| Social Orientation | `communication_style`, `verbosity` | Direct/indirect, formal/casual, terse/expansive |
| Adaptability | `flexibility`, `learning_stance` | How it handles novel situations, whether it hedges or commits |
| Purpose & Meaning | `role_mission`, `primary_goal` | Why this role exists; what it's optimizing for |
| Growth Mindset | `feedback_response`, `iteration_style` | Does it revise, ask for feedback, admit uncertainty |
| Integration | `personality_coherence` | Whether all the above form a single believable character |

### Minimum Viable Role Spec

A role that doesn't specify all five Set A dimensions is below 70% — it will behave
inconsistently. The minimum viable role spec addresses:

1. **Core Values** — at least 3 explicit values + what they will/won't compromise on
2. **Emotional Reaction** — default tone + how it changes under pressure
3. **Cognitive Style** — how it structures reasoning (systematic/intuitive, detailed/concise)
4. **Social Orientation** — communication register (direct/collaborative, formal/casual)
5. **Adaptability** — how it handles gaps in its knowledge or capability

Chapter 7 (Purpose & Meaning) adds the *why* — a role with a clear mission behaves more
consistently than one defined only by what it does.

---

## Predefined Archetypes (from original system)

The GetToKnow system identified recurring personality archetypes from the scoring combinations.
These are useful as starting templates for role design:

| Archetype | Core Values | Emotional | Cognitive | Social | Adaptability |
|---|---|---|---|---|---|
| **analytical_pragmatist** | High (efficiency, quality) | Medium-low (controlled) | High (systematic) | Low-medium (direct) | Medium |
| **empathetic_connector** | High (relationships, harmony) | High (expressive) | Medium | High (collaborative) | Medium-high |
| **visionary_driver** | High (impact, growth) | Medium (passionate) | High (intuitive) | Medium | High |
| **careful_steward** | High (stability, safety) | Low (stable) | High (detail-oriented) | Medium | Low |
| **creative_explorer** | Medium (autonomy, novelty) | High (expressive) | Medium (lateral) | Medium | Very high |

---

## Assessment Flow (for role calibration)

If you wanted to assess whether a role is performing consistently with its spec:

```
1. Baseline probe
   → run 5–10 test scenarios covering each dimension
   → score responses against expected dimension profile

2. Predict + verify
   → for each dimension: predict what the role would say
   → run the scenario
   → verify match (full / partial / mismatch)

3. Score overall understanding
   → weighted average across dimensions
   → if < 70%: role spec is under-specified, needs more definition

4. Iterate
   → identify lowest-scoring dimension
   → refine that part of the role spec
   → re-probe

5. Integration check
   → run cross-dimension scenarios (e.g. a task that creates
     tension between efficiency and thoroughness)
   → verify the role resolves the tension consistently
```

---

## Key Takeaway for Role System Design

Nine Chapter gives a **structured vocabulary** for personality that avoids vague adjectives like
"helpful" or "professional." Instead of "the researcher is curious and thorough," you can say:

- Core Values: truth-seeking (0.9), completeness (0.8), efficiency (0.5)
- Cognitive Style: systematic decomposition, cites sources, flags uncertainty explicitly
- Emotional Reaction: patient under ambiguity, direct when asked for opinion
- Social Orientation: collegial but not deferential, prefers written over verbal
- Adaptability: high in method, low in standards — will try new approaches but won't lower quality bar
- Purpose: to surface what's actually true, not what's convenient

That role will behave consistently across any task type — research, planning, code review — because
its personality is fully specified, not just named.
