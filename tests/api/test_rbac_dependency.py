"""app.core.deps: require_role(...) RBAC dependency, exercised via a throwaway
route mounted only for this test module (not part of the real app)."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def rbac_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.core.deps import require_role
    from app.db.session import get_db
    from app.main import app
    from app.models.user import UserRole

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    routes_before = list(app.router.routes)

    @app.get("/__test__/admin-only", dependencies=[Depends(require_role(UserRole.ADMIN))])
    async def _admin_only() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.router.routes = routes_before
    app.dependency_overrides.clear()


async def test_require_role_admin_token_allows_access(rbac_client: AsyncClient, make_user, auth_headers):
    from app.models.user import UserRole

    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await rbac_client.get("/__test__/admin-only", headers=headers)

    assert response.status_code == 200


async def test_require_role_wrong_role_gets_403(rbac_client: AsyncClient, make_user, auth_headers):
    from app.models.user import UserRole

    rep = await make_user(email="rep@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await rbac_client.get("/__test__/admin-only", headers=headers)

    assert response.status_code == 403


async def test_require_role_missing_auth_header_gets_401(rbac_client: AsyncClient):
    response = await rbac_client.get("/__test__/admin-only")

    assert response.status_code == 401


async def test_require_role_garbage_token_gets_401(rbac_client: AsyncClient):
    response = await rbac_client.get(
        "/__test__/admin-only", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401
