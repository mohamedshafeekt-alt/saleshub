"""User business logic: creation (with duplicate-email guard) and authentication."""

import secrets
import string
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import BackgroundTasks
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.enums import AuditAction
from app.models.role import Role
from app.models.user import User, UserStatus
from app.schemas.user import UserCreate, UserUpdate
from app.core.logging import logger
from app.services.audit_service import log_audit
from app.services.email.sender import EmailSender
from app.services.email.templates import send_new_user_credentials_email
from app.services.file_upload_service import UnsupportedFileTypeError
from app.services.storage import get_storage_service


class EmailAlreadyExistsError(Exception):
    """Raised when attempting to create a user with an email already in use."""


class UserNotFoundError(Exception):
    """Raised when a user id doesn't match an existing, non-deleted user."""


class RoleNotFoundError(Exception):
    """Raised when a role id doesn't match an existing, non-deleted role."""


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(12))


async def _send_new_user_email_safe(email_sender: EmailSender, to: str, password: str) -> None:
    try:
        await send_new_user_credentials_email(email_sender, to, password)
    except Exception:
        logger.warning("Failed to send new-user credentials email to %s", to, exc_info=True)


async def create_user(
    db: AsyncSession,
    data: UserCreate,
    email_sender: EmailSender,
    actor_id: int,
    background_tasks: BackgroundTasks | None = None,
) -> User:
    role = await db.get(Role, data.role_id)
    if role is None or role.is_delete:
        raise RoleNotFoundError(f"Role not found: {data.role_id}")

    password = _generate_password()

    result = await db.execute(
        select(User).where(User.email == data.email, User.is_delete.is_(True))
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.first_name = data.first_name
        existing.last_name = data.last_name
        existing.role_id = data.role_id
        existing.hashed_password = hash_password(password)
        existing.is_delete = False
        existing.is_active = True
        user = existing
    else:
        user = User(
            email=data.email,
            hashed_password=hash_password(password),
            first_name=data.first_name,
            last_name=data.last_name,
            role_id=data.role_id,
        )
        db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyExistsError(f"Email already exists: {data.email}") from exc

    await db.refresh(user, attribute_names=["role"])

    await log_audit(
        db, table_name="users", record_id=user.id, action=AuditAction.CREATED,
        actor_id=actor_id, description=f"User '{user.email}' created",
    )

    # Not awaited inline when a background_tasks handle is available: SMTP is
    # slow/flaky enough (real mail server round-trip) that awaiting it here
    # was making "create user" time out on the client. background_tasks is
    # None in service-level tests calling create_user directly -- falls back
    # to the old inline-await behavior there.
    if background_tasks is not None:
        background_tasks.add_task(_send_new_user_email_safe, email_sender, user.email, password)
    else:
        await _send_new_user_email_safe(email_sender, user.email, password)

    return user


async def list_users(
    db: AsyncSession,
    *,
    role_id: int | None = None,
    is_active: bool | None = None,
    status: UserStatus | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[User]:
    filters: list[ColumnElement[bool]] = [User.is_delete.is_(False)]
    if role_id is not None:
        filters.append(User.role_id == role_id)
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if status is not None:
        if status is UserStatus.DEACTIVATED:
            filters.append(User.is_active.is_(False))
        elif status is UserStatus.INVITED:
            filters.append(User.is_active.is_(True))
            filters.append(User.last_login_at.is_(None))
        else:
            filters.append(User.is_active.is_(True))
            filters.append(User.last_login_at.is_not(None))
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if date_from is not None:
        filters.append(User.created_at >= date_from)
    if date_to is not None:
        filters.append(User.created_at < date_to)

    result = await db.execute(
        select(User).where(*filters).order_by(User.first_name, User.last_name)
    )
    return list(result.scalars().all())


async def soft_delete_user(db: AsyncSession, user_id: int, actor_id: int) -> None:
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_delete.is_(False))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"User not found: {user_id}")

    if not user.is_active:
        return

    email = user.email
    user.is_active = False
    await db.flush()
    await log_audit(
        db, table_name="users", record_id=user_id, action=AuditAction.DEACTIVATED,
        actor_id=actor_id, description=f"User '{email}' deactivated",
    )


async def activate_user(db: AsyncSession, user_id: int, actor_id: int) -> None:
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_delete.is_(False))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"User not found: {user_id}")

    if user.is_active:
        return

    email = user.email
    user.is_active = True
    await db.flush()
    await log_audit(
        db, table_name="users", record_id=user_id, action=AuditAction.ACTIVATED,
        actor_id=actor_id, description=f"User '{email}' activated",
    )

class IncorrectPasswordError(Exception):
    """Raised when current_password doesn't match the user's stored hash."""


async def update_profile(db: AsyncSession, user: User, data: UserUpdate) -> User:
    user.first_name = data.first_name
    user.last_name = data.last_name
    user.phone_number = data.phone_number
    await db.flush()
    return user


async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise IncorrectPasswordError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    # Naive UTC: written straight into the (timezone-naive) column with no
    # server-side tz conversion, so it compares directly against the JWT
    # "iat" claim (also naive UTC) in rbac_middleware.enforce_rbac.
    user.password_changed_at = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    await log_audit(
        db, table_name="users", record_id=user.id, action=AuditAction.UPDATED,
        actor_id=user.id, description=f"User '{user.email}' changed their password",
    )


class UnsupportedImageTypeError(UnsupportedFileTypeError):
    """Raised when an avatar upload isn't image/png or image/jpeg."""


_avatar_upload_service = get_storage_service(
    base_dir=Path("media/avatars"),
    allowed_content_types={"image/png": ".png", "image/jpeg": ".jpg"},
)


async def save_avatar(db: AsyncSession, user: User, content: bytes, content_type: str) -> str:
    try:
        # ponytail: fixed filename per user means switching png<->jpeg leaves the
        # old file orphaned on disk; not worth a cleanup pass for an internal tool.
        avatar_url = _avatar_upload_service.save(content, content_type, filename_stem=str(user.id))
    except UnsupportedFileTypeError as exc:
        raise UnsupportedImageTypeError(str(exc)) from exc

    user.avatar_url = avatar_url
    await db.flush()
    return user.avatar_url


async def remove_avatar(db: AsyncSession, user: User) -> None:
    if user.avatar_url is not None:
        _avatar_upload_service.delete(user.avatar_url)
    user.avatar_url = None
    await db.flush()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user
