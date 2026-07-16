"""Lead business logic: creation (with duplicate-email guard), role-scoped
listing/search, and ownership-checked get/update/delete."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource, LeadStatus, LeadTier
from app.models.lead import Lead
from app.models.user import User, UserRole
from app.schemas.lead import LeadCreate, LeadUpdate


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


async def create_lead(db: AsyncSession, data: LeadCreate) -> Lead:
    lead = Lead(**data.model_dump())
    db.add(lead)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    return lead


async def list_leads(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    source: LeadSource | None = None,
    tier: LeadTier | None = None,
    status: LeadStatus | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Lead]:
    query = select(Lead)
    if search is not None:
        query = query.join(User, Lead.owner_id == User.id, isouter=True)

    if requester.role in (UserRole.SALES_REP, UserRole.DELIVERY_SME):
        query = query.where(or_(Lead.owner_id == requester.id, Lead.owner_id.is_(None)))

    if owner_id is not None:
        query = query.where(Lead.owner_id == owner_id)
    if source is not None:
        query = query.where(Lead.source == source)
    if tier is not None:
        query = query.where(Lead.tier == tier)
    if status is not None:
        query = query.where(Lead.status == status)
    if search is not None:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Lead.company.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )

    query = query.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_lead_or_raise(db: AsyncSession, lead_id: int, requester: User) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise LeadNotFoundError(f"Lead not found: {lead_id}")
    if (
        requester.role in (UserRole.SALES_REP, UserRole.DELIVERY_SME)
        and lead.owner_id is not None
        and lead.owner_id != requester.id
    ):
        raise LeadAccessForbiddenError(f"Not permitted to access lead: {lead_id}")
    return lead


async def get_lead(db: AsyncSession, lead_id: int, requester: User) -> Lead:
    return await _get_lead_or_raise(db, lead_id, requester)


async def update_lead(db: AsyncSession, lead_id: int, data: LeadUpdate, requester: User) -> Lead:
    lead = await _get_lead_or_raise(db, lead_id, requester)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    return lead


async def delete_lead(db: AsyncSession, lead_id: int, requester: User) -> None:
    lead = await _get_lead_or_raise(db, lead_id, requester)
    await db.delete(lead)
    await db.flush()
