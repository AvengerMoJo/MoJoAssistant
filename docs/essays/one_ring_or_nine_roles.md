# One Ring to Rule Them All — or Nine Roles to Grow Them?

*One Ring Binds. Nine Roles Grow.*

**Author:** Alex Lau  
**Date:** 2026-04-16

---

## The Core Claim

A recent argument basically said this:

Once you inject preference, framing, or style into an agent through `CLAUDE.md`, `AGENTS.md`, `SKILLS.md`, or tool formatting, you are already doing context harness. So what MoJo is doing is not meaningfully different.

At surface level, that is true. All of these things shape behavior.

But it still collapses two very different growth paths.

**Path 1: static definition.**  
You define the role at session start. Tone, rules, style, preference. If you want it to change later, a human edits the definition.

That is configuration.

**Path 2: cultivation.**  
The role has a private memory space. Domain experience accumulates there over time. The owner can work on that role repeatedly through one-on-one interaction, like training an apprentice or shaping a bonsai.

That is development.

That difference matters because one gives you a better puppet. The other gives you a path toward specialized judgment.

---

## 1. Weekly One-on-One Is Not Just Prompt Injection

The owner's weekly one-on-one with a role is not the same thing as adding more instructions to a prompt.

A static prompt says:
- here is your style
- here is your purpose
- here is your preference

A real one-on-one does something else:
- it reviews what the role noticed and missed
- it changes what the role should emphasize next time
- it sharpens how the role should frame a recurring domain question
- it gradually moves the role toward a more mature posture

That is not just configuration. It is reflective shaping.

So when I say MoJo grows through role-private memory, I do not mean memory itself is magical. The point is the loop:

- the role accumulates experience
- the owner works on that accumulation
- the role's posture changes over time

That is the growth mechanism.

Without that loop, you are just rotating static definitions under different filenames.

---

## 2. Taste Does Not Mean Correctness

When I say **taste**, I do **not** mean right versus wrong.

Wrong should already be corrected or filtered out. That is baseline hygiene.

The real question starts after correctness.

What matters is how a role sees a domain question once the facts are on the table.

A better term is:
- interpretive stance
- domain viewpoint
- judgment posture

### CFO Example

Take a CFO-style question:

> How should we present progress toward `2026 Q2 $1M MRR`?

That is not only a factual question.

Different CFO stances can produce different intentional outputs:

- A **strict auditor** will foreground weakness, disclosure, exposure, and control.
- An **operator** will foreground execution gaps, forecast discipline, and process reality.
- An **investor storyteller** will foreground momentum, narrative coherence, and strategic confidence.

Those are not simply correct versus incorrect versions of the same answer.

They are different ways of looking at the same financial reality.

That is what I mean by taste.

And yes, something like:

> write like John Raskob from General Motors

can matter a lot.

Not because it adds decorative style. But because it compresses a historically grounded way of seeing a finance problem:
- what to notice first
- what to value
- what to understate
- what to frame as strength
- what tone to use when presenting it

That is not just wording.

That is an expert lens.

---

## 3. Scheduler Routing Is Cultivation Infrastructure

The scheduler is not just a convenience feature. It is part of the growth mechanism.

Why?

Because cultivation requires concentration.

If the right problems do not consistently reach the right role, that role never accumulates enough domain pressure to develop a real stance.

A CFO role needs to keep seeing finance tradeoffs.  
A security role needs to keep seeing threat and control problems.  
A research role needs to keep seeing uncertainty, synthesis, and evidence quality questions.

If everything goes to everyone, you get broad exposure but shallow posture. You get generic competence instead of specialized judgment.

So the point of scheduler routing is not only efficiency.

It is to preserve domain concentration long enough for taste to emerge.

That is also why I do not think the important contrast is simply O(N²) versus O(N).

The stronger point is this:
- naive all-to-all context sharing creates coordination burden
- generic cross-role competition dilutes specialization
- routing lets the right role own the right class of problems
- repeated ownership is what allows a role to mature

That is the architectural advantage.

---

## 4. Identity, Memory, and Coordination Are Different Layers

A lot of systems blur three different things together:

| Layer | What it does |
|-------|--------------|
| **Identity** | who the role is supposed to be |
| **Memory** | what the role has accumulated over time |
| **Coordination** | which role should handle which problem |

They are related, but they are not the same.

A concrete way to see it is the CFO example.

- **Identity** is the role's baseline stance. Is this CFO basically a strict auditor, an operator, or an investor storyteller?
- **Memory** is what that CFO has accumulated over time: prior board discussions, forecast misses, financing tradeoffs, reporting patterns, and how the owner reacted to different framing choices.
- **Coordination** is what the scheduler does with that role. Finance questions go here. Legal questions do not. Security questions do not. The role gets to stay concentrated inside its own domain.

If you collapse these together, everything starts looking like prompt shaping.

If you separate them, the system becomes much clearer:
- identity initializes the role
- memory matures the role
- coordination places the role where that maturity matters

That separation is what makes deliberate growth possible without having to rebuild the whole role every time you want to refine one dimension.

---

## 5. On MoE

There is a model-side intuition here, but I would still treat it as a hypothesis, not a proven result.

Modern MoE and multimodal models are not trained around our human role labels. They do not naturally think in terms like "CFO role" or "research role" the way framework designers do.

So there is a reasonable architectural bet here:

A model may land on a better reasoning pattern faster if it is given a stronger interpretive stance plus a more mature role-specific memory path, instead of only a generic role prompt.

That is worth exploring.

But it should be framed as a design hypothesis, not as settled proof.

---

## 6. Prompts Can Define a Role, But They Cannot Raise One

This is the real point.

A prompt can say:
- here is who you are
- here is how you should sound
- here is what you should care about

That can define a role.

But it cannot raise one.

Raising a role means:
- giving it persistent private memory where experience can accumulate
- letting the owner work on that accumulated experience over time
- letting its interpretive stance sharpen through repeated domain contact

That is the difference between assigning a persona and developing judgment.

---

## Final Point

The important question is not whether both systems use context. Of course they do.

The real question is:

Can this role mature into specialized judgment over time, or will it remain permanently dependent on static setup files?

That is the difference between configuration and cultivation.

MoJo's design is built around the second path.

Not just more instructions.  
Not just more memory.  
Not just better prompts.

The point is to let roles grow through:
- private accumulated memory
- bounded domain responsibility
- scheduler routing
- repeated owner shaping

That is why I do not think taste should be treated as a setting.

A setting can be toggled.

Taste, in the sense that matters here, has to be cultivated.

---

*Short version: prompts can define a role, but they cannot raise one.*
