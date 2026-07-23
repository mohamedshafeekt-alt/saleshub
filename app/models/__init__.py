"""Import all ORM models here so Base.metadata is fully populated for Alembic autogenerate."""

from app.models.account import Account
from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.deal_contact import DealContact
from app.models.deal_stage import DealStage
from app.models.deal_stage_history import DealStageHistory
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_contact import LeadContact
from app.models.notification import Notification
from app.models.permission import Permission
from app.models.refresh_token import RefreshToken
from app.models.role import Role
from app.models.user import User, UserStatus

__all__ = [
    "Account",
    "Company",
    "Contact",
    "Deal",
    "DealContact",
    "DealStage",
    "DealStageHistory",
    "Lead",
    "LeadActivity",
    "LeadContact",
    "Notification",
    "Permission",
    "RefreshToken",
    "Role",
    "User",
    "UserStatus",
]
