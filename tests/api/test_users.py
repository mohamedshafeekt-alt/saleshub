"""POST /api/v1/users (admin-only user creation).

Target contract: UserCreate has no `password` field — admin supplies
first_name/last_name, the server generates a random password and emails it
via EmailSender (injected through get_email_sender, overridden here with a
fake so no test touches real SMTP).
"""

import pytest_asyncio
from httpx import AsyncClient

from app.models.user import UserRole

USERS_URL = "/api/v1/users"


class FakeEmailSender:
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise
        self.calls: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.should_raise:
            raise RuntimeError("SMTP is down")
        self.calls.append({"to": to, "subject": subject, "body": body})


@pytest_asyncio.fixture
async def fake_email_sender(client: AsyncClient):
    """Overrides get_email_sender with a fake that records (rather than sends) emails."""
    from app.core.deps import get_email_sender
    from app.main import app

    fake = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake


@pytest_asyncio.fixture
async def failing_email_sender(client: AsyncClient):
    """Overrides get_email_sender with a fake whose send() always raises."""
    from app.core.deps import get_email_sender
    from app.main import app

    fake = FakeEmailSender(should_raise=True)
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake


async def test_create_user_as_admin_returns_201_with_user_read_shape(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-creator@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "brand-new@example.com", "first_name": "Some Name", "role": "sales_rep"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "brand-new@example.com"
    assert body["first_name"] == "Some Name"
    assert body["role"] == "sales_rep"
    assert body["is_active"] is True
    assert "id" in body

    body_text = response.text
    assert "hashed_password" not in body_text
    assert "password" not in body_text.lower()

    assert len(fake_email_sender.calls) == 1
    assert fake_email_sender.calls[0]["to"] == "brand-new@example.com"


async def test_create_user_as_sales_rep_returns_403(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    rep = await make_user(email="rep-cant-create@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        USERS_URL,
        json={"email": "should-not-be-created@example.com", "first_name": "Some Name", "role": "sales_rep"},
        headers=headers,
    )

    assert response.status_code == 403


async def test_create_user_duplicate_email_as_admin_returns_409(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-dup-check@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    await make_user(email="already-exists@example.com", role=UserRole.SALES_REP)

    response = await client.post(
        USERS_URL,
        json={"email": "already-exists@example.com", "first_name": "Some Name", "role": "sales_rep"},
        headers=headers,
    )

    assert response.status_code == 409


async def test_create_user_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-validation@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL, json={"email": "no-first-name@example.com", "role": "sales_rep"}, headers=headers
    )

    assert response.status_code == 422


async def test_create_user_bad_role_enum_value_returns_422(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-bad-enum@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "bad-role@example.com", "first_name": "Some Name", "role": "not_a_real_role"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_user_no_auth_header_returns_401(client: AsyncClient, fake_email_sender):
    response = await client.post(
        USERS_URL,
        json={"email": "no-auth@example.com", "first_name": "Some Name", "role": "sales_rep"},
    )

    assert response.status_code == 401


async def test_create_user_when_email_send_fails_still_returns_201(
    client: AsyncClient, make_user, auth_headers, failing_email_sender
):
    admin = await make_user(email="admin-email-fails@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "survives-email-failure@example.com", "first_name": "Some Name", "role": "sales_rep"},
        headers=headers,
    )

    assert response.status_code == 201
