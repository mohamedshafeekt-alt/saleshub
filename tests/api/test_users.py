"""POST /api/v1/users (admin-only user creation).

Target contract: UserCreate has no `password` field — admin supplies
first_name/last_name, the server generates a random password and emails it
via EmailSender (injected through get_email_sender, overridden here with a
fake so no test touches real SMTP).
"""

import pytest_asyncio
from httpx import AsyncClient

from tests.support.roles import UserRole

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
    rep = await make_user(email="rep-role-source@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "brand-new@example.com", "first_name": "Some Name", "role_id": rep.role_id},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "brand-new@example.com"
    assert body["first_name"] == "Some Name"
    assert body["role"]["name"] == "Sales Rep"
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
        json={
            "email": "should-not-be-created@example.com",
            "first_name": "Some Name",
            "role_id": rep.role_id,
        },
        headers=headers,
    )

    assert response.status_code == 403


async def test_create_user_duplicate_email_as_admin_returns_409(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-dup-check@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)
    existing = await make_user(email="already-exists@example.com", role=UserRole.SALES_REP)

    response = await client.post(
        USERS_URL,
        json={"email": "already-exists@example.com", "first_name": "Some Name", "role_id": existing.role_id},
        headers=headers,
    )

    assert response.status_code == 409


async def test_create_user_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-validation@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL, json={"email": "no-first-name@example.com", "role_id": admin.role_id}, headers=headers
    )

    assert response.status_code == 422


async def test_create_user_unknown_role_id_returns_404(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-bad-role-id@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "bad-role@example.com", "first_name": "Some Name", "role_id": 999999},
        headers=headers,
    )

    assert response.status_code == 404


