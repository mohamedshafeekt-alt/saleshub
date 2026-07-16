"""Lead business logic: creation (with duplicate-email guard), role-scoped
listing/search, and ownership-checked get/update/delete."""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.models.enums import LeadSource, LeadStatus
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_contact import LeadContact
from app.models.user import User, UserRole
from app.schemas.lead import LeadUpsert
from app.services.email.sender import EmailSender
from app.services.email.templates import send_new_lead_notification_email


class DuplicateLeadEmailError(Exception):
    """Raised when attempting to create/update a lead with an email already in use."""


class LeadNotFoundError(Exception):
    """Raised when a lead id does not exist."""


class LeadAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access a lead they don't own."""


def _is_duplicate_email_violation(exc: IntegrityError) -> bool:
    # The unique index on Lead.email is the only unique constraint on this
    # table; any other IntegrityError (e.g. a bad owner_id FK) is a
    # different failure and must not be reported as a duplicate email.
    return "ix_leads_email" in str(exc.orig)


async def create_lead(db: AsyncSession, data: LeadUpsert, email_sender: EmailSender) -> Lead:
    lead_data = data.model_dump(exclude={"id", "contacts"})
    lead_data["status"] = lead_data["status"] or LeadStatus.NOT_CONTACTED
    lead = Lead(**lead_data)
    db.add(lead)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    db.add(LeadContact(lead_id=lead.id, email=lead.email, phone=lead.phone))
    for contact in data.contacts:
        db.add(LeadContact(lead_id=lead.id, email=contact.email, phone=contact.phone))
    await db.flush()

    result = await db.execute(select(User).where(User.role == UserRole.ADMIN))
    lead_name = f"{lead.first_name} {lead.last_name}".strip()
    for admin in result.scalars():
        try:
            await send_new_lead_notification_email(email_sender, admin.email, lead_name, lead.company)
        except Exception:
            logger.warning("Failed to send new-lead notification email to %s", admin.email, exc_info=True)

    # owner is unloaded on a freshly constructed row (no SELECT has run yet to
    # populate it). Accessing owner_name later during response serialization
    # -- outside an async context -- would raise MissingGreenlet unless it's
    # loaded now, while still awaitable. Only reliably a no-op in tests, where
    # the requester and the assigned owner are often the same already-loaded
    # session identity; a distinct owner in a fresh request session needs this.
    await db.refresh(lead, attribute_names=["owner"])

    return lead


async def list_leads(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    source: LeadSource | None = None,
    status: LeadStatus | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Lead], int]:
    filters = []
    if requester.role in (UserRole.SALES_REP, UserRole.DELIVERY_SME):
        filters.append(or_(Lead.owner_id == requester.id, Lead.owner_id.is_(None)))
    if owner_id is not None:
        filters.append(Lead.owner_id == owner_id)
    if source is not None:
        filters.append(Lead.source == source)
    if status is not None:
        filters.append(Lead.status == status)
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                Lead.company.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )

    count_query = select(func.count(Lead.id))
    items_query = select(Lead).options(selectinload(Lead.owner))
    if search is not None:
        # Only the search filter needs the join (it matches against owner name).
        count_query = count_query.join(User, Lead.owner_id == User.id, isouter=True)
        items_query = items_query.join(User, Lead.owner_id == User.id, isouter=True)

    count_query = count_query.where(*filters)
    items_query = items_query.where(*filters).order_by(Lead.created_at.desc()).limit(limit).offset(offset)

    total = (await db.execute(count_query)).scalar_one()
    items = list((await db.execute(items_query)).scalars().all())
    return items, total


def _check_lead_access(lead: Lead, requester: User) -> None:
    if (
        requester.role in (UserRole.SALES_REP, UserRole.DELIVERY_SME)
        and lead.owner_id is not None
        and lead.owner_id != requester.id
    ):
        raise LeadAccessForbiddenError(f"Not permitted to access lead: {lead.id}")


async def _get_lead_or_raise(db: AsyncSession, lead_id: int, requester: User) -> Lead:
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.owner))
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise LeadNotFoundError(f"Lead not found: {lead_id}")
    _check_lead_access(lead, requester)
    return lead


async def get_lead(db: AsyncSession, lead_id: int, requester: User) -> Lead:
    return await _get_lead_or_raise(db, lead_id, requester)


async def get_lead_detail(db: AsyncSession, lead_id: int, requester: User) -> Lead:
    """Like get_lead, but eager-loads contacts + activities (with each
    activity's creator) for the single-lead detail view."""
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.owner),
            selectinload(Lead.contacts),
            selectinload(Lead.activities).selectinload(LeadActivity.creator),
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise LeadNotFoundError(f"Lead not found: {lead_id}")
    _check_lead_access(lead, requester)
    return lead


async def update_lead(db: AsyncSession, lead_id: int, data: LeadUpsert, requester: User) -> Lead:
    lead = await _get_lead_or_raise(db, lead_id, requester)

    for field, value in data.model_dump(exclude_unset=True, exclude={"id", "contacts"}).items():
        setattr(lead, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    # updated_at's onupdate is server-computed (func.now() on Base), so after
    # an UPDATE SQLAlchemy marks it expired rather than refetching it --
    # accessing it later outside an async context (e.g. during response
    # serialization) would raise MissingGreenlet. Refresh now, while still awaitable.
    await db.refresh(lead)

    return lead


async def delete_lead(db: AsyncSession, lead_id: int, requester: User) -> None:
    lead = await _get_lead_or_raise(db, lead_id, requester)
    await db.delete(lead)
    await db.flush()
