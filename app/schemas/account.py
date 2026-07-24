"""Account request/response schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.models.enums import LeadTier
from app.schemas.contact_account import AccountContactRead
from app.schemas.deal import DealRead
from app.schemas.validators import validate_linkedin_url


class AccountContactInput(BaseModel):
    """A contact to save alongside a new Account (e.g. from the New Lead
    form's "Save & Convert to Account" action).

    Only the first contact in the request's `contacts` list is required to
    carry first_name/last_name -- create_account fills in the missing name
    from the first contact, since Contact.first_name is NOT NULL. email is
    required on every contact (Contact.email is NOT NULL and globally
    unique); phone is purely optional, no longer an alternative to email. At
    most one contact in the whole list may set is_primary=True (enforced
    alongside any pre-existing primary contact by create_account/
    update_account -- see PrimaryContactAlreadyExistsError).
    """

    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr
    phone: str | None = None
    job_title: str | None = None
    is_primary: bool = False


class AccountCreate(BaseModel):
    company: str
    domain: str
    tier: LeadTier
    owner_id: int
    industry: str | None = None
    city: str | None = None
    description: str | None = None
    linkedin_url: str | None = None
    contacts: list[AccountContactInput] = []

    _validate_linkedin_url = field_validator("linkedin_url")(validate_linkedin_url)

    @model_validator(mode="after")
    def _first_contact_requires_name(self) -> "AccountCreate":
        if self.contacts and self.contacts[0].first_name is None:
            raise ValueError("The first contact must include first_name")
        return self


class AccountUpdate(BaseModel):
    company: str | None = None
    domain: str | None = None
    tier: LeadTier | None = None
    owner_id: int | None = None
    industry: str | None = None
    city: str | None = None
    description: str | None = None
    linkedin_url: str | None = None
    # Appends to the account's existing contacts -- never replaces or edits
    # them (use the dedicated PATCH /contacts/{id} for that). Same rule as
    # AccountCreate.contacts: only the first entry needs a first_name.
    contacts: list[AccountContactInput] = []

    _validate_linkedin_url = field_validator("linkedin_url")(validate_linkedin_url)

    @model_validator(mode="after")
    def _first_contact_requires_name(self) -> "AccountUpdate":
        if self.contacts and self.contacts[0].first_name is None:
            raise ValueError("The first contact must include first_name")
        return self


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    domain: str | None
    tier: LeadTier
    owner_id: int
    owner_name: str
    source_lead_id: int | None
    industry: str | None
    city: str | None
    description: str | None
    linkedin_url: str | None
    contact_count: int
    deal_count: int


class AccountOverviewRead(BaseModel):
    """The Account Overview screen: account fields, its full contact list,
    and its open (non-closed/non-cold) deals with their total value.

    last_activity/next_step/total_arr have no backing model yet (no
    generic Account activity log, no ARR field) -- always null until those
    are built.
    """

    id: int
    company: str
    domain: str | None
    tier: LeadTier
    owner_id: int
    owner_name: str
    industry: str | None
    city: str | None
    description: str | None
    linkedin_url: str | None
    open_deal_value: float
    last_activity: str | None = None
    next_step: str | None = None
    total_arr: float | None = None
    key_contacts: list[AccountContactRead]
    active_deals: list[DealRead]
