"""FastAPI app entrypoint: router registration."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    accounts,
    audit_log,
    auth,
    contacts,
    dashboard,
    deal_stages,
    deals,
    documents,
    leads,
    notifications,
    permissions,
    roles,
    search,
    users,
)
from app.core.error_handler import register_error_handlers
from app.core.logging import configure_logging
from app.core.deps import bearer_scheme
from app.core.rbac import public
from app.core.rbac_middleware import enforce_rbac
from app.core.rbac_seed import seed_on_startup

configure_logging()

Path("media/avatars").mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Idempotent -- keeps the permission catalog/starter roles in sync with
    # app.core.rbac_seed._PERMISSIONS on every process start, so a newly
    # added permission code doesn't need scripts/seed_admin.py re-run by hand.
    await seed_on_startup()
    yield


app = FastAPI(
    title="Sales CRM Platform",
    lifespan=lifespan,
    dependencies=[Depends(bearer_scheme), Depends(enforce_rbac)],
)

# Wildcard is safe here (no allow_credentials): auth is a Bearer token in
# the Authorization header, not a cookie, so there's nothing ambient for a
# malicious origin to ride along.
# ponytail: wildcard origins, scope to a real allowlist before prod launch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.mount("/media", StaticFiles(directory="media"), name="media")


@app.get("/health")
@public
async def health() -> dict[str, str]:
    return {"status": "ok"}

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(contacts.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")
app.include_router(deal_stages.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(permissions.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(audit_log.router, prefix="/api/v1")