"""Contact <-> Account association business logic: the "Add Contact" / "Edit
Contact" modal on the Account Detail page, which creates/updates a Contact
*and* its ContactAccount link (with is_primary) for one account in a single
call. Reuses account_service.get_account for the account existence/ownership
check -- this module depends on account_service, not the other way around.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.user import User
from app.schemas.contact_account import AccountContactUpsert
from app.services.account_service import (
    PrimaryContactAlreadyExistsError,
    account_has_primary_contact,
    get_account,
)


class ContactNotFoundError(Exception):
    """Raised when a contact id does not exist."""


async def create_account_contact(
    db: AsyncSession, account_id: int, data: AccountContactUpsert, requester: User
) -> tuple[Contact, ContactAccount]:
    """data.contact_id must be None -- the dispatch on that field happens in
    the route, same as LeadUpsert. first_name is guaranteed non-None here by
    AccountContactUpsert's validator."""
    await get_account(db, account_id, requester)  # existence + ownership check

    is_primary = data.is_primary or False
    if is_primary and await account_has_primary_contact(db, account_id):
        raise PrimaryContactAlreadyExistsError(f"Account {account_id} already has a primary contact")

    contact = Contact(
        first_name=data.first_name,
        last_name=data.last_name,
        job_title=data.job_title,
        linkedin_url=data.linkedin_url,
        email=data.email,
        phone=data.phone,
        alternate_phone=data.alternate_phone,
    )
    db.add(contact)
    await db.flush()

    contact_account = ContactAccount(contact_id=contact.id, account_id=account_id, is_primary=is_primary)
    db.add(contact_account)
    await db.flush()

    return contact, contact_account


async def _get_contact_or_raise(db: AsyncSession, contact_id: int) -> Contact:
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")
    return contact


async def _get_contact_account_or_none(
    db: AsyncSession, account_id: int, contact_id: int
) -> ContactAccount | None:
    result = await db.execute(
        select(ContactAccount).where(
            ContactAccount.account_id == account_id, ContactAccount.contact_id == contact_id
        )
    )
    return result.scalar_one_or_none()


async def update_account_contact(
    db: AsyncSession, account_id: int, contact_id: int, data: AccountContactUpsert, requester: User
) -> tuple[Contact, ContactAccount]:
    """Updates the Contact's fields (only those the caller actually sent)
    and/or its is_primary flag for this account. If (account_id, contact_id)
    has no existing link, one is created -- this is how an already-existing
    contact gets associated with another account."""
    await get_account(db, account_id, requester)
    contact = await _get_contact_or_raise(db, contact_id)

    for field, value in data.model_dump(exclude_unset=True, exclude={"contact_id", "is_primary"}).items():
        setattr(contact, field, value)

    contact_account = await _get_contact_account_or_none(db, account_id, contact_id)
    was_already_primary = contact_account is not None and contact_account.is_primary
    is_primary = data.is_primary if data.is_primary is not None else was_already_primary

    if is_primary and not was_already_primary and await account_has_primary_contact(db, account_id):
        raise PrimaryContactAlreadyExistsError(f"Account {account_id} already has a primary contact")

    if contact_account is None:
        contact_account = ContactAccount(contact_id=contact_id, account_id=account_id, is_primary=is_primary)
        db.add(contact_account)
    else:
        contact_account.is_primary = is_primary

    await db.flush()
    return contact, contact_account


async def list_account_contacts(
    db: AsyncSession, account_id: int, requester: User, *, limit: int = 20, offset: int = 0
) -> tuple[list[tuple[Contact, bool]], int]:
    await get_account(db, account_id, requester)

    total = (
        await db.execute(
            select(func.count(ContactAccount.id)).where(ContactAccount.account_id == account_id)
        )
    ).scalar_one()

    query = (
        select(Contact, ContactAccount.is_primary)
        .join(ContactAccount, ContactAccount.contact_id == Contact.id)
        .where(ContactAccount.account_id == account_id)
        .order_by(Contact.created_at)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(query)).all()
    return [(contact, is_primary) for contact, is_primary in rows], total