async def test_create_user_missing_role_id_returns_422(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-missing-role-id@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={"email": "no-role-given@example.com", "first_name": "Some Name"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_user_no_auth_header_returns_401(client: AsyncClient, fake_email_sender):
    response = await client.post(
        USERS_URL,
        json={"email": "no-auth@example.com", "first_name": "Some Name", "role_id": 1},
    )

    assert response.status_code == 401


async def test_create_user_when_email_send_fails_still_returns_201(
    client: AsyncClient, make_user, auth_headers, failing_email_sender
):
    admin = await make_user(email="admin-email-fails@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(
        USERS_URL,
        json={
            "email": "survives-email-failure@example.com",
            "first_name": "Some Name",
            "role_id": admin.role_id,
        },
        headers=headers,
    )

    assert response.status_code == 201


async def test_list_users_as_sales_rep_returns_200_with_all_users(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-lister@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="other-rep@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert {rep.email, other_rep.email} <= emails


async def test_list_users_includes_inactive_users(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-sees-inactive@example.com", role=UserRole.SALES_REP)
    inactive = await make_user(
        email="inactive-user@example.com", role=UserRole.SALES_REP, is_active=False
    )
    headers = auth_headers(rep)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200
    by_email = {u["email"]: u for u in response.json()}
    assert by_email[inactive.email]["is_active"] is False


async def test_list_users_rejects_date_to_before_date_from(client: AsyncClient, make_user, auth_headers):
    manager = await make_user(email="manager-bad-date-range-users@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)

    response = await client.get(
        USERS_URL, params={"date_from": "2026-09-11", "date_to": "2026-08-11"}, headers=headers
    )

    assert response.status_code == 422


async def test_list_users_as_sales_manager_returns_200(client: AsyncClient, make_user, auth_headers):
    manager = await make_user(email="manager-lister@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200


async def test_list_users_as_admin_returns_200(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-lister@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200


async def test_list_users_as_delivery_sme_returns_200(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-allowed-list@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.get(USERS_URL, headers=headers)

    assert response.status_code == 200


async def test_list_users_no_auth_header_returns_401(client: AsyncClient):
    response = await client.get(USERS_URL)

    assert response.status_code == 401


async def test_list_users_filters_by_role(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-filter@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-role-filter@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, params={"role_id": rep.role_id}, headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert rep.email in emails
    assert admin.email not in emails


async def test_list_users_filters_by_is_active(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-status-filter@example.com", role=UserRole.ADMIN)
    active = await make_user(email="active-status-filter@example.com", role=UserRole.SALES_REP)
    inactive = await make_user(
        email="inactive-status-filter@example.com", role=UserRole.SALES_REP, is_active=False
    )
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, params={"is_active": "false"}, headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert inactive.email in emails
    assert active.email not in emails


async def test_list_users_search_matches_name_or_email(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-search-filter@example.com", role=UserRole.ADMIN)
    match = await make_user(
        email="findme@example.com", role=UserRole.SALES_REP, first_name="Karthick"
    )
    other = await make_user(email="other-search@example.com", role=UserRole.SALES_REP, first_name="Vishnu")
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, params={"search": "karthick"}, headers=headers)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert match.email in emails
    assert other.email not in emails

    response_by_email = await client.get(USERS_URL, params={"search": "findme"}, headers=headers)
    emails_by_email = {u["email"] for u in response_by_email.json()}
    assert match.email in emails_by_email


async def test_list_users_filters_by_status_invited(client: AsyncClient, make_user, auth_headers, db_session):
    from datetime import UTC, datetime

    admin = await make_user(email="admin-invited-filter@example.com", role=UserRole.ADMIN)
    admin.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    await db_session.flush()
    invited = await make_user(email="invited-filter@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, params={"status": "invited"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    emails = {u["email"] for u in body}
    assert invited.email in emails
    assert admin.email not in emails
    assert next(u for u in body if u["email"] == invited.email)["status"] == "invited"


async def test_user_read_status_reflects_active_and_deactivated(
    client: AsyncClient, make_user, auth_headers, db_session
):
    from datetime import UTC, datetime

    admin = await make_user(email="admin-status-shape@example.com", role=UserRole.ADMIN)
    admin.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    await db_session.flush()
    deactivated = await make_user(
        email="deactivated-status-shape@example.com", role=UserRole.SALES_REP, is_active=False
    )
    headers = auth_headers(admin)

    response = await client.get(USERS_URL, headers=headers)

    body = response.json()
    by_email = {u["email"]: u for u in body}
    assert by_email[admin.email]["status"] == "active"
    assert by_email[deactivated.email]["status"] == "deactivated"


async def test_delete_user_as_admin_returns_204_and_shows_as_deactivated(
    client: AsyncClient, make_user, auth_headers
):
    admin = await make_user(email="admin-deleter@example.com", role=UserRole.ADMIN)
    target = await make_user(email="delete-target@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.delete(f"{USERS_URL}/{target.id}", headers=headers)
    assert response.status_code == 204

    list_response = await client.get(USERS_URL, params={"status": "deactivated"}, headers=headers)
    by_email = {u["email"]: u for u in list_response.json()}
    assert by_email[target.email]["status"] == "deactivated"


async def test_delete_user_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-cant-delete@example.com", role=UserRole.SALES_REP)
    target = await make_user(email="delete-target-403@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{USERS_URL}/{target.id}", headers=headers)

    assert response.status_code == 403


async def test_delete_user_unknown_id_returns_404(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-delete-404@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.delete(f"{USERS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_user_no_auth_header_returns_401(client: AsyncClient, make_user):
    target = await make_user(email="delete-target-401@example.com", role=UserRole.SALES_REP)

    response = await client.delete(f"{USERS_URL}/{target.id}")

    assert response.status_code == 401


async def test_delete_user_permanent_removes_from_list(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-hard-deleter@example.com", role=UserRole.ADMIN)
    target = await make_user(email="hard-delete-target@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.delete(f"{USERS_URL}/{target.id}", params={"permanent": "true"}, headers=headers)
    assert response.status_code == 204

    list_response = await client.get(USERS_URL, headers=headers)
    emails = [u["email"] for u in list_response.json()]
    assert target.email not in emails


async def test_delete_user_permanent_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-cant-hard-delete@example.com", role=UserRole.SALES_REP)
    target = await make_user(email="hard-delete-target-403@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{USERS_URL}/{target.id}", params={"permanent": "true"}, headers=headers)

    assert response.status_code == 403


async def test_reinvite_user_regenerates_password_and_reactivates(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-reinviter@example.com", role=UserRole.ADMIN)
    target = await make_user(
        email="reinvite-target@example.com", role=UserRole.SALES_REP, is_active=False
    )
    headers = auth_headers(admin)

    response = await client.post(f"{USERS_URL}/{target.id}/reinvite", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "invited"
    emails = [c["to"] for c in fake_email_sender.calls]
    assert target.email in emails


async def test_reinvite_user_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-cant-reinvite@example.com", role=UserRole.SALES_REP)
    target = await make_user(email="reinvite-target-403@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(f"{USERS_URL}/{target.id}/reinvite", headers=headers)

    assert response.status_code == 403


async def test_reinvite_user_unknown_id_returns_404(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-reinvite-404@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(f"{USERS_URL}/999999/reinvite", headers=headers)

    assert response.status_code == 404


async def test_update_user_role_changes_role(client: AsyncClient, make_user, auth_headers, db_session):
    from tests.support.roles import role_id_for

    admin = await make_user(email="admin-role-updater@example.com", role=UserRole.ADMIN)
    target = await make_user(email="role-update-target@example.com", role=UserRole.SALES_REP)
    manager_role_id = await role_id_for(db_session, UserRole.SALES_MANAGER)
    headers = auth_headers(admin)

    response = await client.patch(
        f"{USERS_URL}/{target.id}/role", json={"role_id": manager_role_id}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["role"]["id"] == manager_role_id


async def test_update_user_role_as_sales_rep_returns_403(client: AsyncClient, make_user, auth_headers, db_session):
    from tests.support.roles import role_id_for

    rep = await make_user(email="rep-cant-change-role@example.com", role=UserRole.SALES_REP)
    target = await make_user(email="role-update-target-403@example.com", role=UserRole.SALES_REP)
    manager_role_id = await role_id_for(db_session, UserRole.SALES_MANAGER)
    headers = auth_headers(rep)

    response = await client.patch(
        f"{USERS_URL}/{target.id}/role", json={"role_id": manager_role_id}, headers=headers
    )

    assert response.status_code == 403


async def test_update_user_role_rejects_self_change(client: AsyncClient, make_user, auth_headers, db_session):
    from tests.support.roles import role_id_for

    admin = await make_user(email="admin-self-role@example.com", role=UserRole.ADMIN)
    manager_role_id = await role_id_for(db_session, UserRole.SALES_MANAGER)
    headers = auth_headers(admin)

    response = await client.patch(
        f"{USERS_URL}/{admin.id}/role", json={"role_id": manager_role_id}, headers=headers
    )

    assert response.status_code == 400


async def test_update_user_role_unknown_role_returns_404(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-role-404@example.com", role=UserRole.ADMIN)
    target = await make_user(email="role-update-unknown-role@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.patch(
        f"{USERS_URL}/{target.id}/role", json={"role_id": 999_999}, headers=headers
    )

    assert response.status_code == 404


ME_URL = f"{USERS_URL}/me"
ME_PASSWORD_URL = f"{USERS_URL}/me/password"


async def test_get_me_returns_own_profile(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="get-me@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "get-me@example.com"
    assert body["phone_number"] is None
    assert body["avatar_url"] is None
    assert "created_at" in body


async def test_get_me_no_auth_header_returns_401(client: AsyncClient):
    response = await client.get(ME_URL)

    assert response.status_code == 401


async def test_patch_me_updates_name_and_phone(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="patch-me@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.patch(
        ME_URL,
        json={"first_name": "Sarah", "last_name": "Jenkins", "phone_number": "+919845012233"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Sarah"
    assert body["last_name"] == "Jenkins"
    assert body["phone_number"] == "+919845012233"


async def test_patch_me_does_not_accept_email_change(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="patch-me-email@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.patch(
        ME_URL,
        json={"first_name": "Sarah", "email": "changed@example.com"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["email"] == "patch-me-email@example.com"


async def test_change_password_with_correct_current_password_returns_204(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="change-pw@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "BrandNewPass1"},
        headers=headers,
    )

    assert response.status_code == 204

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "change-pw@example.com", "password": "BrandNewPass1"},
    )
    assert login_response.status_code == 200


async def test_change_password_wrong_current_password_returns_400(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="change-pw-wrong@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "wrong-password", "new_password": "BrandNewPass1"},
        headers=headers,
    )

    assert response.status_code == 400


async def test_change_password_rejects_current_access_token_afterwards(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="change-pw-forces-logout@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "BrandNewPass1"},
        headers=headers,
    )
    assert response.status_code == 204

    me_response = await client.get(f"{USERS_URL}/me", headers=headers)
    assert me_response.status_code == 401


async def test_change_password_revokes_existing_refresh_token(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="change-pw-revokes-refresh@example.com", password="correct-password", role=UserRole.SALES_REP)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "change-pw-revokes-refresh@example.com", "password": "correct-password"},
    )
    refresh_token = login_response.json()["refresh_token"]
    headers = auth_headers(user)

    await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "BrandNewPass1"},
        headers=headers,
    )

    refresh_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 401


async def test_change_password_too_short_returns_422(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="change-pw-short@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "short"},
        headers=headers,
    )

    assert response.status_code == 422


ME_AVATAR_URL = f"{USERS_URL}/me/avatar"


async def test_upload_avatar_returns_updated_profile(client: AsyncClient, make_user, auth_headers):
    import pathlib

    user = await make_user(email="upload-avatar@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"] == f"/media/avatars/{user.id}.png"

    pathlib.Path(f"media/avatars/{user.id}.png").unlink()


async def test_upload_avatar_rejects_unsupported_type_returns_400(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="upload-avatar-bad-type@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_AVATAR_URL,
        headers=headers,
        files={"file": ("doc.pdf", b"whatever", "application/pdf")},
    )

    assert response.status_code == 400


async def test_upload_avatar_no_auth_header_returns_401(client: AsyncClient):
    response = await client.post(
        ME_AVATAR_URL,
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )

    assert response.status_code == 401


async def test_delete_avatar_clears_avatar_url(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="delete-avatar@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)
    await client.post(
        ME_AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )

    response = await client.delete(ME_AVATAR_URL, headers=headers)

    assert response.status_code == 200
    assert response.json()["avatar_url"] is None


async def test_delete_avatar_no_auth_header_returns_401(client: AsyncClient):
    response = await client.delete(ME_AVATAR_URL)

    assert response.status_code == 401
