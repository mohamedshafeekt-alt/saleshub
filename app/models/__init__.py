"""Import all ORM models here so Base.metadata is fully populated for Alembic autogenerate."""

from app.models.account import Account
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.deal_stage_history import DealStageHistory
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_contact import LeadContact
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole

__all__ = [
    "Account",
    "Contact",
    "Deal",
    "DealStageHistory",
    "Lead",
    "LeadActivity",
    "LeadContact",
    "RefreshToken",
    "User",
    "UserRole",
]
