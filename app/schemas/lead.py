"""Lead request/response schemas."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models.enums import LeadSource, LeadStatus, LeadTier
from app.schemas.lead_activity import LeadActivityDetailRead


class LeadContactInput(BaseModel):
    """An extra contact point beyond the lead's own primary email/phone."""

    email: EmailStr | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> "LeadContactInput":
        if self.email is None and self.phone is None:
            raise ValueError("A contact needs at least one of email or phone")
        return self


class LeadContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    phone: str | None


class LeadUpsert(BaseModel):
    """Single request body for create-or-update: absent `id` creates a new
    lead (first_name/company/email/source become required), present `id`
    partially updates that lead (every field but `id` is optional and only
    supplied fields are applied)."""

    id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    domain: str | None = None
    job_title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    source: LeadSource | None = None
    status: LeadStatus | None = None
    owner_id: int | None = None
    next_follow_up_date: date | None = None
    follow_up_note: str | None = None
    contacts: list[LeadContactInput] = []

    @model_validator(mode="after")
    def _require_creation_fields_when_no_id(self) -> "LeadUpsert":
        if self.id is None:
            missing = [
                name
                for name, value in (
                    ("first_name", self.first_name),
                    ("company", self.company),
                    ("email", self.email),
                    ("source", self.source),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"Missing required field(s) for lead creation: {', '.join(missing)}")
        return self


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
    status: LeadStatus
    owner_id: int | None
    owner_name: str | None
    next_follow_up_date: date | None
    follow_up_note: str | None
    is_converted: bool
    created_at: datetime
    updated_at: datetime


class LeadDetailRead(LeadRead):
    """LeadRead plus everything the single-lead detail view needs: every
    extra contact, the full activity log (with who logged each one), a
    count for the Activity panel's badge, and the most recent activity's
    timestamp for the "Last Contact" stat."""

    contacts: list[LeadContactRead]
    activities: list[LeadActivityDetailRead]
    activity_count: int
    last_contact_at: datetime | None


class LeadConvertRequest(BaseModel):
    tier: LeadTier | None = None
    owner_id: int | None = None
