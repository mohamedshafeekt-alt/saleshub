"""app.core.rbac_seed.seed_on_startup: the thin session-owning wrapper that
app.main's lifespan calls on every process start, so a permission code added
in code lands in the database without a manual scripts/seed_admin.py re-run.
seed_permissions_and_roles itself is already exercised indirectly by every
other test via the `engine` fixture -- this only covers the wrapper's own
session/commit wiring."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac_seed import seed_on_startup, seed_permissions_and_roles
from app.models.permission import Permission
from app.models.role import Role


@asynccontextmanager
async def _passthrough(session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    yield session


async def test_seed_on_startup_commits_permissions_via_its_own_session(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.session.async_session_factory", lambda: _passthrough(db_session))

    await seed_on_startup()

    result = await db_session.execute(select(Permission.code).where(Permission.code == "deals.notify_on_create"))
    assert result.scalar_one() == "deals.notify_on_create"


async def test_seed_backfills_users_view_onto_an_existing_role_missing_it(db_session: AsyncSession) -> None:
    """A role built (via role_service, or directly like here) before
    deals.access -> users.view existed in PERMISSION_DEPENDENCIES must not
    stay stuck missing it forever -- seed_permissions_and_roles (called on
    every app startup) backfills it onto every existing role, not just ones
    a caller happens to resave through /roles."""
    result = await db_session.execute(select(Permission).where(Permission.code == "deals.access"))
    deals_access = result.scalar_one()
    role = Role(name="Pre-Dependency Deals Role", permissions=[deals_access])
    db_session.add(role)
    await db_session.flush()

    await seed_permissions_and_roles(db_session)

    codes = {p.code for p in role.permissions}
    assert "users.view" in codes
