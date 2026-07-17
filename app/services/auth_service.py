"""Session lifecycle: issue an access+refresh token pair at login, exchange a
refresh token for a new access token, and revoke a refresh token on logout."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_token
from app.models.refresh_token import RefreshToken
from app.models.user import User


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token is unknown, expired, revoked, or its user is inactive."""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=_utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    return access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    stored = result.scalar_one_or_none()
    if stored is None or stored.revoked_at is not None or stored.expires_at < _utcnow():
        raise InvalidRefreshTokenError("Invalid or expired refresh token")

    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError("Invalid or expired refresh token")

    return create_access_token(subject=str(user.id))


async def revoke_refresh_token(db: AsyncSession, user: User, refresh_token: str) -> None:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(refresh_token),
            RefreshToken.user_id == user.id,
        )
    )
    stored = result.scalar_one_or_none()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = _utcnow()
        await db.commit()
