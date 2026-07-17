"""Password hashing, JWT create/decode, and refresh-token helpers."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (expires_delta if expires_delta is not None else timedelta(minutes=settings.jwt_expire_minutes))
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def create_refresh_token() -> str:
    """Opaque high-entropy token — not a JWT, so it can be revoked server-side
    (a signed JWT would remain valid until it expired, logout couldn't kill it)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 for exact-match lookup. Not bcrypt: this is a high-entropy
    random token, not a low-entropy password, so a slow salted hash buys
    nothing and would force a full-table scan instead of an indexed lookup."""
    return hashlib.sha256(token.encode()).hexdigest()
