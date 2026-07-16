"""Account request/response schemas."""

from pydantic import BaseModel, ConfigDict

from app.models.enums import LeadTier


class AccountCreate(BaseModel):
    company: str
    domain: str | None = None
    tier: LeadTier
    owner_id: int
    industry: str | None = None
    city: str | None = None
    description: str | None = None


class AccountUpdate(BaseModel):
    company: str | None = None
    domain: str | None = None
    tier: LeadTier | None = None
    owner_id: int | None = None
    industry: str | None = None
    city: str | None = None
    description: str | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    domain: str | None
    tier: LeadTier
    owner_id: int
    source_lead_id: int | None
    industry: str | None
    city: str | None
    description: str | None
