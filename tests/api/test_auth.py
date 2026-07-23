"""POST /api/v1/auth/login, /auth/refresh, /auth/logout."""

from httpx import AsyncClient

from tests.support.roles import UserRole

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"


async def test_login_correct_credentials_returns_token(client: AsyncClient, make_user):
    await make_user(email="login-ok@example.com", password="correct-password", role=UserRole.SALES_REP)

    response = await client.post(
        LOGIN_URL, json={"email": "login-ok@example.com", "password": "correct-password"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_login_returns_role_permission_codes(client: AsyncClient, make_user):
    await make_user(email="perms@example.com", password="correct-password", role=UserRole.ADMIN)

    response = await client.post(
        LOGIN_URL, json={"email": "perms@example.com", "password": "correct-password"}
    )

    assert response.status_code == 200
    permissions = response.json()["permissions"]
    assert isinstance(permissions, list)
    assert len(permissions) > 0


async def test_login_wrong_password_returns_401(client: AsyncClient, make_user):
    await make_user(email="wrongpw@example.com", password="correct-password", role=UserRole.SALES_REP)

    response = await client.post(
        LOGIN_URL, json={"email": "wrongpw@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401


async def test_login_unknown_email_returns_401_with_same_detail_as_wrong_password(
    client: AsyncClient, make_user
):
    await make_user(email="known@example.com", password="correct-password", role=UserRole.SALES_REP)

    wrong_password_response = await client.post(
        LOGIN_URL, json={"email": "known@example.com", "password": "wrong-password"}
    )
    unknown_email_response = await client.post(
        LOGIN_URL, json={"email": "nobody-here@example.com", "password": "whatever"}
    )

    assert unknown_email_response.status_code == 401
    # no user enumeration: same status AND same detail message for both failure modes
    assert unknown_email_response.json()["detail"] == wrong_password_response.json()["detail"]


async def test_login_inactive_user_returns_401(client: AsyncClient, make_user):
    await make_user(
        email="inactive@example.com",
        password="correct-password",
        role=UserRole.SALES_REP,
        is_active=False,
    )

    response = await client.post(
        LOGIN_URL, json={"email": "inactive@example.com", "password": "correct-password"}
    )

    assert response.status_code == 401


async def test_login_missing_password_field_returns_422(client: AsyncClient):
    response = await client.post(LOGIN_URL, json={"email": "someone@example.com"})

    assert response.status_code == 422


async def test_login_malformed_email_returns_422(client: AsyncClient):
    response = await client.post(
        LOGIN_URL, json={"email": "not-an-email", "password": "whatever"}
    )

    assert response.status_code == 422


async def test_refresh_with_valid_token_returns_new_access_token(client: AsyncClient, make_user):
    await make_user(email="refresh-route@example.com", password="correct-password", role=UserRole.SALES_REP)
    login_response = await client.post(
        LOGIN_URL, json={"email": "refresh-route@example.com", "password": "correct-password"}
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_refresh_with_unknown_token_returns_401(client: AsyncClient):
    response = await client.post(REFRESH_URL, json={"refresh_token": "not-a-real-token"})

    assert response.status_code == 401


async def test_logout_revokes_refresh_token_so_it_cannot_be_reused(client: AsyncClient, make_user):
    await make_user(email="logout-route@example.com", password="correct-password", role=UserRole.SALES_REP)
    login_response = await client.post(
        LOGIN_URL, json={"email": "logout-route@example.com", "password": "correct-password"}
    )
    body = login_response.json()
    access_token, refresh_token = body["access_token"], body["refresh_token"]

    logout_response = await client.post(
        LOGOUT_URL,
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 204

    refresh_response = await client.post(REFRESH_URL, json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 401


async def test_logout_without_auth_header_returns_401(client: AsyncClient):
    response = await client.post(LOGOUT_URL, json={"refresh_token": "whatever"})

    assert response.status_code == 401
