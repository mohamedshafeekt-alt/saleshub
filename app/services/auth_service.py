"""Session lifecycle: issue an access+refresh token pair at login, exchange a
refresh token for a new access token, and revoke a refresh token on logout."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_token
from app.models.enums import AuditAction
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.audit_service import log_audit


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token is unknown, expired, revoked, or its user is inactive."""


_IST = ZoneInfo("Asia/Kolkata")


def _now_ist() -> datetime:
    # Naive IST wall-clock time, to match Postgres' func.now() (used for
    # created_at/updated_at) — the DB session timezone is Asia/Kolkata, so
    # storing UTC here would silently disagree with those columns.
    return datetime.now(_IST).replace(tzinfo=None)


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token()
    user.last_login_at = _now_ist()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=_now_ist() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await log_audit(
        db,
        table_name="users",
        record_id=user.id,
        action=AuditAction.LOGIN,
        actor_id=user.id,
        description=f"User '{user.email}' logged in",
    )
    await db.commit()
    return access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    stored = result.scalar_one_or_none()
    if stored is None or stored.revoked_at is not None or stored.expires_at < _now_ist():
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
        stored.revoked_at = _now_ist()
        await log_audit(
            db,
            table_name="users",
            record_id=user.id,
            action=AuditAction.LOGOUT,
            actor_id=user.id,
            description=f"User '{user.email}' logged out",
        )
        await db.commit()


async def revoke_all_refresh_tokens(db: AsyncSession, user: User) -> None:
    """Revoke every one of the user's still-valid refresh tokens -- used on
    password change, so every other logged-in session is forced to log in
    again rather than silently keeping a stale-password session alive."""
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    )
    now = _now_ist()
    for stored in result.scalars():
        stored.revoked_at = now
