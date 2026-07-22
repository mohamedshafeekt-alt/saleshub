"""Contact request/response schemas.

Contact is a standalone person record -- it's linked to Account(s) via
ContactAccount (app/schemas/contact_account.py), not by a field here.
"""

from pydantic import BaseModel, ConfigDict


class ContactCreate(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    alternate_phone: str | None
    job_title: str | None
    linkedin_url: str | None
