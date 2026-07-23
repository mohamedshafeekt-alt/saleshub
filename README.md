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
- [x] Contact CRUD — `POST/GET/PATCH/DELETE /api/v1/contacts`, `GET /api/v1/accounts/{id}/contacts` (now paginated); no `owner_id` of its own, access gated entirely through the parent Account's owner (Sales Rep/Manager/Admin, Delivery SME 403). Superseded by the `contact_accounts` refactor below — see that entry.
- [x] Deal CRUD + stage transitions + stage history — `POST/GET/PATCH/DELETE /api/v1/deals`, `GET /api/v1/deals/{id}/stage-history`, `GET /api/v1/accounts/{id}/deals`; Deal has its own `owner_id` independent of the account's owner, any stage can move to any other stage (no transition graph), every stage change (including creation) writes a `deal_stage_history` row
- [x] Deal "mark cold with reason" — `cold_reason` on Deal, required (400) whenever the resulting stage is `cold_deals` with no reason on record, whether set on create or via PATCH
- [x] Paginated list responses — `GET /api/v1/leads`, `/api/v1/accounts`, `/api/v1/deals`, and `/api/v1/accounts/{id}/contacts` now return `{items, total, limit, offset}` instead of a bare array, so the frontend can render "1-25 of N" without a second request
- [x] CORS middleware (`app/main.py`) — wildcard origins for now (safe: auth is a Bearer token, not a cookie, so no `allow_credentials` needed); without this, browsers/Flutter-web got a 404/405 on the `OPTIONS` preflight before ever reaching a route
- [x] Refresh tokens + logout — `POST /api/v1/auth/login` now also returns a `refresh_token` (opaque, DB-backed via new `refresh_tokens` table, 30-day expiry by default); `POST /api/v1/auth/refresh` exchanges it for a new access token (no rotation — same refresh token reused until logout/expiry); `POST /api/v1/auth/logout` (authenticated) revokes the caller's own refresh token, idempotently
- [x] Lead import from `.xlsx`/`.csv` — `GET /api/v1/leads/import/template`, `POST /api/v1/leads/import`
- [x] `POST /api/v1/accounts` ("Save & Convert to Account" on the New Lead form) now requires `domain` alongside `company`/`tier`/`owner_id`, and accepts a `contacts` list saved straight to the `contacts` table (`account_id` FK); only the first contact needs a name — later ones just add another email/phone and inherit it
- [x] Every Account response (`POST`/`GET`/`GET` list) now carries `owner_name`, `contact_count`, and `deal_count` to match the Accounts List screen's table columns; `GET /api/v1/accounts` gained an `industry` filter and its `search` now also matches `domain` (not just company/owner name)
- [x] `PATCH /api/v1/accounts/{id}` accepts the same `contacts` list as `POST` (appends, same first-contact-needs-a-name rule) — lets the Edit Account form add contacts in the same call
- [x] `GET /api/v1/accounts/{id}/overview` — the Account Overview screen in one call: account fields, `open_deal_value` (sum of non-closed/non-cold deal values), `key_contacts`, `active_deals`. `last_activity`/`next_step`/`total_arr` are always `null` — no backing model yet (no generic Account activity log, no ARR field); Pre-Sales Checklist deliberately left out of this endpoint for the same reason
- [x] Contact is now many-to-many with Account via a new `contact_accounts` join table (`contact_id`, `account_id`, `is_primary`, unique per pair, partial-unique index enforcing at most one primary contact per account — violating it raises `409`, never silently demotes the old primary). `POST /api/v1/accounts/{id}/contacts` is a single create-or-update route (same dispatch pattern as `POST /leads`): absent `contact_id` creates a Contact + its link (201), present `contact_id` updates that contact's fields and/or `is_primary` (200), creating the link if the contact wasn't already associated with that account (how an existing contact gets added to another account); `GET /api/v1/accounts/{id}/contacts` now includes `is_primary` per contact. Contact gained `linkedin_url`/`alternate_phone`. Standalone `POST/GET/PATCH/DELETE /api/v1/contacts` are now role-gated only, no per-account ownership check — there's no single owning account to check anymore.
- [x] Fixed `DELETE /api/v1/leads/{id}` 400 when a lead had activities/contacts — `Lead.contacts`/`Lead.activities` relationships now use `passive_deletes=True` so the ORM defers to the FK's existing `ON DELETE CASCADE` instead of trying to null the (`NOT NULL`) `lead_id` column itself
- [x] Profile self-service — `GET/PATCH /api/v1/users/me` (name/phone, email not editable here), `POST /api/v1/users/me/password` (current-password verified), `POST /api/v1/users/me/avatar` (image/png or image/jpeg, saved to local disk under `media/avatars/`, served via `/media` static mount); `User` gained `phone_number`/`avatar_url`/`last_login_at`, the last one stamped on every successful login
- [x] Swagger's Authorize button/padlocks now work — `app/core/deps.py` adds an `HTTPBearer` scheme so FastAPI's OpenAPI generator registers a security scheme, wired globally alongside `enforce_rbac` in `app/main.py`; real auth is still done entirely by `rbac_middleware`, this only makes the token show up in `/docs`
- [x] `POST /api/v1/users` reactivates a soft-deleted user instead of failing "Email already exists" — same email on a previously deleted row now overwrites name/role and reissues a generated password on that same user id (preserves history); a still-active duplicate email still 409s as before
- [x] Notifications: in-app bell/panel backed by `GET/PATCH/POST/DELETE /api/v1/notifications` (list with `unread_only`/`type` filters, `unread-count`, mark-one-read, mark-all/bulk-read, bulk soft-delete) — populated on new-lead creation (same `LEADS_NOTIFY_ON_CREATE`-permission recipients as the existing admin email), lead reassignment, and deal stage changes, plus a `task_overdue` entry computed at read time from `Lead.next_follow_up_date` (no new Task entity, no scheduler); polling-based, no real-time push, no email mirroring
- [x] Global search — `GET /api/v1/search?q=` (auth-only, no specific permission gate) matches by name across Leads (first/last name), Accounts (company), Deals (deal name), and Contacts (first/last name); each result is `{id, label, name}` (`label` is the entity type), capped at 5 per type
- [x] Deal pipeline stages are now dynamic, admin-configurable rows (`deal_stages`, full CRUD via `POST/GET/PATCH/DELETE /api/v1/deal-stages`) instead of a fixed enum — `Deal.stage_id`/`DealStageHistory.from_stage_id`/`to_stage_id` replace the old `deal_stage` enum columns; `is_cold` on the stage (not a hardcoded stage-name check) now drives the cold-reason-required rule; a minimal `companies` table backs per-company stage grouping (single "Default" company seeded, no other table gets a `company_id`); `Deal` gained optional `tier` and a many-to-many `contact_ids` (via the `deal_contacts` join table, replacing the earlier single nullable `contact_id`) so a deal can have multiple stakeholder contacts; `GET /api/v1/deals` gained `view=list|board` (board groups the same filtered results by stage with per-column totals, unpaginated), `sort_by`/`sort_dir`, and account-company-name search; `GET /api/v1/deals/export` streams an xlsx of all role-scoped deals; `PATCH /api/v1/deals/generic-patch` is a small allowlisted single-field/record patch (`deals`/`deal_stage_history`/`deal_stages`)
- [x] Deal Activities — `deal_activities` table + `POST/GET/PATCH/DELETE /api/v1/deals/{id}/activities` (Note/Meeting/Call/Comment/Follow-up), mirroring Lead Activities exactly: `types`/`date_from`/`date_to` filters on list, only the deal owner may edit, delete gated by the new `deals.delete_any_activity` permission (Admin only by default, same pattern as `leads.delete_any_activity`)
- [x] Deal Documents — `deal_documents` table + `POST/GET/DELETE /api/v1/deals/{id}/documents` for uploading proposals/NDAs/contracts per deal (`application/pdf`, `.doc`, `.docx`, `image/png`, `image/jpeg`), saved to local disk under `media/deal_documents/` with a per-upload unique filename; upload/list/delete are gated the same way as the Deal record itself (ownership or `deals.view_all`, no extra owner-only rule); backed by a new shared class-based `FileUploadService` (`app/services/file_upload_service.py`) which `save_avatar` was refactored to use as well, so avatar and deal-document uploads share one code path
- [x] `GET /api/v1/leads/export` streams an xlsx of all role-scoped leads (Name, Email, Phone, Company, Source, Status, Owner), scoped/filterable the same way as `GET /api/v1/leads` (owner-or-unassigned unless `leads.view_all`; `source`/`status`/`search`, no pagination) — xlsx building for both Deal and Lead export now goes through a shared `rows_to_xlsx()` helper in the new `app/services/export_service.py` (openpyxl, no new dependency), which the Deal export route was refactored to use as well (same output, no behavior change)
- [ ] Static Pre-Sales Checklist per deal
- [ ] Activity log for Account (Lead's and Deal's are done; Account's is still open)
- [ ] Dashboard aggregation endpoints (funnel, target vs actual)

## Milestones (per Phase 1 kickoff)
- **Week 1** — Login, RBAC, Lead Management, Navigation
- **Week 2** — Accounts, Contacts, Deals, Activities, Notifications
- **Week 3** — Dashboard, QA/UAT, optimization, deployment
m