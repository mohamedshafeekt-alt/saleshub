"""Account-scoped contact schemas: the "Add Contact"/"Edit Contact" modal on
the Account Detail page, which creates/updates a Contact *and* its
ContactAccount link (with is_primary) for one specific account in a single
call.
"""

from pydantic import BaseModel, ConfigDict, model_validator


class AccountContactUpsert(BaseModel):
    """POST /accounts/{account_id}/contacts body: single route for create-or-
    update, same pattern as LeadUpsert -- absent `contact_id` creates a new
    Contact (first_name becomes required) and links it to this account;
    present `contact_id` updates that contact's fields (only those provided)
    and/or the is_primary flag for this account's link to it. If no link
    exists yet for this (account_id, contact_id) pair, one is created --
    this is how an existing contact gets associated with another account.
    """

    contact_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    is_primary: bool | None = None

    @model_validator(mode="after")
    def _first_name_required_when_creating(self) -> "AccountContactUpsert":
        if self.contact_id is None and self.first_name is None:
            raise ValueError("first_name is required when contact_id is not given")
        return self


class AccountContactRead(BaseModel):
    """A contact as seen from one specific account's Contacts tab -- same
    fields as ContactRead, plus is_primary for *this* account (a Contact
    linked to multiple accounts can be primary for one and not another)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    alternate_phone: str | None
    job_title: str | None
    linkedin_url: str | None
    is_primary: bool
