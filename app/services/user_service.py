"""User business logic: creation (with duplicate-email guard) and authentication."""

import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.logging import logger
from app.services.email.sender import EmailSender
from app.services.email.templates import send_new_user_credentials_email


class EmailAlreadyExistsError(Exception):
    """Raised when attempting to create a user with an email already in use."""


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(12))


async def create_user(db: AsyncSession, data: UserCreate, email_sender: EmailSender) -> User:
    password = _generate_password()
    user = User(
        email=data.email,
        hashed_password=hash_password(password),
        first_name=data.first_name,
        last_name=data.last_name,
        role=data.role,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyExistsError(f"Email already exists: {data.email}") from exc

    try:
        await send_new_user_credentials_email(email_sender, user.email, password)
    except Exception:
        logger.warning("Failed to send new-user credentials email to %s", user.email, exc_info=True)

    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.first_name, User.last_name))
    return list(result.scalars().all())


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user
