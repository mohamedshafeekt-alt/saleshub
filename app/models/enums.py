"""Shared enums for ORM models (roles, stages, tiers, etc.)."""

import enum


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INVITED = "invited"
    DEACTIVATED = "deactivated"


class LeadSource(str, enum.Enum):
    WEBSITE = "website"
    REFERRAL = "referral"
    COLD_CALL = "cold_call"
    LINKEDIN = "linkedin"
    EMAIL_CAMPAIGN = "email_campaign"
    OTHER = "other"


class LeadTier(str, enum.Enum):
    DIAMOND = "diamond"
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


class LeadStatus(str, enum.Enum):
    NOT_CONTACTED = "not_contacted"
    ATTEMPTED_TO_CONTACT = "attempted_to_contact"
    CONTACTED = "contacted"
    CONTACT_IN_FUTURE = "contact_in_future"
    JUNK_LEAD = "junk_lead"
    LOST_LEAD = "lost_lead"


class LeadActivityType(str, enum.Enum):
    NOTE = "note"
    MEETING = "meeting"
    CALL = "call"
    COMMENT = "comment"
    FOLLOW_UP = "follow_up"


class DealActivityType(str, enum.Enum):
    NOTE = "note"
    MEETING = "meeting"
    CALL = "call"
    COMMENT = "comment"
    FOLLOW_UP = "follow_up"


class AccountActivityType(str, enum.Enum):
    NOTE = "note"
    MEETING = "meeting"
    CALL = "call"
    COMMENT = "comment"
    FOLLOW_UP = "follow_up"


class NotificationType(str, enum.Enum):
    TASK_OVERDUE = "task_overdue"
    DEAL_STAGE_CHANGED = "deal_stage_changed"
    LEAD_ASSIGNED = "lead_assigned"
    NEW_LEAD = "new_lead"
