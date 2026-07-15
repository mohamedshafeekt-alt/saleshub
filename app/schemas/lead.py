"""Lead request/response schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import LeadSource, LeadTier


class LeadCreate(BaseModel):
    first_name: str
    last_name: str | None = None
    company: str
    domain: str | None = None
    job_title: str | None = None
    email: EmailStr
    phone: str | None = None
    linkedin_url: str | None = None
    source: LeadSource
    tier: LeadTier
    owner_id: int
    next_follow_up_date: date | None = None
    follow_up_note: str | None = None


class LeadUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    domain: str | None = None
    job_title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    source: LeadSource | None = None
    tier: LeadTier | None = None
    owner_id: int | None = None
    next_follow_up_date: date | None = None
    follow_up_note: str | None = None


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    company: str
    domain: str | None
    job_title: str | None
    email: EmailStr
    phone: str | None
    linkedin_url: str | None
    source: LeadSource
    tier: LeadTier
    owner_id: int
    next_follow_up_date: date | None
    follow_up_note: str | None
