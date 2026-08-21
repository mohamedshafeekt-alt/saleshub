"""Account business logic: role-scoped listing/search, ownership-checked
get/update/delete, and Lead -> Account conversion."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permission_codes import ACCOUNTS_NOTIFY_ON_CREATE, ACCOUNTS_VIEW_ALL
from app.models.account import Account
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.deal import Deal
from app.models.deal_stage import DealStage
from app.models.enums import AuditAction, LeadTier, NotificationType
from app.models.lead_contact import LeadContact
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import role_permissions
from app.models.user import User
from app.schemas.account import AccountContactInput, AccountCreate, AccountUpdate
from app.services.audit_service import log_audit
from app.services.contact_service import DuplicateContactEmailError
from app.services.lead_service import get_lead
from app.services.notification_service import create_notification

_EAGER_LOAD_OPTIONS = (
    selectinload(Account.owner),
    selectinload(Account.contact_accounts).selectinload(ContactAccount.contact),
    selectinload(Account.deals),
)

_CLOSED_STAGE_NAMES = {"Closed Won", "Closed Lost"}


class AccountNotFoundError(Exception):
    """Raised when an account id does not exist."""


class AccountAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access an account they don't own."""


class LeadAlreadyConvertedError(Exception):
    """Raised when attempting to convert a lead that was already converted."""


class LeadMissingFieldsForConversionError(Exception):
    """Raised when a lead has no tier and/or owner and none was supplied at conversion time."""


class PrimaryContactAlreadyExistsError(Exception):
    """Raised when trying to mark a contact primary for an account that already has one.

    Deliberately NOT auto-demoting the existing primary contact -- the
    caller must explicitly unset the old one first.
    """


async def account_has_primary_contact(db: AsyncSession, account_id: int) -> bool:
    result = await db.execute(
        select(ContactAccount.id).where(
            ContactAccount.account_id == account_id, ContactAccount.is_primary.is_(True)
        )
    )
    return result.scalar_one_or_none() is not None


async def _add_contacts(db: AsyncSession, account_id: int, contacts: list[AccountContactInput]) -> None:
    """contacts[0]'s first_name/last_name is required (enforced by the
    AccountCreate/AccountUpdate validator) and back-fills any later contact
    that omits its own, since Contact.first_name is NOT NULL.

    Checked up front rather than relying on the DB's partial-unique-index /
    unique-email-index + IntegrityError rollback: this runs after the
    Account itself may already be flushed in the same transaction
    (create_account), and rolling back on conflict would undo that too, not
    just this call's own inserts.
    """
    if not contacts:
        return

    if sum(contact.is_primary for contact in contacts) > 1:
        raise PrimaryContactAlreadyExistsError(
            "Only one contact per request can be marked primary"
        )
    if any(contact.is_primary for contact in contacts) and await account_has_primary_contact(
        db, account_id
    ):
        raise PrimaryContactAlreadyExistsError(f"Account {account_id} already has a primary contact")

    emails = [contact.email for contact in contacts]
    if len(emails) != len(set(emails)):
        raise DuplicateContactEmailError("Duplicate email within the same request")
    result = await db.execute(select(Contact.email).where(Contact.email.in_(emails)))
    existing_email = result.scalar_one_or_none()
    if existing_email is not None:
        raise DuplicateContactEmailError(f"Email already exists: {existing_email}")

    first_name = contacts[0].first_name
    last_name = contacts[0].last_name

    new_contacts = []
    for contact in contacts:
        row = Contact(
            first_name=contact.first_name or first_name,
            last_name=contact.last_name if contact.first_name else last_name,
            email=contact.email,
            phone=contact.phone,
            job_title=contact.job_title,
        )
        db.add(row)
        new_contacts.append((row, contact.is_primary))

    await db.flush()  # assigns ids to the new Contact rows

    for contact_row, is_primary in new_contacts:
        db.add(ContactAccount(contact_id=contact_row.id, account_id=account_id, is_primary=is_primary))


async def create_account(db: AsyncSession, data: AccountCreate, requester: User) -> Account:
    fields = data.model_dump(exclude={"contacts"})
    fields["owner_id"] = fields["owner_id"] or requester.id
    account = Account(**fields)
    db.add(account)
    await db.flush()

    await _add_contacts(db, account.id, data.contacts)
    if data.contacts:
        await db.flush()

    await db.refresh(account, attribute_names=["owner", "contact_accounts", "deals"])
    await log_audit(
        db, table_name="accounts", record_id=account.id, action=AuditAction.CREATED,
        actor_id=requester.id, description=f"Account '{account.company}' created",
    )

    result = await db.execute(
        select(User)
        .join(Role, User.role_id == Role.id)
        .join(role_permissions, Role.id == role_permissions.c.role_id)
        .join(Permission, role_permissions.c.permission_id == Permission.id)
        .where(
            Permission.code == ACCOUNTS_NOTIFY_ON_CREATE,
            User.is_active.is_(True),
            User.is_delete.is_(False),
        )
    )
    for notifiable in result.scalars():
        await create_notification(
            db,
            recipient_id=notifiable.id,
            type=NotificationType.ACCOUNT_CREATED,
            title="New account created",
            body=f"{account.company} was just created.",
            actor_id=requester.id,
            entity_type="account",
            entity_id=account.id,
        )

    return account


