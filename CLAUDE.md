# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Sales CRM Platform — Backend (Phase 1)

## Status
This is a fresh scaffold: package layout exists (`app/api/v1`, `app/core`,
`app/db`, `app/models`, `app/schemas`, `app/services`, `tests/`) but every
directory is empty except `app/main.py` (also empty) and `app/__init__.py`.
No dependencies are installed yet, no migrations exist, no tests exist.
Nothing in "Implemented" in `README.md` is done. Treat every resource as
being built from zero — there is no existing pattern to copy yet for the
first one you build; `.claude/commands/new-endpoint.md` and the agents in
`.claude/agents/` define the intended shape.

## Commands
```bash
uv sync                              # install deps (first time / after pyproject changes)
uv run alembic upgrade head          # apply migrations
uv run uvicorn app.main:app --reload # run dev server

uv run ruff check .                  # lint
uv run mypy app                      # typecheck
uv run pytest                        # full test suite
uv run pytest tests/path/to_test.py::test_name   # single test
```
`.claude/hooks/post-edit.sh` runs ruff + mypy + pytest after every Edit/Write —
a failure there is a blocker per CLAUDE.md rule 6, not something to defer.

## What this project does
FastAPI backend for InnoBoon's Sales Prospecting & CRM Platform, Phase 1 scope:
Login/RBAC, Lead Management, Account Management, Contact Management,
Deal/Opportunity Management, plus supporting Dashboard, Notifications,
and Activity Log. Includes a static (non-dynamic) Pre-Sales Checklist.

Business context: B2B services sales CRM, not e-commerce/B2C.
Flow: Lead -> qualify (Go/No-Go) -> convert to Account -> Deal moves
through pipeline stages -> checklist gates proposal quality (Sales +
Delivery SME joint ownership on some items) -> Closed Won / Closed Lost / Cold.

Deal stages (Phase 1, confirmed at kickoff — do NOT use the stage list
from the original scope PDF, it's outdated):
Received Requirements -> Qualified to Buy -> Evaluation -> Proposals ->
Contracts -> Closed Won | Closed Lost | Cold Deals

Roles: Sales Rep, Delivery/Technical SME, Sales Manager/Director, Admin.
"Joint" checklist ownership is not a login role — it means both Sales
and Delivery must sign off on that item.

Explicitly OUT of scope for Phase 1 (do not build these even if the
original scope PDF mentions them):
- Document Management / Proposals repository
- Staff Augmentation (both resource list and opportunity tracking)
- Dynamic / templated / stage-gated checklist logic — Phase 1 checklist
  is a flat, static list of items with a status toggle and notes field

Reference docs live in `docs/`:
- `docs/phase1-kickoff-email.md` — the SOURCE OF TRUTH for Phase 1 scope
- `Scope & User Story Document - Sales CRM Platform.pdf` (repo root) —
  original full-vision scope doc, not yet moved into `docs/`. Useful for
  screen/field detail and user-story language, but any conflict with the
  kickoff email loses. The kickoff email wins.

## Where things live
- `app/main.py` — FastAPI app entrypoint, router registration
- `app/api/v1/` — route modules, one file per resource:
  `auth.py`, `leads.py`, `accounts.py`, `contacts.py`, `deals.py`,
  `checklist.py`, `activities.py`, `notifications.py`, `dashboard.py`
- `app/models/` — SQLAlchemy ORM models
- `app/schemas/` — Pydantic request/response schemas (never expose
  ORM models directly through the API)
- `app/services/` — business logic that doesn't belong in a route:
  duplicate-lead-email detection, deal stage-transition + history
  logging, notification generation, dashboard aggregation queries
- `app/core/` — settings (pydantic-settings), JWT auth, RBAC
  dependencies (`require_role(...)`)
- `app/db/` — session factory, declarative base, Alembic migrations
- `tests/` — pytest, directory structure mirrors `app/`
- `.claude/agents/` — subagent definitions for parallel work
- `.claude/commands/` — reusable slash commands
- `.claude/hooks/` — self-validation scripts (lint, typecheck, test)
- `README.md` — running log of what's actually implemented, updated
  after every feature (this is the source of truth on build status,
  not this file)

## How work gets done

1. **WHY before WHAT/HOW.** Before implementing anything, state in one
   line the business reason for the task, tied to a specific Phase 1
   scope item or user story. If it's unclear which stage/screen/story
   this maps to, ask before building.

2. **Plan Mode first.** Never write code before a plan is proposed and
   approved, except for trivial one-line fixes.

3. **Verify, don't guess, on anything load-bearing.** For current
   FastAPI/SQLAlchemy/Pydantic/Alembic API behavior, library version
   quirks, or anything time-sensitive, use the Context7 MCP server or
   web search. Do not answer from stale pretraining for anything that
   affects a real implementation decision.

4. **TDD.** Write a failing test first, then implement, for every
   endpoint and every service function. No exceptions for "it's simple."

5. **Simplest effective solution.** No speculative abstraction, no
   generic frameworks for a single use case. Equally: don't skip
   validation, error handling, or the duplicate-check/stage-history
   logic in the name of "keeping it simple" — those are explicit
   requirements, not extras.

6. **Self-validation loop, every change.** Run lint (ruff), typecheck
   (mypy), and tests (pytest) via `.claude/hooks/post-edit.sh` after
   every edit. A failure is a blocker — fix it before moving to the
   next task, don't hand back red code.

7. **Full ownership.** Implement the feature, run the tests yourself,
   fix failures yourself. Only return control to me for manual
   verification once everything is green end-to-end.

8. **Git is read-only for you.** Never run `git commit`, `git push`,
   `git reset`, `git checkout`, `git rebase`, `git branch -d`, `git
   merge`, or any other history-mutating command. `git log`, `git
   diff`, `git status`, `git show` are fine. I handle all commits.

9. **Subagents for parallelizable work.** For multi-part features
   (e.g., a new resource = model + schema + route + service + tests),
   act as the manager: delegate independent pieces to the subagents in
   `.claude/agents/`, then integrate and validate the result yourself.

10. **Product framing.** Before or after implementing a feature, give a
    short summary of what it does from a product-owner's perspective —
    what can a user now do that they couldn't before — not just a code
    diff summary.

11. **Track it in README.md.** After every completed feature, add a
    line under "Implemented" in `README.md`. This is how progress
    against the Week 1 / Week 2 / Week 3 milestones gets tracked.

## Current milestone
Week 1 (per kickoff email): Login, RBAC, Lead Management, Navigation.
Demo target: login flow + full lead CRUD/filter/search working.
