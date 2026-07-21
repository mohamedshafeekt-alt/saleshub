"""User business logic: creation (with duplicate-email guard) and authentication."""

import secrets
import string
from pathlib import Path

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.role import Role
from app.models.user import User, UserStatus
from app.schemas.user import UserCreate, UserUpdate
from app.core.logging import logger
from app.services.email.sender import EmailSender
from app.services.email.templates import send_new_user_credentials_email


class EmailAlreadyExistsError(Exception):
    """Raised when attempting to create a user with an email already in use."""


class UserNotFoundError(Exception):
    """Raised when a user id doesn't match an existing, non-deleted user."""


class RoleNotFoundError(Exception):
    """Raised when a role id doesn't match an existing, non-deleted role."""


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(12))


async def create_user(db: AsyncSession, data: UserCreate, email_sender: EmailSender) -> User:
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

    try:
        await send_new_user_credentials_email(email_sender, user.email, password)
    except Exception:
        logger.warning("Failed to send new-user credentials email to %s", user.email, exc_info=True)

    return user


async def list_users(
    db: AsyncSession,
    *,
    role_id: int | None = None,
    is_active: bool | None = None,
    status: UserStatus | None = None,
    search: str | None = None,
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

    result = await db.execute(
        select(User).where(*filters).order_by(User.first_name, User.last_name)
    )
    return list(result.scalars().all())


async def soft_delete_user(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(select(User).where(User.id == user_id, User.is_delete.is_(False)))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"User not found: {user_id}")

    user.is_delete = True
    await db.flush()


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
    await db.flush()


class UnsupportedImageTypeError(Exception):
    """Raised when an avatar upload isn't image/png or image/jpeg."""


_AVATAR_DIR = Path("media/avatars")
_AVATAR_EXTENSION_BY_CONTENT_TYPE = {"image/png": ".png", "image/jpeg": ".jpg"}


async def save_avatar(db: AsyncSession, user: User, content: bytes, content_type: str) -> str:
    extension = _AVATAR_EXTENSION_BY_CONTENT_TYPE.get(content_type)
    if extension is None:
        raise UnsupportedImageTypeError(f"Unsupported image type: {content_type}")

    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    # ponytail: fixed filename per user means switching png<->jpeg leaves the
    # old file orphaned on disk; not worth a cleanup pass for an internal tool.
    filename = f"{user.id}{extension}"
    (_AVATAR_DIR / filename).write_bytes(content)

    user.avatar_url = f"/media/avatars/{filename}"
    await db.flush()
    return user.avatar_url


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user
