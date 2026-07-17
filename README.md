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
- [x] Lead CRUD + filter/search (owner, source, status, company/owner-name search) — single `POST /api/v1/leads` upsert route (no `id` in the body creates, `id` present partially updates — replaces the old separate create/PATCH routes), plus `GET/DELETE /api/v1/leads`; Sales Rep/Delivery SME/Manager/Admin all have full access; Sales Rep and Delivery SME are scoped to leads they own plus unassigned leads (`owner_id IS NULL`, a shared claimable queue) — Manager/Admin see everything
- [x] Lead duplicate-email detection (409, same pattern as User)
- [x] Lead `tier` removed entirely (kickoff-email scope call — Account keeps `tier`, only Lead's was dropped); `owner_id` is optional at creation (a lead can be unassigned); Lead has a `status` field (`not_contacted` default, `attempted_to_contact`/`contacted`/`contact_in_future`/`junk_lead`/`lost_lead`), settable on create/update and filterable via `GET /api/v1/leads?status=`
- [x] `id` moved onto the shared `Base` alongside `created_at`/`updated_at` — every model gets it for free, no more per-table `id` boilerplate
- [x] Admin gets an email the moment any lead is created (`send_new_lead_notification_email`, same best-effort/non-blocking pattern as the new-user-credentials email — a failed send never fails the request)
- [x] `lead_contacts` table — a Lead can have more than one contact; creating a Lead auto-inserts its own email/phone as the primary `lead_contacts` row, plus any extra contacts passed in the `contacts` array (Lead's own `email`/`phone` columns are unchanged, still the primary/duplicate-checked contact)
- [x] `lead_activities` table + `POST /api/v1/leads/{id}/activities` — logs a Note/Meeting/Call/Comment against a lead (403/404 gated the same way as the rest of the Lead API); a Postgres trigger (`clock_timestamp()`, not `now()`, so it fires correctly even inside one transaction) bumps the parent lead's `updated_at` on every insert into `lead_activities`, including ones written directly with raw SQL
- [x] `GET /api/v1/leads/{id}` now returns the full single-lead detail: `owner_name`, every `lead_contacts` row, the full activity log (each with `created_by_name`/`created_at`) and an `activity_count`; `GET /api/v1/leads` (list) gained `owner_name` and `updated_at` per row
- [x] `GET /api/v1/users` opened up to Delivery SME as well (Sales Rep/Manager/Admin already could) — SME has full Lead access and needs the same Owner-dropdown data
- [x] Account CRUD + filter/search (owner, tier, company/owner-name search) — `POST/GET/PATCH/DELETE /api/v1/accounts`, same RBAC/ownership-scoping as Leads; gained `linkedin_url`; `POST /api/v1/leads/{id}/convert` turns a Lead into an Account (409 on double-conversion, 400 if no tier/owner-id was resolved — tier must now always come from the convert request, Lead no longer carries one), Lead gains `is_converted`
- [x] Contact CRUD — `POST/GET/PATCH/DELETE /api/v1/contacts`, `GET /api/v1/accounts/{id}/contacts` (now paginated); no `owner_id` of its own, access gated entirely through the parent Account's owner (Sales Rep/Manager/Admin, Delivery SME 403)
- [x] Deal CRUD + stage transitions + stage history — `POST/GET/PATCH/DELETE /api/v1/deals`, `GET /api/v1/deals/{id}/stage-history`, `GET /api/v1/accounts/{id}/deals`; Deal has its own `owner_id` independent of the account's owner, any stage can move to any other stage (no transition graph), every stage change (including creation) writes a `deal_stage_history` row
- [x] Deal "mark cold with reason" — `cold_reason` on Deal, required (400) whenever the resulting stage is `cold_deals` with no reason on record, whether set on create or via PATCH
- [x] Paginated list responses — `GET /api/v1/leads`, `/api/v1/accounts`, `/api/v1/deals`, and `/api/v1/accounts/{id}/contacts` now return `{items, total, limit, offset}` instead of a bare array, so the frontend can render "1-25 of N" without a second request
<<<<<<< Updated upstream
- [x] CORS middleware (`app/main.py`) — wildcard origins for now (safe: auth is a Bearer token, not a cookie, so no `allow_credentials` needed); without this, browsers/Flutter-web got a 404/405 on the `OPTIONS` preflight before ever reaching a route
- [x] Refresh tokens + logout — `POST /api/v1/auth/login` now also returns a `refresh_token` (opaque, DB-backed via new `refresh_tokens` table, 30-day expiry by default); `POST /api/v1/auth/refresh` exchanges it for a new access token (no rotation — same refresh token reused until logout/expiry); `POST /api/v1/auth/logout` (authenticated) revokes the caller's own refresh token, idempotently
=======
- [x] "Save & Convert to Account" on the New Lead form — `POST /api/v1/leads/convert` creates an Account (and its Contacts) directly from the form, without ever creating a Lead row; company/domain/tier/owner_id required, sibling to the existing `POST /api/v1/leads/{id}/convert` (which converts an already-saved Lead); contacts arrive as a list, only the first needs a name — later ones just add another email/phone and inherit it
>>>>>>> Stashed changes
- [ ] Static Pre-Sales Checklist per deal
- [ ] Activity log for Account/Deal (Lead's is done; a generic cross-entity log is still open)
- [ ] Notifications (task overdue, stage transition)
- [ ] Dashboard aggregation endpoints (funnel, target vs actual)

## Milestones (per Phase 1 kickoff)
- **Week 1** — Login, RBAC, Lead Management, Navigation
- **Week 2** — Accounts, Contacts, Deals, Activities, Notifications
- **Week 3** — Dashboard, QA/UAT, optimization, deployment
