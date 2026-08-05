"""POST /api/v1/auth/login, /auth/refresh, /auth/logout, /auth/forgot-password, /auth/reset-password."""

import pytest_asyncio
from httpx import AsyncClient

from tests.support.roles import UserRole

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
FORGOT_PASSWORD_URL = "/api/v1/auth/forgot-password"
RESET_PASSWORD_URL = "/api/v1/auth/reset-password"


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


class FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})


@pytest_asyncio.fixture
async def fake_email_sender(client: AsyncClient):
    from app.core.deps import get_email_sender
    from app.main import app

    fake = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake


async def test_forgot_password_known_email_returns_204_and_sends_email(
    client: AsyncClient, make_user, fake_email_sender
):
    await make_user(email="forgot-route@example.com", password="correct-password", role=UserRole.SALES_REP)

    response = await client.post(FORGOT_PASSWORD_URL, json={"email": "forgot-route@example.com"})

    assert response.status_code == 204
    assert len(fake_email_sender.calls) == 1
    assert fake_email_sender.calls[0]["to"] == "forgot-route@example.com"


async def test_forgot_password_unknown_email_returns_204_and_sends_nothing(
    client: AsyncClient, fake_email_sender
):
    response = await client.post(FORGOT_PASSWORD_URL, json={"email": "nobody-here@example.com"})

    assert response.status_code == 204
    assert fake_email_sender.calls == []


async def test_reset_password_with_valid_token_returns_204_and_allows_login_with_new_password(
    client: AsyncClient, make_user, fake_email_sender
):
    await make_user(email="reset-route@example.com", password="old-password", role=UserRole.SALES_REP)
    await client.post(FORGOT_PASSWORD_URL, json={"email": "reset-route@example.com"})
    reset_token = fake_email_sender.calls[0]["body"].split("?token=")[1].split("\n")[0]

    response = await client.post(
        RESET_PASSWORD_URL, json={"token": reset_token, "new_password": "new-password"}
    )

    assert response.status_code == 204
    login_response = await client.post(
        LOGIN_URL, json={"email": "reset-route@example.com", "password": "new-password"}
    )
    assert login_response.status_code == 200


async def test_reset_password_with_unknown_token_returns_400(client: AsyncClient):
    response = await client.post(
        RESET_PASSWORD_URL, json={"token": "not-a-real-token", "new_password": "whatever"}
    )

    assert response.status_code == 400
