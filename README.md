# Sales CRM Platform — Backend

FastAPI backend for InnoBoon's Sales Prospecting & CRM Platform, Phase 1.
See `CLAUDE.md` for full context, scope, and working conventions.

## Stack
- Python (uv for dependency management)
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- pytest / pytest-asyncio / httpx

## Setup
```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Running checks
```bash
uv run ruff check .
uv run mypy app
uv run pytest
```

## Implemented
_(updated after every feature — do not batch these)_

- [x] Login / JWT auth (`POST /api/v1/auth/login`, admin-only `POST /api/v1/users`, `scripts/seed_admin.py`)
- [x] RBAC (Sales Rep, Delivery SME, Sales Manager/Director, Admin) — `require_role(...)` dependency
- [x] Admin-create-user no longer accepts a client-supplied password: server generates one and emails it via `app.services.email` (`EmailSender` protocol, `SMTPEmailSender`, injected through `get_email_sender`); `UserCreate`/`User` gained `first_name`/`last_name`
- [x] `created_at`/`updated_at` moved onto the shared `Base` — every future model gets them for free
- [x] Global error handling (`app/core/error_handler.py`): unhandled DB errors and unexpected exceptions return a structured `ErrorResponse`; deliberate `HTTPException`s (401/403/409 etc.) untouched. Simplified `app/core/logging.py` replaces ad-hoc logging.
- [x] Config now loads from a single `APP_CONFIG` JSON blob in `.env` instead of one env var per setting
- [x] Enums moved to `app/models/enums.py` (starting with `UserRole`), re-exported from `app.models.user` for compatibility
- [x] Lead CRUD + filter/search (owner, source, tier, status, company/owner-name search) — `POST/GET/PATCH/DELETE /api/v1/leads`, Sales Rep/Delivery SME/Manager/Admin all have full access; Sales Rep and Delivery SME are scoped to leads they own plus unassigned leads (`owner_id IS NULL`, a shared claimable queue) — Manager/Admin see everything
- [x] Lead duplicate-email detection (409, same pattern as User)
- [x] Lead `tier` and `owner_id` are now optional at creation (a lead can be untiered/unassigned); Lead gained a `status` field (`not_contacted` default, `attempted_to_contact`/`contacted`/`contact_in_future`/`junk_lead`/`lost_lead`), settable on create/PATCH and filterable via `GET /api/v1/leads?status=`
- [x] Account CRUD + filter/search (owner, tier, company/owner-name search) — `POST/GET/PATCH/DELETE /api/v1/accounts`, same RBAC/ownership-scoping as Leads; `POST /api/v1/leads/{id}/convert` turns a Lead into an Account (409 on double-conversion, 400 if the lead has no tier/owner and none was supplied in the optional request body), Lead gains `is_converted`
- [x] Contact CRUD — `POST/GET/PATCH/DELETE /api/v1/contacts`, `GET /api/v1/accounts/{id}/contacts`; no `owner_id` of its own, access gated entirely through the parent Account's owner (Sales Rep/Manager/Admin, Delivery SME 403)
- [x] Deal CRUD + stage transitions + stage history — `POST/GET/PATCH/DELETE /api/v1/deals`, `GET /api/v1/deals/{id}/stage-history`, `GET /api/v1/accounts/{id}/deals`; Deal has its own `owner_id` independent of the account's owner, any stage can move to any other stage (no transition graph), every stage change (including creation) writes a `deal_stage_history` row
- [x] Deal "mark cold with reason" — `cold_reason` on Deal, required (400) whenever the resulting stage is `cold_deals` with no reason on record, whether set on create or via PATCH
- [x] `GET /api/v1/users` — lists all users (unfiltered, including inactive) so the frontend can populate the lead Owner/reassign dropdown; same RBAC as Leads (Sales Rep/Manager/Admin, Delivery SME 403)
- [ ] Static Pre-Sales Checklist per deal
- [ ] Activity log (generic, per lead/account/deal)
- [ ] Notifications (task overdue, stage transition)
- [ ] Dashboard aggregation endpoints (funnel, target vs actual)

## Milestones (per Phase 1 kickoff)
- **Week 1** — Login, RBAC, Lead Management, Navigation
- **Week 2** — Accounts, Contacts, Deals, Activities, Notifications
- **Week 3** — Dashboard, QA/UAT, optimization, deployment
