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


class DealStage(str, enum.Enum):
    RECEIVED_REQUIREMENTS = "received_requirements"
    QUALIFIED_TO_BUY = "qualified_to_buy"
    EVALUATION = "evaluation"
    PROPOSALS = "proposals"
    CONTRACTS = "contracts"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    COLD_DEALS = "cold_deals"
