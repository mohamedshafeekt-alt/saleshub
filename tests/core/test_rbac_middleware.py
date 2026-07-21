"""app.core.rbac_middleware: central RBAC enforcement, exercised via
throwaway routes mounted only for this test module (not part of the real
app), covering all three tiers: @public, no decorator, @requires_permission."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import public, requires_permission


@pytest_asyncio.fixture
async def rbac_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.db.session import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    routes_before = list(app.router.routes)

    @app.get("/__test__/public")
    @public
    async def _public_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/__test__/authenticated-only")
    async def _authenticated_only_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/__test__/permission-gated")
    @requires_permission("users.manage")
    async def _permission_gated_route() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.router.routes = routes_before
    app.dependency_overrides.clear()


async def test_public_route_needs_no_auth(rbac_client: AsyncClient):
    response = await rbac_client.get("/__test__/public")

    assert response.status_code == 200


async def test_authenticated_only_route_rejects_missing_token(rbac_client: AsyncClient):
    response = await rbac_client.get("/__test__/authenticated-only")

    assert response.status_code == 401


async def test_authenticated_only_route_allows_any_valid_user(
    rbac_client: AsyncClient, make_user, auth_headers
):
    from tests.support.roles import UserRole

    rep = await make_user(email="rep-mw-authonly@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await rbac_client.get("/__test__/authenticated-only", headers=headers)

    assert response.status_code == 200


async def test_permission_gated_route_rejects_missing_token(rbac_client: AsyncClient):
    response = await rbac_client.get("/__test__/permission-gated")

    assert response.status_code == 401


async def test_permission_gated_route_rejects_garbage_token(rbac_client: AsyncClient):
    response = await rbac_client.get(
        "/__test__/permission-gated", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


async def test_permission_gated_route_rejects_role_without_permission(
    rbac_client: AsyncClient, make_user, auth_headers
):
    from tests.support.roles import UserRole

    rep = await make_user(email="rep-mw-forbidden@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await rbac_client.get("/__test__/permission-gated", headers=headers)

    assert response.status_code == 403


async def test_permission_gated_route_allows_role_with_permission(
    rbac_client: AsyncClient, make_user, auth_headers
):
    from tests.support.roles import UserRole

    admin = await make_user(email="admin-mw-allowed@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await rbac_client.get("/__test__/permission-gated", headers=headers)

    assert response.status_code == 200


async def test_permission_gated_route_rejects_inactive_user(
    rbac_client: AsyncClient, make_user, auth_headers
):
    from tests.support.roles import UserRole

    inactive_admin = await make_user(
        email="inactive-admin-mw@example.com", role=UserRole.ADMIN, is_active=False
    )
    headers = auth_headers(inactive_admin)

    response = await rbac_client.get("/__test__/permission-gated", headers=headers)

    assert response.status_code == 401
