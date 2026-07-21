"""app.models.contact: Contact ORM model construction + constraints.

Covers: construction with all fields persists and round-trips; created_at/
updated_at present via Base inheritance; first_name and account_id are
NOT NULL (required).
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
    from app.models.contact import Contact

    owner = await _make_owner(db_session)
    account = await _make_account(db_session, owner.id)

    contact = Contact(
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@acme.com",
        phone="555-1234",
        job_title="VP Sales",
        account_id=account.id,
    )
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.last_name == "Doe"
    assert contact.email == "jane.doe@acme.com"
    assert contact.phone == "555-1234"
    assert contact.job_title == "VP Sales"
    assert contact.account_id == account.id
    assert contact.created_at is not None
    assert contact.updated_at is not None


async def test_contact_persists_with_only_required_fields(db_session: AsyncSession):
    from app.models.contact import Contact

    owner = await _make_owner(db_session, email="owner2-contact@example.com")
    account = await _make_account(db_session, owner.id, company="Minimal Co")

    contact = Contact(first_name="Minimal", account_id=account.id)
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.last_name is None
    assert contact.email is None
    assert contact.phone is None
    assert contact.job_title is None


async def test_first_name_is_required(db_session: AsyncSession):
    from app.models.contact import Contact

    owner = await _make_owner(db_session, email="owner3-contact@example.com")
    account = await _make_account(db_session, owner.id, company="No First Name Co")

    db_session.add(Contact(first_name=None, account_id=account.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_account_id_is_required(db_session: AsyncSession):
    from app.models.contact import Contact

    db_session.add(Contact(first_name="No Account", account_id=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
