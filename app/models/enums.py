"""Shared enums for ORM models (roles, stages, tiers, etc.)."""

import enum


class UserRole(str, enum.Enum):
    SALES_REP = "sales_rep"
    DELIVERY_SME = "delivery_sme"
    SALES_MANAGER = "sales_manager"
    ADMIN = "admin"


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
