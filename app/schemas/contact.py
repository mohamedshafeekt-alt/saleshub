"""Contact request/response schemas.

Contact is a standalone person record -- it's linked to Account(s) via
ContactAccount (app/schemas/contact_account.py), not by a field here.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator
from app.schemas.base import ORMBase

from app.schemas.validators import validate_linkedin_url

from app.models.enums import LeadTier


class ContactCreate(BaseModel):
    first_name: str
    last_name: str | None = None
    email: EmailStr
    phone: str | None = None
    alternate_phone: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None

    _validate_linkedin_url = field_validator("linkedin_url")(validate_linkedin_url)


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None

    _validate_linkedin_url = field_validator("linkedin_url")(validate_linkedin_url)


class ContactRead(ORMBase):

    id: int
    first_name: str
    last_name: str | None
    email: str
    phone: str | None
    alternate_phone: str | None
    job_title: str | None
    linkedin_url: str | None


class ContactOverviewRead(BaseModel):
    """The Contact Detail screen's Overview tab.

    A Contact can be linked to more than one Account (see ContactAccount), so
    owner_id/owner_name/tier/account_id/account_name are derived from a
    single representative link: the contact's oldest ContactAccount row
    marked is_primary=True, or its oldest link overall if none is primary
    (see contact_service._primary_account_link). All of those are null when
    the contact has no linked accounts at all.

    created_at is Contact.created_at (always present); created_by_name comes
    from the audit log's CREATED row for this contact (null if none exists,
    e.g. a contact created before audit logging or with no matching row).

    tags/about/last_activity/task_count/log_count have no backing model yet
    (no Tag model, no Contact-level notes/activity-log/Task model) -- always
    null until those are built, same pattern as AccountOverviewRead's
    last_activity/next_step/total_arr.
    """

    id: int
    first_name: str
    last_name: str | None
    email: str
    phone: str | None
    alternate_phone: str | None
    job_title: str | None
    linkedin_url: str | None
    is_primary: bool
    account_id: int | None
    account_name: str | None
    owner_id: int | None
    owner_name: str | None
    tier: LeadTier | None
    deal_count: int
    created_at: datetime
    created_by_name: str | None = None
    task_count: int | None = None
    log_count: int | None = None
    tags: list[str] | None = None
    about: str | None = None
    last_activity: str | None = None


class ContactListItemRead(BaseModel):
    """One row of the Contacts List screen. account_id/account_name/owner
    fields are derived the same way as ContactOverviewRead (see its
    docstring) -- independent of which of the contact's linked accounts
    actually matched any owner/account/tier filter on the request."""

    id: int
    first_name: str
    last_name: str | None
    email: str
    phone: str | None
    job_title: str | None
    is_primary: bool
    account_id: int | None
    account_name: str | None
