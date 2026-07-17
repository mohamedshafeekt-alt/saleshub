"""FastAPI app entrypoint: router registration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import accounts, auth, contacts, deals, leads, users
from app.core.error_handler import register_error_handlers
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Sales CRM Platform")

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

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(contacts.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")