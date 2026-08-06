"""app.services.auth_service: issue/refresh/revoke refresh tokens.

Covers: login issues a valid pair; refresh exchanges a valid refresh token
for a new access token; refresh rejects unknown/expired/revoked tokens and
tokens belonging to a since-deactivated user; revoke is scoped to the
owning user and is idempotent.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, hash_token, verify_password
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.services.auth_service import (
    InvalidRefreshTokenError,
    InvalidResetTokenError,
    issue_tokens,
    refresh_access_token,
    request_password_reset,
    reset_password,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
)


class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


async def test_issue_tokens_returns_valid_access_and_refresh_token(db_session: AsyncSession, make_user):
    user = await make_user(email="issue@example.com")

    access_token, refresh_token = await issue_tokens(db_session, user)

    assert decode_access_token(access_token)["sub"] == str(user.id)
    assert len(refresh_token) > 20

    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    stored = result.scalar_one()
    assert stored.token_hash == hash_token(refresh_token)
    assert stored.revoked_at is None


async def test_refresh_access_token_issues_new_access_token_for_valid_refresh_token(
    db_session: AsyncSession, make_user
):
    user = await make_user(email="refresh-ok@example.com")
    _, refresh_token = await issue_tokens(db_session, user)

    new_access_token = await refresh_access_token(db_session, refresh_token)

    assert decode_access_token(new_access_token)["sub"] == str(user.id)


async def test_refresh_access_token_rejects_unknown_token(db_session: AsyncSession):
    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, "not-a-real-token")


async def test_refresh_access_token_rejects_expired_token(db_session: AsyncSession, make_user):
    user = await make_user(email="refresh-expired@example.com")
    token = "expired-token-value"
    db_session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
    )
    await db_session.commit()

    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, token)


async def test_refresh_access_token_rejects_revoked_token(db_session: AsyncSession, make_user):
    user = await make_user(email="refresh-revoked@example.com")
    _, refresh_token = await issue_tokens(db_session, user)
    await revoke_refresh_token(db_session, user, refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, refresh_token)


async def test_refresh_access_token_rejects_token_for_deactivated_user(
    db_session: AsyncSession, make_user
):
    user = await make_user(email="refresh-inactive@example.com")
    _, refresh_token = await issue_tokens(db_session, user)

    user.is_active = False
    await db_session.commit()

    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, refresh_token)


async def test_revoke_refresh_token_marks_it_revoked(db_session: AsyncSession, make_user):
    user = await make_user(email="revoke-ok@example.com")
    _, refresh_token = await issue_tokens(db_session, user)

    await revoke_refresh_token(db_session, user, refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, refresh_token)


async def test_revoke_refresh_token_does_not_revoke_another_users_token(
    db_session: AsyncSession, make_user
):
    owner = await make_user(email="revoke-owner@example.com")
    other = await make_user(email="revoke-other@example.com")
    _, refresh_token = await issue_tokens(db_session, owner)

    await revoke_refresh_token(db_session, other, refresh_token)

    # still valid -- `other` was not permitted to revoke `owner`'s token
    new_access_token = await refresh_access_token(db_session, refresh_token)
    assert decode_access_token(new_access_token)["sub"] == str(owner.id)


async def test_revoke_refresh_token_is_idempotent_for_unknown_token(
    db_session: AsyncSession, make_user
):
    user = await make_user(email="revoke-unknown@example.com")

    # must not raise
    await revoke_refresh_token(db_session, user, "never-issued-token")


async def test_revoke_all_refresh_tokens_revokes_every_session(db_session: AsyncSession, make_user):
    user = await make_user(email="revoke-all@example.com")
    _, first_token = await issue_tokens(db_session, user)
    _, second_token = await issue_tokens(db_session, user)

    await revoke_all_refresh_tokens(db_session, user)
    await db_session.commit()

    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, first_token)
    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, second_token)


async def test_revoke_all_refresh_tokens_does_not_affect_another_user(db_session: AsyncSession, make_user):
    target = await make_user(email="revoke-all-target@example.com")
    other = await make_user(email="revoke-all-other@example.com")
    _, other_token = await issue_tokens(db_session, other)

    await revoke_all_refresh_tokens(db_session, target)
    await db_session.commit()

    new_access_token = await refresh_access_token(db_session, other_token)
    assert decode_access_token(new_access_token)["sub"] == str(other.id)


async def test_issue_tokens_sets_last_login_at(db_session: AsyncSession, make_user):
    user = await make_user(email="stamps-last-login@example.com")
    assert user.last_login_at is None

    await issue_tokens(db_session, user)

    assert user.last_login_at is not None


async def test_issue_tokens_writes_audit_log(db_session: AsyncSession, make_user):
    from app.models.audit_log import AuditLog

    user = await make_user(email="auth-audit-login@example.com")
    await issue_tokens(db_session, user)

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.table_name == "users", AuditLog.record_id == user.id, AuditLog.action == "login"
        )
    )
    assert result.scalar_one() is not None


async def test_revoke_refresh_token_writes_audit_log(db_session: AsyncSession, make_user):
    from app.models.audit_log import AuditLog

    user = await make_user(email="auth-audit-logout@example.com")
    _, refresh_token = await issue_tokens(db_session, user)
    await revoke_refresh_token(db_session, user, refresh_token)

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.table_name == "users", AuditLog.record_id == user.id, AuditLog.action == "logout"
        )
    )
    assert result.scalar_one() is not None


async def test_request_password_reset_creates_token_and_sends_email(db_session: AsyncSession, make_user):
    user = await make_user(email="forgot@example.com")
    sender = _FakeEmailSender()

    await request_password_reset(db_session, user.email, sender)

    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    stored = result.scalar_one()
    assert stored.used_at is None
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == user.email


async def test_request_password_reset_unknown_email_sends_nothing_and_does_not_raise(
    db_session: AsyncSession,
):
    sender = _FakeEmailSender()

    await request_password_reset(db_session, "nobody@example.com", sender)

    assert sender.sent == []


async def test_request_password_reset_inactive_user_sends_nothing(db_session: AsyncSession, make_user):
    user = await make_user(email="forgot-inactive@example.com", is_active=False)
    sender = _FakeEmailSender()

    await request_password_reset(db_session, user.email, sender)

    assert sender.sent == []


async def _issue_reset_token(db_session: AsyncSession, sender: _FakeEmailSender, email: str) -> str:
    await request_password_reset(db_session, email, sender)
    # test-only: pull the raw token back out via the reset link it was sent in
    return sender.sent[-1][2].split("?token=")[1].split("\n")[0]


async def test_reset_password_updates_password_and_revokes_sessions(db_session: AsyncSession, make_user):
    user = await make_user(email="reset-ok@example.com")
    _, refresh_token = await issue_tokens(db_session, user)
    sender = _FakeEmailSender()
    token = await _issue_reset_token(db_session, sender, user.email)

    await reset_password(db_session, token, "brand-new-password")

    await db_session.refresh(user)
    assert verify_password("brand-new-password", user.hashed_password)
    with pytest.raises(InvalidRefreshTokenError):
        await refresh_access_token(db_session, refresh_token)


async def test_reset_password_rejects_unknown_token(db_session: AsyncSession):
    with pytest.raises(InvalidResetTokenError):
        await reset_password(db_session, "not-a-real-token", "whatever-new-pw")


async def test_reset_password_rejects_expired_token(db_session: AsyncSession, make_user):
    user = await make_user(email="reset-expired@example.com")
    token = "expired-reset-token"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    with pytest.raises(InvalidResetTokenError):
        await reset_password(db_session, token, "whatever-new-pw")


async def test_reset_password_rejects_already_used_token(db_session: AsyncSession, make_user):
    user = await make_user(email="reset-used@example.com")
    sender = _FakeEmailSender()
    token = await _issue_reset_token(db_session, sender, user.email)
    await reset_password(db_session, token, "first-new-password")

    with pytest.raises(InvalidResetTokenError):
        await reset_password(db_session, token, "second-new-password")