async def list_accounts(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    tier: LeadTier | None = None,
    industry: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Account], int]:
    if ACCOUNTS_VIEW_ALL not in requester.permission_codes:
        owner_id = requester.id

    filters = []
    if owner_id is not None:
        filters.append(Account.owner_id == owner_id)
    if tier is not None:
        filters.append(Account.tier == tier)
    if industry is not None:
        filters.append(Account.industry == industry)
    if date_from is not None:
        filters.append(Account.created_at >= date_from)
    if date_to is not None:
        # Inclusive, matching the dashboard's `num_accounts` tile
        # (dashboard_service._count_accounts) -- it used to be exclusive,
        # silently dropping accounts created on the requested end date and
        # undercounting against the tile for the same range.
        filters.append(Account.created_at < date_to + timedelta(days=1))
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                Account.company.ilike(pattern),
                Account.domain.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )

    count_query = select(func.count(Account.id))
    items_query = select(Account).options(*_EAGER_LOAD_OPTIONS)
    if search is not None:
        count_query = count_query.join(User, Account.owner_id == User.id)
        items_query = items_query.join(User, Account.owner_id == User.id)

    count_query = count_query.where(*filters)
    items_query = items_query.where(*filters).order_by(Account.created_at.desc()).limit(limit).offset(offset)

    total = (await db.execute(count_query)).scalar_one()
    items = list((await db.execute(items_query)).scalars().all())
    return items, total


