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

from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.contact_service import (
    ContactNotFoundError,
    DuplicateContactEmailError,
    create_contact,
    delete_contact,
    get_contact,
    update_contact,
)


async def test_create_contact_succeeds(db_session: AsyncSession):
    data = ContactCreate(first_name="Jane", last_name="Doe", email="jane@example.com")

    contact = await create_contact(db_session, data)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.last_name == "Doe"
    assert contact.email == "jane@example.com"


async def test_create_contact_with_linkedin_and_alternate_phone(db_session: AsyncSession):
    data = ContactCreate(
        first_name="Jane",
        linkedin_url="https://linkedin.com/in/jane",
        phone="555-0001",
        alternate_phone="555-0002",
    )

    contact = await create_contact(db_session, data)

    assert contact.linkedin_url == "https://linkedin.com/in/jane"
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


async def test_create_contact_duplicate_email_raises(db_session: AsyncSession):
    await create_contact(db_session, ContactCreate(first_name="First", email="dup-contact@example.com"))

    with pytest.raises(DuplicateContactEmailError):
        await create_contact(db_session, ContactCreate(first_name="Second", email="dup-contact@example.com"))


async def test_update_contact_duplicate_email_raises(db_session: AsyncSession):
    await create_contact(db_session, ContactCreate(first_name="First", email="taken@example.com"))
    other = await create_contact(db_session, ContactCreate(first_name="Second", email="free@example.com"))

    with pytest.raises(DuplicateContactEmailError):
        await update_contact(db_session, contact_id=other.id, data=ContactUpdate(email="taken@example.com"))


async def test_delete_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await delete_contact(db_session, contact_id=999_999)


async def test_delete_contact_removes_the_row(db_session: AsyncSession):
    created = await create_contact(db_session, ContactCreate(first_name="To Delete"))
    contact_id = created.id

    await delete_contact(db_session, contact_id=contact_id)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=contact_id)
