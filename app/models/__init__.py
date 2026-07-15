"""Import all ORM models here so Base.metadata is fully populated for Alembic autogenerate."""

from app.models.lead import Lead
from app.models.user import User, UserRole

__all__ = ["Lead", "User", "UserRole"]
