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

from app.core.security import decode_access_token, hash_token
from app.models.refresh_token import RefreshToken
from app.services.auth_service import (
    InvalidRefreshTokenError,
    issue_tokens,
    refresh_access_token,
    revoke_refresh_token,
)


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
