"""Contact business logic: plain CRUD on the standalone Contact entity, plus
scoped listing and the Contact Overview screen.

Contact has no owner_id and, as of the contact_accounts refactor, no single
owning Account either (a Contact can be linked to more than one Account) --
there is no coherent single account to gate access against anymore. Without
contacts.view_all, a requester only sees a Contact that's linked (via
ContactAccount or DealContact) to an Account/Deal they own, or -- for a
Contact with no links at all yet -- one they created themselves (see
_contact_visibility_filter). Mirrors deal_service/account_service's
owner_id-vs-*_VIEW_ALL pattern, adapted for a many-owner entity.
Account-scoped contact creation/update (with the is_primary flag) lives in
contact_account_service.py instead.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permission_codes import CONTACTS_VIEW_ALL
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.deal import Deal
from app.models.deal_contact import DealContact
from app.models.enums import AuditAction, LeadTier
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.audit_service import log_audit

_OVERVIEW_EAGER_LOAD = (
    selectinload(Contact.contact_accounts)
    .selectinload(ContactAccount.account)
    .selectinload(Account.owner),
)


class ContactNotFoundError(Exception):
    """Raised when a contact id does not exist."""


class ContactAccessForbiddenError(Exception):
    """Raised when a requester without contacts.view_all isn't linked to
    this contact's Account/Deal (and didn't create it, if it's unlinked)."""


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


async def create_contact(db: AsyncSession, data: ContactCreate, requester: User) -> Contact:
    contact = Contact(**data.model_dump())
    db.add(contact)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateContactEmailError(f"Email already exists: {data.email}") from exc
        raise

    name = f"{contact.first_name} {contact.last_name or ''}".strip()
    await log_audit(
        db, table_name="contacts", record_id=contact.id, action=AuditAction.CREATED,
        actor_id=requester.id, description=f"Contact '{name}' created",
    )
    return contact


def _contact_visibility_filter(requester: User) -> Any:
    """SQL predicate: true iff `requester` may see this Contact without
    contacts.view_all (callers check that permission first and skip this
    filter entirely if it's present). True when linked via ContactAccount to
    an Account the requester owns, linked via DealContact to a Deal the
    requester owns, or -- for a Contact with no links at all -- when the
    requester is who created it (the audit log's CREATED row, same signal
    get_contact_overview surfaces as created_by)."""
    owns_via_account = (
        select(ContactAccount.id)
        .join(Account, ContactAccount.account_id == Account.id)
        .where(ContactAccount.contact_id == Contact.id, Account.owner_id == requester.id)
        .exists()
    )
    owns_via_deal = (
        select(DealContact.id)
        .join(Deal, DealContact.deal_id == Deal.id)
        .where(DealContact.contact_id == Contact.id, Deal.owner_id == requester.id)
        .exists()
    )
    has_any_link = or_(
        select(ContactAccount.id).where(ContactAccount.contact_id == Contact.id).exists(),
        select(DealContact.id).where(DealContact.contact_id == Contact.id).exists(),
    )
    created_by_requester = (
        select(AuditLog.id)
        .where(
            AuditLog.table_name == "contacts",
            AuditLog.record_id == Contact.id,
            AuditLog.action == AuditAction.CREATED.value,
            AuditLog.actor_id == requester.id,
        )
        .exists()
    )
    return or_(owns_via_account, owns_via_deal, and_(~has_any_link, created_by_requester))


async def _get_contact_or_raise(db: AsyncSession, contact_id: int) -> Contact:
    """Existence check only -- no visibility scoping. Used internally where
    the caller already has its own authorization (e.g. deal_service attaching
    an existing contact as a stakeholder on a deal it's already checked
    access to) and just needs to know the id is real. Contact-facing reads
    should go through get_contact instead."""
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")
    return contact


async def contact_exists(db: AsyncSession, contact_id: int) -> Contact:
    """Public existence-only lookup for other services -- see
    _get_contact_or_raise's docstring for why this skips visibility scoping."""
    return await _get_contact_or_raise(db, contact_id)


async def _assert_contact_visible(db: AsyncSession, contact: Contact, requester: User) -> None:
    if CONTACTS_VIEW_ALL in requester.permission_codes:
        return
    visible = (
        await db.execute(select(Contact.id).where(Contact.id == contact.id, _contact_visibility_filter(requester)))
    ).first()
    if visible is None:
        raise ContactAccessForbiddenError(f"Not permitted to access contact: {contact.id}")


async def get_contact(db: AsyncSession, contact_id: int, requester: User) -> Contact:
    contact = await _get_contact_or_raise(db, contact_id)
    await _assert_contact_visible(db, contact, requester)
    return contact


