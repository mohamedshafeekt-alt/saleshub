"""POST/GET/PATCH/DELETE /api/v1/roles."""

from httpx import AsyncClient

from tests.support.roles import UserRole

ROLES_URL = "/api/v1/roles"


async def _get_permission_id(client: AsyncClient, headers: dict, code: str) -> int:
    response = await client.get("/api/v1/permissions", headers=headers)
    return next(p["id"] for p in response.json() if p["code"] == code)


async def test_create_role_as_admin_returns_201(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-create@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    permission_id = await _get_permission_id(client, headers, "leads.access")

    response = await client.post(
        ROLES_URL,
        json={"name": "Custom Role", "description": "d", "permission_ids": [permission_id]},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Custom Role"
    # leads.access now pulls in users.view too (Owner dropdowns on the Lead
    # form need GET /users) -- set, not an ordered/indexed check.
    assert {p["code"] for p in body["permissions"]} == {"leads.access", "users.view"}


async def test_create_role_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-role-create@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(ROLES_URL, json={"name": "Nope"}, headers=headers)

    assert response.status_code == 403


async def test_create_role_duplicate_name_returns_409(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-dup@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    await client.post(ROLES_URL, json={"name": "Dupe Role"}, headers=headers)

    response = await client.post(ROLES_URL, json={"name": "Dupe Role"}, headers=headers)

    assert response.status_code == 409


async def test_list_roles_as_admin_returns_200(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-list@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.get(ROLES_URL, headers=headers)

    assert response.status_code == 200
    names = {r["name"] for r in response.json()}
    assert "Admin" in names


async def test_update_role_as_admin_returns_200(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-update@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    created = await client.post(ROLES_URL, json={"name": "Before"}, headers=headers)
    role_id = created.json()["id"]

    response = await client.patch(
        f"{ROLES_URL}/{role_id}", json={"name": "After", "permission_ids": []}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "After"


async def test_update_role_unknown_id_returns_404(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-update-404@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.patch(f"{ROLES_URL}/999999", json={"name": "X"}, headers=headers)

    assert response.status_code == 404


async def test_delete_role_as_admin_returns_204_and_excludes_from_list(
    client: AsyncClient, make_user, auth_headers
):
    admin = await make_user(email="admin-role-delete@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    created = await client.post(ROLES_URL, json={"name": "To Delete"}, headers=headers)
    role_id = created.json()["id"]

    response = await client.delete(f"{ROLES_URL}/{role_id}", headers=headers)
    assert response.status_code == 204

    list_response = await client.get(ROLES_URL, headers=headers)
    names = {r["name"] for r in list_response.json()}
    assert "To Delete" not in names


async def test_roles_endpoints_no_auth_header_returns_401(client: AsyncClient):
    response = await client.get(ROLES_URL)

    assert response.status_code == 401
