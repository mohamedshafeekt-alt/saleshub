"""Contact business logic: ownership-checked CRUD scoped via the parent Account.

Contact has no owner_id of its own — access control is delegated entirely to
the parent Account via account_service.get_account, whose AccountNotFoundError
/ AccountAccessForbiddenError propagate unchanged (mirrors how
account_service.convert_lead_to_account reuses lead_service.get_lead's
exceptions without wrapping them).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.account_service import get_account


class ContactNotFoundError(Exception):
    """Raised when a contact id does not exist."""


async def create_contact(db: AsyncSession, data: ContactCreate, requester: User) -> Contact:
    await get_account(db, data.account_id, requester)

    contact = Contact(**data.model_dump())
    db.add(contact)
    await db.flush()
    return contact


async def list_contacts_for_account(db: AsyncSession, account_id: int, requester: User) -> list[Contact]:
    await get_account(db, account_id, requester)

    query = select(Contact).where(Contact.account_id == account_id).order_by(Contact.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_contact_or_raise(db: AsyncSession, contact_id: int, requester: User) -> Contact:
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")
    await get_account(db, contact.account_id, requester)
    return contact


async def get_contact(db: AsyncSession, contact_id: int, requester: User) -> Contact:
    return await _get_contact_or_raise(db, contact_id, requester)


async def update_contact(
    db: AsyncSession, contact_id: int, data: ContactUpdate, requester: User
) -> Contact:
    contact = await _get_contact_or_raise(db, contact_id, requester)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    await db.flush()
    return contact


async def delete_contact(db: AsyncSession, contact_id: int, requester: User) -> None:
    contact = await _get_contact_or_raise(db, contact_id, requester)
    await db.delete(contact)
    await db.flush()
