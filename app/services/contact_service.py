"""Contact business logic: plain CRUD on the standalone Contact entity, plus
role-gated (not ownership-scoped) listing and the Contact Overview screen.

Contact has no owner_id and, as of the contact_accounts refactor, no single
owning Account either (a Contact can be linked to more than one Account) --
there is no coherent single account to gate access against anymore, so these
operations are role-gated only (via the router's require_role dependency),
not ownership-scoped. Account-scoped contact creation/update (with the
is_primary flag) lives in contact_account_service.py instead.
"""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.deal_contact import DealContact
from app.models.enums import LeadTier
from app.schemas.contact import ContactCreate, ContactUpdate

_OVERVIEW_EAGER_LOAD = (selectinload(Contact.contact_accounts).selectinload(ContactAccount.account),)


class ContactNotFoundError(Exception):
    """Raised when a contact id does not exist."""


class DuplicateContactEmailError(Exception):
    """Raised when a Contact with this email already exists.

    Email is Contact's unique identifying field across the whole table (not
    scoped to any one account, since a Contact isn't owned by a single
    account) -- a different name with an already-used email still counts as
    a duplicate. Mirrors Lead.email's unique-index + IntegrityError-catch
    pattern in lead_service.py.
    """


def _is_duplicate_email_violation(exc: IntegrityError) -> bool:
    return "ix_contacts_email" in str(exc.orig)


async def create_contact(db: AsyncSession, data: ContactCreate) -> Contact:
    contact = Contact(**data.model_dump())
    db.add(contact)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateContactEmailError(f"Email already exists: {data.email}") from exc
        raise
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

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateContactEmailError(f"Email already exists: {data.email}") from exc
        raise
    return contact


async def delete_contact(db: AsyncSession, contact_id: int) -> None:
    contact = await _get_contact_or_raise(db, contact_id)
    await db.delete(contact)
    await db.flush()


def _primary_account_link(contact: Contact) -> ContactAccount | None:
    """The contact's oldest ContactAccount row marked primary, or its oldest
    link overall if none is primary -- a Contact can be linked to more than
    one Account, and is_primary is scoped per-account (not per-contact), so
    more than one link could claim to be primary. contact.contact_accounts
    is already ordered oldest-first (see Contact.contact_accounts)."""
    for link in contact.contact_accounts:
        if link.is_primary:
            return link
    return contact.contact_accounts[0] if contact.contact_accounts else None


async def get_contact_overview(
    db: AsyncSession, contact_id: int
) -> tuple[Contact, ContactAccount | None, int]:
    """Contact fields + its representative Account link (see
    _primary_account_link) + how many Deals it's linked to via DealContact.
    tags/about/last_activity/task_count/log_count have no backing model yet
    -- the route fills those with null, same pattern as
    AccountOverviewRead.last_activity/next_step/total_arr."""
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id).options(*_OVERVIEW_EAGER_LOAD)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")

    account_link = _primary_account_link(contact)
    deal_count = (
        await db.execute(select(func.count(DealContact.id)).where(DealContact.contact_id == contact_id))
    ).scalar_one()

    return contact, account_link, deal_count


async def list_contacts(
    db: AsyncSession,
    *,
    owner_id: int | None = None,
    account_id: int | None = None,
    tier: LeadTier | None = None,
    is_primary: bool | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Contact, ContactAccount | None]], int]:
    """Contacts List screen: owner_id/account_id/tier/is_primary match if ANY
    of a contact's linked Accounts satisfies them (a Contact can be linked to
    more than one Account) -- e.g. owner_id matches contacts with at least
    one link to an Account owned by that user, regardless of which linked
    Account ends up as the display representative below. search matches
    first/last name or email. Each result pairs the Contact with its single
    representative Account link (see _primary_account_link) for display."""
    filters: list[Any] = []
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.email.ilike(pattern),
            )
        )

    if owner_id is not None or account_id is not None or tier is not None or is_primary is not None:
        link_query = select(ContactAccount.id).where(ContactAccount.contact_id == Contact.id)
        if owner_id is not None or tier is not None:
            link_query = link_query.join(Account, ContactAccount.account_id == Account.id)
        if owner_id is not None:
            link_query = link_query.where(Account.owner_id == owner_id)
        if account_id is not None:
            link_query = link_query.where(ContactAccount.account_id == account_id)
        if tier is not None:
            link_query = link_query.where(Account.tier == tier)
        if is_primary is not None:
            link_query = link_query.where(ContactAccount.is_primary == is_primary)
        filters.append(link_query.exists())

    count_query = select(func.count(Contact.id)).where(*filters)
    items_query = (
        select(Contact)
        .where(*filters)
        .options(*_OVERVIEW_EAGER_LOAD)
        .order_by(Contact.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    total = (await db.execute(count_query)).scalar_one()
    contacts = list((await db.execute(items_query)).scalars().all())

    items = [(contact, _primary_account_link(contact)) for contact in contacts]
    return items, total
