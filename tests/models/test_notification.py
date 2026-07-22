"""app.models.notification.Notification: column defaults and FK integrity."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType
from app.models.notification import Notification


async def test_create_notification_defaults(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient@example.com")

    notification = Notification(
        recipient_id=recipient.id,
        type=NotificationType.LEAD_ASSIGNED,
        title="New lead assigned",
        body="You have been assigned the new lead Ivy Rao.",
        entity_type="lead",
        entity_id=1,
    )
    db_session.add(notification)
    await db_session.flush()

    result = await db_session.execute(select(Notification).where(Notification.id == notification.id))
    stored = result.scalar_one()

    assert stored.is_read is False
    assert stored.read_at is None
    assert stored.actor_id is None
    assert isinstance(stored.created_at, datetime)
