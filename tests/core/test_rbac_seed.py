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

from app.core.rbac_seed import seed_on_startup
from app.models.permission import Permission


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
