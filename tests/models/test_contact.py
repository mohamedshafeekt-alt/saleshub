"""app.models.contact: Contact ORM model construction + constraints.

Covers: construction with all fields (including linkedin_url/alternate_phone)
persists and round-trips; created_at/updated_at present via Base
inheritance; first_name and email are both NOT NULL (required); email is
globally unique; Contact has no account_id of its own -- association with an
Account goes through ContactAccount (see tests/models/test_contact_account.py).
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.enums import LeadTier
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def _make_owner(db_session: AsyncSession, email: str = "owner-contact@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role_id=await role_id_for(db_session, UserRole.SALES_REP))
    db_session.add(owner)
    await db_session.flush()
    return owner


async def _make_account(db_session: AsyncSession, owner_id: int, company: str = "Acme Corp"):
    from app.models.account import Account

    account = Account(company=company, tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


async def test_contact_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    contact = Contact(
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@acme.com",
        phone="555-1234",
        alternate_phone="555-5678",
        job_title="VP Sales",
        linkedin_url="linkedin.com/in/janedoe",
    )
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.last_name == "Doe"
    assert contact.email == "jane.doe@acme.com"
    assert contact.phone == "555-1234"
    assert contact.alternate_phone == "555-5678"
    assert contact.job_title == "VP Sales"
    assert contact.linkedin_url == "linkedin.com/in/janedoe"
    assert contact.created_at is not None
    assert contact.updated_at is not None


async def test_contact_persists_with_only_required_fields(db_session: AsyncSession):
    contact = Contact(first_name="Minimal", email="minimal@example.com")
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.last_name is None
    assert contact.phone is None
    assert contact.alternate_phone is None
    assert contact.job_title is None
    assert contact.linkedin_url is None


async def test_first_name_is_required(db_session: AsyncSession):
    db_session.add(Contact(first_name=None, email="first-name-required@example.com"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_email_is_required(db_session: AsyncSession):
    db_session.add(Contact(first_name="No Email", email=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_email_must_be_unique(db_session: AsyncSession):
    db_session.add(Contact(first_name="A", email="dupe-contact@example.com"))
    await db_session.flush()

    db_session.add(Contact(first_name="B", email="dupe-contact@example.com"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
