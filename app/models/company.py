"""Company ORM model: minimal tenancy scaffold -- only deal_stages references
this today (see app/models/deal_stage.py). Not attached to Users/Accounts/
Deals; a single "Default" row is seeded for the current single-tenant setup."""

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["Company"]


class Company(Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(nullable=False)
