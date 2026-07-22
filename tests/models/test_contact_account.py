"""app.models.contact_account: ContactAccount ORM model construction +
constraints.

Covers: construction persists and round-trips (including default
is_primary=False); contact_id/account_id are NOT NULL; a (contact_id,
account_id) pair can't repeat (uq_contact_accounts_contact_account); at
most one is_primary=True row per account_id (the partial unique index
uq_contact_accounts_one_primary_per_account) -- a second contact for the
same account can still be inserted as long as it isn't also primary.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.enums import LeadTier
from app.models.user import User, UserRole


async def _make_owner(db_session: AsyncSession, email: str = "owner-ca@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role=UserRole.SALES_REP)
    db_session.add(owner)
    await db_session.flush()
    return owner


async def _make_account(db_session: AsyncSession, owner_id: int, company: str = "Acme Corp") -> Account:
    account = Account(company=company, tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


async def _make_contact(db_session: AsyncSession, first_name: str = "Jane") -> Contact:
    contact = Contact(first_name=first_name)
    db_session.add(contact)
    await db_session.flush()
    return contact


async def test_contact_account_persists_and_defaults_is_primary_false(db_session: AsyncSession):
    owner = await _make_owner(db_session)
    account = await _make_account(db_session, owner.id)
    contact = await _make_contact(db_session)

    link = ContactAccount(contact_id=contact.id, account_id=account.id)
    db_session.add(link)
    await db_session.flush()
    await db_session.refresh(link)

    assert link.id is not None
    assert link.is_primary is False


async def test_contact_id_is_required(db_session: AsyncSession):
    owner = await _make_owner(db_session, email="owner-ca-2@example.com")
    account = await _make_account(db_session, owner.id, company="No Contact Co")

    db_session.add(ContactAccount(contact_id=None, account_id=account.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_account_id_is_required(db_session: AsyncSession):
    contact = await _make_contact(db_session, first_name="No Account")

    db_session.add(ContactAccount(contact_id=contact.id, account_id=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_same_contact_account_pair_cannot_repeat(db_session: AsyncSession):
    owner = await _make_owner(db_session, email="owner-ca-3@example.com")
    account = await _make_account(db_session, owner.id, company="Dup Pair Co")
    contact = await _make_contact(db_session, first_name="Dup Pair")

    db_session.add(ContactAccount(contact_id=contact.id, account_id=account.id))
    await db_session.flush()

    db_session.add(ContactAccount(contact_id=contact.id, account_id=account.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_contact_can_link_to_more_than_one_account(db_session: AsyncSession):
    owner = await _make_owner(db_session, email="owner-ca-4@example.com")
    account_a = await _make_account(db_session, owner.id, company="Multi Co A")
    account_b = await _make_account(db_session, owner.id, company="Multi Co B")
    contact = await _make_contact(db_session, first_name="Multi Account")

    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_a.id))
    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_b.id))
    await db_session.flush()

    assert len(contact.contact_accounts) == 2


async def test_only_one_primary_contact_per_account(db_session: AsyncSession):
    owner = await _make_owner(db_session, email="owner-ca-5@example.com")
    account = await _make_account(db_session, owner.id, company="Primary Conflict Co")
    contact_a = await _make_contact(db_session, first_name="First Primary")
    contact_b = await _make_contact(db_session, first_name="Second Primary")

    db_session.add(ContactAccount(contact_id=contact_a.id, account_id=account.id, is_primary=True))
    await db_session.flush()

    db_session.add(ContactAccount(contact_id=contact_b.id, account_id=account.id, is_primary=True))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_second_non_primary_contact_for_same_account_is_allowed(db_session: AsyncSession):
    owner = await _make_owner(db_session, email="owner-ca-6@example.com")
    account = await _make_account(db_session, owner.id, company="Second Contact Co")
    contact_a = await _make_contact(db_session, first_name="Primary")
    contact_b = await _make_contact(db_session, first_name="Not Primary")

    db_session.add(ContactAccount(contact_id=contact_a.id, account_id=account.id, is_primary=True))
    await db_session.flush()

    db_session.add(ContactAccount(contact_id=contact_b.id, account_id=account.id, is_primary=False))
    await db_session.flush()  # should not raise

    assert len(account.contact_accounts) == 2
