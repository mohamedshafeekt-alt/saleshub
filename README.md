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
- [x] Lead CRUD + filter/search (owner, source, tier, company/owner-name search) — `POST/GET/PATCH/DELETE /api/v1/leads`, Sales Rep/Manager/Admin only (Delivery SME 403), Sales Reps scoped to their own leads
- [x] Lead duplicate-email detection (409, same pattern as User)
- [ ] Account CRUD
- [ ] Contact CRUD
- [ ] Deal CRUD + stage transitions + stage history
- [ ] Deal "mark cold with reason"
- [ ] Static Pre-Sales Checklist per deal
- [ ] Activity log (generic, per lead/account/deal)
- [ ] Notifications (task overdue, stage transition)
- [ ] Dashboard aggregation endpoints (funnel, target vs actual)

## Milestones (per Phase 1 kickoff)
- **Week 1** — Login, RBAC, Lead Management, Navigation
- **Week 2** — Accounts, Contacts, Deals, Activities, Notifications
- **Week 3** — Dashboard, QA/UAT, optimization, deployment
