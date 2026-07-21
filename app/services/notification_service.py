"""Notification business logic: create rows at existing event trigger
points, list (merged with computed overdue-follow-up entries), unread
count, mark-read, and soft-delete — everything strictly scoped to the
requester's own recipient_id."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType
from app.models.lead import Lead
from app.models.notification import Notification
from app.models.user import User


class NotificationNotFoundError(Exception):
    """Raised when a notification id does not exist."""


class NotificationAccessForbiddenError(Exception):
    """Raised when a user tries to read/mutate another user's notification."""


@dataclass
class OverdueFollowUpItem:
    """A computed (non-persisted) TASK_OVERDUE entry, shaped enough like
    Notification for NotificationRead.model_validate to serialize it."""

    id: int
    type: NotificationType
    title: str
    body: str
    is_read: bool
    read_at: datetime | None
    actor_id: int | None
    entity_type: str
    entity_id: int
    created_at: datetime


async def create_notification(
    db: AsyncSession,
    *,
    recipient_id: int,
    type: NotificationType,
    title: str,
    body: str,
    entity_type: str,
    entity_id: int,
    actor_id: int | None = None,
) -> Notification:
    notification = Notification(
        recipient_id=recipient_id,
        type=type,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
    )
    db.add(notification)
    await db.flush()
    return notification


async def _overdue_followup_items(db: AsyncSession, requester: User) -> list[OverdueFollowUpItem]:
    result = await db.execute(
        select(Lead).where(Lead.owner_id == requester.id, Lead.next_follow_up_date < date.today())
    )
    items: list[OverdueFollowUpItem] = []
    for lead in result.scalars():
        if lead.next_follow_up_date is None:
            continue
        lead_name = f"{lead.first_name} {lead.last_name}".strip()
        items.append(
            OverdueFollowUpItem(
                id=-lead.id,  # negative: never collides with a real Notification.id
                type=NotificationType.TASK_OVERDUE,
                title="Follow-up overdue",
                body=f"Follow up with {lead_name} at {lead.company} is overdue.",
                is_read=False,
                read_at=None,
                actor_id=None,
                entity_type="lead",
                entity_id=lead.id,
                created_at=datetime.combine(lead.next_follow_up_date, datetime.min.time()),
            )
        )
    return items


async def list_notifications(
    db: AsyncSession,
    *,
    requester: User,
    unread_only: bool = False,
    type: NotificationType | None = None,
    limit: int = 20,
    offset: int = 0,
):
    overdue_items = []
    if type is None or type == NotificationType.TASK_OVERDUE:
        overdue_items = await _overdue_followup_items(db, requester)
        if unread_only:
            overdue_items = [item for item in overdue_items if not item.is_read]

    stored_items: list[Notification] = []
    stored_total = 0
    if type != NotificationType.TASK_OVERDUE:
        filters = [Notification.recipient_id == requester.id, Notification.is_delete.is_(False)]
        if unread_only:
            filters.append(Notification.is_read.is_(False))
        if type is not None:
            filters.append(Notification.type == type)

        stored_total = (await db.execute(select(func.count(Notification.id)).where(*filters))).scalar_one()
        query = (
            select(Notification).where(*filters).order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        )
        stored_items = list((await db.execute(query)).scalars().all())

    merged: list[Notification | OverdueFollowUpItem] = [*overdue_items, *stored_items]
    merged.sort(key=lambda item: item.created_at, reverse=True)
    total = stored_total + len(overdue_items)
    return merged[:limit], total


async def get_unread_count(db: AsyncSession, *, requester: User) -> int:
    overdue_items = await _overdue_followup_items(db, requester)
    stored_count = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == requester.id,
                Notification.is_delete.is_(False),
                Notification.is_read.is_(False),
            )
        )
    ).scalar_one()
    return stored_count + len(overdue_items)


async def _get_owned_notification_or_raise(db: AsyncSession, notification_id: int, requester: User) -> Notification:
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if notification is None or notification.is_delete:
        raise NotificationNotFoundError(f"Notification not found: {notification_id}")
    if notification.recipient_id != requester.id:
        raise NotificationAccessForbiddenError(f"Not permitted to access notification: {notification_id}")
    return notification


async def mark_read(db: AsyncSession, notification_id: int, *, requester: User) -> Notification:
    notification = await _get_owned_notification_or_raise(db, notification_id, requester)
    notification.is_read = True
    notification.read_at = datetime.now()
    await db.flush()
    return notification


async def mark_all_read(db: AsyncSession, *, requester: User, ids: list[int] | None = None) -> int:
    filters = [
        Notification.recipient_id == requester.id,
        Notification.is_delete.is_(False),
        Notification.is_read.is_(False),
    ]
    if ids is not None:
        filters.append(Notification.id.in_(ids))

    result = await db.execute(
        update(Notification)
        .where(*filters)
        .values(is_read=True, read_at=datetime.now())
        .returning(Notification.id)
    )
    updated_ids = result.scalars().all()
    await db.flush()
    return len(updated_ids)


async def delete_notifications(db: AsyncSession, ids: list[int], *, requester: User) -> None:
    result = await db.execute(select(Notification).where(Notification.id.in_(ids)))
    notifications = list(result.scalars().all())

    found_ids = {notification.id for notification in notifications}
    missing = set(ids) - found_ids
    if missing:
        raise NotificationNotFoundError(f"Notification(s) not found: {sorted(missing)}")

    for notification in notifications:
        if notification.recipient_id != requester.id:
            raise NotificationAccessForbiddenError(f"Not permitted to delete notification: {notification.id}")

    for notification in notifications:
        notification.is_delete = True
    await db.flush()
