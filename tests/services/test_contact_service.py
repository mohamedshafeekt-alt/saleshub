"""app.services.contact_service: plain CRUD on the standalone Contact entity.

Contact has no owner_id and no single owning account (see the module
docstring on contact_service.py) -- these operations are role-gated only at
the router level, not ownership-scoped here. Covers: create/get/update/delete
succeed regardless of who's asking; get/update/delete raise
ContactNotFoundError for a missing id; update_contact applies only fields set
(partial update). Account-scoped creation/update (with is_primary) is covered
in tests/services/test_contact_account_service.py instead.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User
from tests.support.roles import UserRole, role_id_for
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.contact_service import (
    ContactNotFoundError,
    create_contact,
    delete_contact,
    get_contact,
    update_contact,
)


async def test_create_contact_succeeds(db_session: AsyncSession):
    data = ContactCreate(first_name="Jane", last_name="Doe", email="jane@example.com")
async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def _make_account(db_session: AsyncSession, owner_id: int, company: str = "Acme Corp"):
    from app.models.account import Account

    account = Account(company=company, tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


# --- create_contact ----------------------------------------------------------


async def test_create_contact_raises_not_found_for_nonexistent_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "creator-contact@example.com", UserRole.SALES_MANAGER)

    contact = await create_contact(db_session, data)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.last_name == "Doe"
    assert contact.email == "jane@example.com"


async def test_create_contact_with_linkedin_and_alternate_phone(db_session: AsyncSession):
    data = ContactCreate(
        first_name="Jane",
        linkedin_url="linkedin.com/in/jane",
        phone="555-0001",
        alternate_phone="555-0002",
    )

    contact = await create_contact(db_session, data)

    assert contact.linkedin_url == "linkedin.com/in/jane"
    assert contact.phone == "555-0001"
    assert contact.alternate_phone == "555-0002"


async def test_get_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=999_999)


async def test_get_contact_succeeds(db_session: AsyncSession):
    created = await create_contact(db_session, ContactCreate(first_name="Getable"))

    fetched = await get_contact(db_session, contact_id=created.id)

    assert fetched.id == created.id


async def test_update_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await update_contact(db_session, contact_id=999_999, data=ContactUpdate(first_name="New"))


async def test_update_contact_applies_partial_changes(db_session: AsyncSession):
    created = await create_contact(
        db_session, ContactCreate(first_name="Old", last_name="Name", job_title="Old Title")
    )

    updated = await update_contact(db_session, contact_id=created.id, data=ContactUpdate(first_name="New"))

    assert updated.first_name == "New"
    assert updated.last_name == "Name"  # untouched field preserved
    assert updated.job_title == "Old Title"  # untouched field preserved


async def test_delete_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await delete_contact(db_session, contact_id=999_999)


async def test_delete_contact_removes_the_row(db_session: AsyncSession):
    created = await create_contact(db_session, ContactCreate(first_name="To Delete"))
    contact_id = created.id

    await delete_contact(db_session, contact_id=contact_id)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=contact_id)
