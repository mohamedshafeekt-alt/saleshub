"""Contact business logic: plain CRUD on the standalone Contact entity.

Contact has no owner_id and, as of the contact_accounts refactor, no single
owning Account either (a Contact can be linked to more than one Account) --
there is no coherent single account to gate access against anymore, so these
operations are role-gated only (via the router's require_role dependency),
not ownership-scoped. Account-scoped contact creation/update (with the
is_primary flag) lives in contact_account_service.py instead.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate


class ContactNotFoundError(Exception):
    """Raised when a contact id does not exist."""


async def create_contact(db: AsyncSession, data: ContactCreate) -> Contact:
    contact = Contact(**data.model_dump())
    db.add(contact)
    await db.flush()
    return contact


async def _get_contact_or_raise(db: AsyncSession, contact_id: int) -> Contact:
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")
    return contact


async def get_contact(db: AsyncSession, contact_id: int) -> Contact:
    return await _get_contact_or_raise(db, contact_id)


async def update_contact(db: AsyncSession, contact_id: int, data: ContactUpdate) -> Contact:
    contact = await _get_contact_or_raise(db, contact_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    await db.flush()
    return contact


async def delete_contact(db: AsyncSession, contact_id: int) -> None:
    contact = await _get_contact_or_raise(db, contact_id)
    await db.delete(contact)
    await db.flush()
