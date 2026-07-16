"""FastAPI app entrypoint: router registration."""

from fastapi import FastAPI

from app.api.v1 import accounts, auth, contacts, deals, leads, users
from app.core.error_handler import register_error_handlers
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Sales CRM Platform")

register_error_handlers(app)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(contacts.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")