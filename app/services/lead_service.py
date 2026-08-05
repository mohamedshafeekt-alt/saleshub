"""Lead business logic: creation (with duplicate-email guard), role-scoped
listing/search, and ownership-checked get/update/delete."""

from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.core.permission_codes import LEADS_NOTIFY_ON_CREATE, LEADS_VIEW_ALL
from app.models.enums import AuditAction, LeadSource, LeadStatus, NotificationType
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.lead_contact import LeadContact
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import role_permissions
from app.models.user import User
from app.schemas.lead import LeadUpsert
from app.services.email.sender import EmailSender
from app.services.email.templates import send_new_lead_notification_email
from app.services.notification_service import create_notification
from app.services.audit_service import log_audit


class DuplicateLeadEmailError(Exception):
    """Raised when attempting to create/update a lead with an email already in use."""


class LeadNotFoundError(Exception):
    """Raised when a lead id does not exist."""


class LeadAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access a lead they don't own."""


def _is_duplicate_email_violation(exc: IntegrityError) -> bool:
    # ix_leads_email guards the lead's own email; ix_lead_contacts_email
    # guards its additional contacts (LeadContact rows added below). Any
    # other IntegrityError (e.g. a bad owner_id FK) is a different failure
    # and must not be reported as a duplicate email.
    return "ix_leads_email" in str(exc.orig) or "ix_lead_contacts_email" in str(exc.orig)


async def create_lead(db: AsyncSession, data: LeadUpsert, email_sender: EmailSender, requester: User) -> Lead:
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
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    result = await db.execute(
        select(User)
        .join(Role, User.role_id == Role.id)
        .join(role_permissions, Role.id == role_permissions.c.role_id)
        .join(Permission, role_permissions.c.permission_id == Permission.id)
        .where(Permission.code == LEADS_NOTIFY_ON_CREATE)
    )
    lead_name = f"{lead.first_name} {lead.last_name}".strip()
    for notifiable in result.scalars():
        try:
            await send_new_lead_notification_email(email_sender, notifiable.email, lead_name, lead.company)
        except Exception:
            logger.warning(
                "Failed to send new-lead notification email to %s", notifiable.email, exc_info=True
            )
        await create_notification(
            db,
            recipient_id=notifiable.id,
            type=NotificationType.NEW_LEAD,
            title="New lead created",
            body=f"{lead_name} at {lead.company} was just added as a new lead.",
            entity_type="lead",
            entity_id=lead.id,
        )

    # owner is unloaded on a freshly constructed row (no SELECT has run yet to
    # populate it). Accessing owner_name later during response serialization
    # -- outside an async context -- would raise MissingGreenlet unless it's
    # loaded now, while still awaitable. Only reliably a no-op in tests, where
    # the requester and the assigned owner are often the same already-loaded
    # session identity; a distinct owner in a fresh request session needs this.
    await db.refresh(lead, attribute_names=["owner"])

    await log_audit(
        db, table_name="leads", record_id=lead.id, action=AuditAction.CREATED,
        actor_id=requester.id, description=f"Lead '{lead_name} at {lead.company}' created",
    )

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
    filters: list[ColumnElement[bool]] = [Lead.is_converted.is_(False)]
    if LEADS_VIEW_ALL not in requester.permission_codes:
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
                Lead.first_name.ilike(pattern),
                Lead.last_name.ilike(pattern),
                Lead.email.ilike(pattern),
            )
        )

    count_query = select(func.count(Lead.id)).where(*filters)
    items_query = (
        select(Lead)
        .options(selectinload(Lead.owner))
        .where(*filters)
        .order_by(Lead.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    total = (await db.execute(count_query)).scalar_one()
    items = list((await db.execute(items_query)).scalars().all())
    return items, total


async def export_leads(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    source: LeadSource | None = None,
    status: LeadStatus | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """All leads matching the requester's role-scoping (same rule as
    list_leads). No pagination."""
    filters: list[ColumnElement[bool]] = [Lead.is_converted.is_(False)]
    if LEADS_VIEW_ALL not in requester.permission_codes:
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
                Lead.first_name.ilike(pattern),
                Lead.last_name.ilike(pattern),
                Lead.email.ilike(pattern),
            )
        )

    result = await db.execute(
        select(Lead)
        .options(selectinload(Lead.owner))
        .where(*filters)
        .order_by(Lead.created_at.desc())
    )
    leads = result.scalars().all()
    return [
        {
            "name": " ".join(filter(None, [lead.first_name, lead.last_name])),
            "email": lead.email,
            "phone": lead.phone,
            "company": lead.company,
            "source": lead.source.value,
            "status": lead.status.value,
            "owner": lead.owner_name,
        }
        for lead in leads
    ]


def _check_lead_access(lead: Lead, requester: User) -> None:
    if (
        LEADS_VIEW_ALL not in requester.permission_codes
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
    old_owner_id = lead.owner_id

    updates = data.model_dump(exclude_unset=True, exclude={"id", "contacts"})
    for field, value in updates.items():
        setattr(lead, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_email_violation(exc):
            raise DuplicateLeadEmailError(f"Email already exists: {data.email}") from exc
        raise

    if "owner_id" in updates and updates["owner_id"] is not None and updates["owner_id"] != old_owner_id:
        lead_name = f"{lead.first_name} {lead.last_name}".strip()
        await create_notification(
            db,
            recipient_id=updates["owner_id"],
            type=NotificationType.LEAD_ASSIGNED,
            title="Lead assigned to you",
            body=f"You have been assigned the lead {lead_name} at {lead.company}.",
            actor_id=requester.id,
            entity_type="lead",
            entity_id=lead.id,
        )

    # updated_at's onupdate is server-computed (func.now() on Base), so after
    # an UPDATE SQLAlchemy marks it expired rather than refetching it --
    # accessing it later outside an async context (e.g. during response
    # serialization) would raise MissingGreenlet. Refresh now, while still awaitable.
    await db.refresh(lead)

    await log_audit(
        db, table_name="leads", record_id=lead.id, action=AuditAction.UPDATED,
        actor_id=requester.id,
        description=f"Lead '{f'{lead.first_name} {lead.last_name}'.strip()} at {lead.company}' updated",
    )

    return lead


async def delete_lead(db: AsyncSession, lead_id: int, requester: User) -> None:
    lead = await _get_lead_or_raise(db, lead_id, requester)
    lead_id_, company = lead.id, lead.company
    lead_name = f"{lead.first_name} {lead.last_name}".strip()
    await db.delete(lead)
    await db.flush()
    await log_audit(
        db, table_name="leads", record_id=lead_id_, action=AuditAction.DELETED,
        actor_id=requester.id, description=f"Lead '{lead_name} at {company}' deleted",
    )