async def update_contact(db: AsyncSession, contact_id: int, data: ContactUpdate, requester: User) -> Contact:
    contact = await get_contact(db, contact_id, requester)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateContactEmailError(f"Email already exists: {data.email}") from exc
        raise

    name = f"{contact.first_name} {contact.last_name or ''}".strip()
    await log_audit(
        db, table_name="contacts", record_id=contact.id, action=AuditAction.UPDATED,
        actor_id=requester.id, description=f"Contact '{name}' updated",
    )
    return contact


async def delete_contact(db: AsyncSession, contact_id: int, requester: User) -> None:
    contact = await get_contact(db, contact_id, requester)
    contact_id_ = contact.id
    name = f"{contact.first_name} {contact.last_name or ''}".strip()
    await db.delete(contact)
    await db.flush()
    await log_audit(
        db, table_name="contacts", record_id=contact_id_, action=AuditAction.DELETED,
        actor_id=requester.id, description=f"Contact '{name}' deleted",
    )


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
    db: AsyncSession, contact_id: int, requester: User
) -> tuple[Contact, ContactAccount | None, int, str | None]:
    """Contact fields + its representative Account link (see
    _primary_account_link) + how many Deals it's linked to via DealContact +
    the creator's display name (from the audit log's CREATED row for this
    contact, since Contact has no created_by column of its own). null if no
    such audit row exists. tags/about/last_activity/task_count/log_count
    have no backing model yet -- the route fills those with null, same
    pattern as AccountOverviewRead.last_activity/next_step/total_arr."""
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id).options(*_OVERVIEW_EAGER_LOAD)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise ContactNotFoundError(f"Contact not found: {contact_id}")
    await _assert_contact_visible(db, contact, requester)

    account_link = _primary_account_link(contact)
    deal_count = (
        await db.execute(select(func.count(DealContact.id)).where(DealContact.contact_id == contact_id))
    ).scalar_one()

    created_by_log = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.table_name == "contacts",
                AuditLog.record_id == contact_id,
                AuditLog.action == AuditAction.CREATED.value,
            )
            .options(selectinload(AuditLog.actor))
            .order_by(AuditLog.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    created_by_name = (
        " ".join(filter(None, [created_by_log.actor.first_name, created_by_log.actor.last_name]))
        if created_by_log
        else None
    )

    return contact, account_link, deal_count, created_by_name


async def list_contacts(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    tier: LeadTier | None = None,
    is_primary: bool | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Contact, ContactAccount | None]], int]:
    """Contacts List screen: owner_id/account_id/tier/is_primary match if ANY
    of a contact's linked Accounts satisfies them (a Contact can be linked to
    more than one Account) -- e.g. owner_id matches contacts with at least
    one link to an Account owned by that user, regardless of which linked
    Account ends up as the display representative below. search matches
    first/last name or email. date_from/date_to filter on the Contact row's
    own created_at (not the link's). Each result pairs the Contact with its
    single representative Account link (see _primary_account_link) for
    display.

    Without contacts.view_all, results are forced to contacts visible to
    `requester` (see _contact_visibility_filter) regardless of owner_id --
    same pattern as deal_service._deal_filters."""
    filters: list[Any] = []
    if CONTACTS_VIEW_ALL not in requester.permission_codes:
        filters.append(_contact_visibility_filter(requester))
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.email.ilike(pattern),
            )
        )
    if date_from is not None:
        filters.append(Contact.created_at >= date_from)
    if date_to is not None:
        # Inclusive -- see account_service.list_accounts for why.
        filters.append(Contact.created_at < date_to + timedelta(days=1))

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


async def export_contacts(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    tier: LeadTier | None = None,
    is_primary: bool | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """All contacts matching list_contacts's filters (same requester
    scoping). No dedicated no-pagination query -- reuses list_contacts with
    a large limit.
    # ponytail: large-limit reuse instead of a bespoke unpaginated query;
    # switch to a real no-pagination query if contact counts get large.
    """
    items, _total = await list_contacts(
        db,
        requester=requester,
        owner_id=owner_id,
        account_id=account_id,
        tier=tier,
        is_primary=is_primary,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=1_000_000,
        offset=0,
    )
    rows = []
    for contact, link in items:
        account = link.account if link else None
        rows.append(
            {
                "name": " ".join(filter(None, [contact.first_name, contact.last_name])),
                "email": contact.email,
                "phone": contact.phone,
                "job_title": contact.job_title,
                "account": account.company if account else None,
                "owner": account.owner_name if account else None,
                "tier": account.tier.value if account and account.tier else None,
                "is_primary": link.is_primary if link else False,
            }
        )
    return rows
