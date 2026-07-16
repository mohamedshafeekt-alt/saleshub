"""Contact request/response schemas."""

from pydantic import BaseModel, ConfigDict


class ContactCreate(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    account_id: int


class ContactUpdate(BaseModel):
    # No account_id: reassigning a contact to a different account would need
    # its own ownership check against the destination account, which nothing
    # here performs — a contact stays with the account it was created under.
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    job_title: str | None
    account_id: int
