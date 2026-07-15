"""POST /api/v1/auth/login."""

from httpx import AsyncClient

from app.models.user import UserRole

LOGIN_URL = "/api/v1/auth/login"


async def test_login_correct_credentials_returns_token(client: AsyncClient, make_user):
    await make_user(email="login-ok@example.com", password="correct-password", role=UserRole.SALES_REP)

    response = await client.post(
        LOGIN_URL, json={"email": "login-ok@example.com", "password": "correct-password"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


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
