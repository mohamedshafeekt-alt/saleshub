---
description: Plan a feature before writing any code — WHY, then WHAT, then HOW.
---

Before proposing any code, produce a short plan for: $ARGUMENTS

Structure the plan exactly as:

1. **WHY** — one or two lines: what business need/user story from
   `docs/phase1-kickoff-email.md` or `docs/scope-and-user-stories.md`
   does this serve. If you can't identify one, say so and ask rather
   than guessing.
2. **WHAT** — the user-visible behavior/endpoints this adds, in plain
   language, from a product-owner's perspective.
3. **HOW** — files to be created/touched (models, schemas, routes,
   services, tests), in the order they'll be built (tests first).
   Note any subagent delegation you'll use for independent pieces.
4. **Open questions** — anything ambiguous that needs a decision
   before implementation starts.

Stop after presenting the plan. Do not begin implementation until the
plan is approved.