async def export_accounts(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    tier: LeadTier | None = None,
    industry: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """All accounts matching the requester's role-scoping (same rule as
    list_accounts). No dedicated no-pagination query -- reuses
    list_accounts with a large limit.
    # ponytail: large-limit reuse instead of a bespoke unpaginated query;
    # switch to a real no-pagination query if account counts get large.
    """
    accounts, _total = await list_accounts(
        db,
        requester=requester,
        owner_id=owner_id,
        tier=tier,
        industry=industry,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=1_000_000,
        offset=0,
    )
    return [
        {
            "company": account.company,
            "domain": account.domain,
            "tier": account.tier.value if account.tier else None,
            "industry": account.industry,
            "city": account.city,
            "owner": account.owner_name,
        }
        for account in accounts
    ]


async def _get_account_or_raise(db: AsyncSession, account_id: int, requester: User) -> Account:
    result = await db.execute(
        select(Account).where(Account.id == account_id).options(*_EAGER_LOAD_OPTIONS)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError(f"Account not found: {account_id}")
    if ACCOUNTS_VIEW_ALL not in requester.permission_codes and account.owner_id != requester.id:
        raise AccountAccessForbiddenError(f"Not permitted to access account: {account_id}")
    return account


async def get_account(db: AsyncSession, account_id: int, requester: User) -> Account:
    return await _get_account_or_raise(db, account_id, requester)


async def update_account(db: AsyncSession, account_id: int, data: AccountUpdate, requester: User) -> Account:
    account = await _get_account_or_raise(db, account_id, requester)

    for field, value in data.model_dump(exclude_unset=True, exclude={"contacts"}).items():
        setattr(account, field, value)

    await _add_contacts(db, account.id, data.contacts)

    await db.flush()
    refresh_attrs = []
    if data.owner_id is not None:
        # owner was already eagerly loaded in _get_account_or_raise, but for
        # the *old* owner_id -- refresh so owner_name reflects the new owner.
        refresh_attrs.append("owner")
    if data.contacts:
        refresh_attrs.append("contact_accounts")
    if refresh_attrs:
        await db.refresh(account, attribute_names=refresh_attrs)
    await log_audit(
        db, table_name="accounts", record_id=account.id, action=AuditAction.UPDATED,
        actor_id=requester.id, description=f"Account '{account.company}' updated",
    )
    return account


async def get_account_overview(
    db: AsyncSession, account_id: int, requester: User
) -> tuple[Account, list[Deal], float]:
    """Account Information + Key Contacts + Active Deals for the Overview
    screen. active_deals excludes closed/cold stages; open_deal_value is
    their value summed. Pre-Sales Checklist / Last Activity / Next Step /
    Total ARR have no backing model yet, so they aren't computed here --
    the route fills those with null."""
    account = await _get_account_or_raise(db, account_id, requester)
    stage_ids = {deal.stage_id for deal in account.deals}
    closed_stage_ids: set[int] = set()
    if stage_ids:
        result = await db.execute(
            select(DealStage.id).where(
                DealStage.id.in_(stage_ids),
                or_(DealStage.is_cold.is_(True), DealStage.name.in_(_CLOSED_STAGE_NAMES)),
            )
        )
        closed_stage_ids = set(result.scalars().all())
    active_deals = [deal for deal in account.deals if deal.stage_id not in closed_stage_ids]
    open_deal_value = sum((deal.value or 0) for deal in active_deals)
    return account, active_deals, open_deal_value


async def delete_account(db: AsyncSession, account_id: int, requester: User) -> None:
    account = await _get_account_or_raise(db, account_id, requester)
    account_id_, company = account.id, account.company
    await db.delete(account)
    await db.flush()
    await log_audit(
        db, table_name="accounts", record_id=account_id_, action=AuditAction.DELETED,
        actor_id=requester.id, description=f"Account '{company}' deleted",
    )


async def convert_lead_to_account(
    db: AsyncSession,
    lead_id: int,
    requester: User,
    tier: LeadTier | None = None,
    owner_id: int | None = None,
) -> Account:
    lead = await get_lead(db, lead_id, requester)

    if lead.is_converted:
        raise LeadAlreadyConvertedError(f"Lead already converted: {lead_id}")

    resolved_tier = tier
    resolved_owner_id = owner_id or lead.owner_id
    missing = [
        name
        for name, value in (("tier", resolved_tier), ("owner_id", resolved_owner_id))
        if value is None
    ]
    if missing:
        raise LeadMissingFieldsForConversionError(
            f"Lead {lead_id} is missing required field(s) for conversion: {', '.join(missing)}"
        )
    assert resolved_owner_id is not None  # narrows for mypy; the missing-fields check above guarantees this

    account = Account(
        company=lead.company,
        domain=lead.domain,
        tier=resolved_tier,
        owner_id=resolved_owner_id,
        source_lead_id=lead.id,
        linkedin_url=lead.linkedin_url,
    )
    db.add(account)
    lead.is_converted = True
    await db.flush()

    contact = (
        await db.execute(select(Contact).where(Contact.email == lead.email))
    ).scalar_one_or_none()
    if contact is None:
        contact = Contact(
            first_name=lead.first_name,
            last_name=lead.last_name,
            email=lead.email,
            phone=lead.phone,
            linkedin_url=lead.linkedin_url,
            job_title=lead.job_title,
        )
        db.add(contact)
        await db.flush()
    db.add(ContactAccount(contact_id=contact.id, account_id=account.id, is_primary=True))

    # Lead.contacts (added via "+ Add another email" on the lead) carry over
    # too -- same reuse-by-email as the primary contact above, just
    # non-primary. Skip the row that mirrors the lead's own email (already
    # handled as the primary) and any lacking an email at all. Each
    # LeadContact carries its own name now; only fall back to the lead's own
    # name when a contact didn't supply one (same convention as
    # _add_contacts' nameless-extra-contact handling on direct Account
    # creation).
    lead_contacts = (
        await db.execute(select(LeadContact).where(LeadContact.lead_id == lead.id))
    ).scalars().all()
    for lead_contact in lead_contacts:
        if lead_contact.email is None or lead_contact.email == lead.email:
            continue
        extra_contact = (
            await db.execute(select(Contact).where(Contact.email == lead_contact.email))
        ).scalar_one_or_none()
        if extra_contact is None:
            extra_contact = Contact(
                first_name=lead_contact.first_name or lead.first_name,
                last_name=lead_contact.last_name if lead_contact.first_name else lead.last_name,
                email=lead_contact.email,
                phone=lead_contact.phone,
            )
            db.add(extra_contact)
            await db.flush()
        db.add(ContactAccount(contact_id=extra_contact.id, account_id=account.id, is_primary=False))

    await db.flush()
    await db.refresh(account, attribute_names=["owner", "contact_accounts", "deals"])

    await create_notification(
        db,
        recipient_id=resolved_owner_id,
        type=NotificationType.LEAD_CONVERTED,
        title="Lead converted to account",
        body=f"{lead.name} at {lead.company} was converted to an account.",
        actor_id=requester.id,
        entity_type="account",
        entity_id=account.id,
    )

    await log_audit(
        db, table_name="accounts", record_id=account.id, action=AuditAction.CREATED,
        actor_id=requester.id,
        description=(
            f"Account '{account.company}' created from lead '{lead.name}' conversion"
        ),
    )
    await log_audit(
        db, table_name="leads", record_id=lead.id, action=AuditAction.UPDATED,
        actor_id=requester.id, description=f"Lead '{lead.company}' converted to account '{account.company}'",
    )
    return account
