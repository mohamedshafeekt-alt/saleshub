"""GET /api/v1/permissions."""

from httpx import AsyncClient

from tests.support.roles import UserRole

PERMISSIONS_URL = "/api/v1/permissions"


async def test_list_permissions_as_admin_returns_200(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-permissions-list@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.get(PERMISSIONS_URL, headers=headers)

    assert response.status_code == 200
    codes = {p["code"] for p in response.json()}
    assert "leads.access" in codes
    assert "users.manage" in codes


async def test_list_permissions_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-permissions-list@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(PERMISSIONS_URL, headers=headers)

    assert response.status_code == 403


async def test_list_permissions_no_auth_header_returns_401(client: AsyncClient):
    response = await client.get(PERMISSIONS_URL)

    assert response.status_code == 401
