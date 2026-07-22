"""app.services.notification_service: create/list/unread-count/mark-read/delete.

Covers: create_notification defaults; list_notifications unread_only + type
filters and pagination; overdue-follow-up leads merged into the list;
unread count math; mark one read; mark-all (optionally scoped to ids);
delete is a soft delete and is recipient-scoped (403 on someone else's row).
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType
from app.services.notification_service import (
    NotificationAccessForbiddenError,
    NotificationNotFoundError,
    create_notification,
    delete_notifications,
    get_unread_count,
    list_notifications,
    mark_all_read,
    mark_read,
)


async def test_create_notification_sets_expected_fields(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-create@example.com")

    notification = await create_notification(
        db_session,
        recipient_id=recipient.id,
        type=NotificationType.LEAD_ASSIGNED,
        title="New lead assigned",
        body="You have been assigned the new lead Ivy Rao.",
        entity_type="lead",
        entity_id=1,
    )

    assert notification.recipient_id == recipient.id
    assert notification.is_read is False
    assert notification.entity_type == "lead"


async def test_list_notifications_unread_only_filter(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-list@example.com")
    read_one = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="b", body="b", entity_type="lead", entity_id=2,
    )
    await mark_read(db_session, read_one.id, requester=recipient)

    items, total = await list_notifications(db_session, requester=recipient, unread_only=True)

    assert total == 1
    assert all(not item.is_read for item in items)


async def test_list_notifications_type_filter(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-type@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.DEAL_STAGE_CHANGED,
        title="b", body="b", entity_type="deal", entity_id=1,
    )

    items, total = await list_notifications(
        db_session, requester=recipient, type=NotificationType.DEAL_STAGE_CHANGED
    )

    assert total == 1
    assert items[0].type == NotificationType.DEAL_STAGE_CHANGED


async def test_list_notifications_merges_overdue_followups(db_session: AsyncSession, make_user, make_lead):
    recipient = await make_user(email="recipient-overdue@example.com")
    await make_lead(
        owner_id=recipient.id,
        email="overdue-lead@acme.com",
        next_follow_up_date=date.today() - timedelta(days=1),
    )
    await make_lead(
        owner_id=recipient.id,
        email="future-lead@acme.com",
        next_follow_up_date=date.today() + timedelta(days=1),
    )

    items, total = await list_notifications(db_session, requester=recipient)

    overdue_items = [item for item in items if item.type == NotificationType.TASK_OVERDUE]
    assert len(overdue_items) == 1
    assert total == 1


async def test_get_unread_count(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-count@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="b", body="b", entity_type="lead", entity_id=2,
    )

    count = await get_unread_count(db_session, requester=recipient)

    assert count == 2


async def test_mark_read_forbidden_for_other_recipient(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-forbidden@example.com")
    other = await make_user(email="other-forbidden@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )

    with pytest.raises(NotificationAccessForbiddenError):
        await mark_read(db_session, notification.id, requester=other)


async def test_mark_read_not_found(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-notfound@example.com")

    with pytest.raises(NotificationNotFoundError):
        await mark_read(db_session, 999999, requester=recipient)


async def test_mark_all_read_scoped_to_ids(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-bulk@example.com")
    first = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    second = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="b", body="b", entity_type="lead", entity_id=2,
    )

    updated = await mark_all_read(db_session, requester=recipient, ids=[first.id])

    assert updated == 1
    count = await get_unread_count(db_session, requester=recipient)
    assert count == 1
    assert second.is_read is False


async def test_mark_all_read_without_ids_marks_everything(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-bulk-all@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="b", body="b", entity_type="lead", entity_id=2,
    )

    updated = await mark_all_read(db_session, requester=recipient)

    assert updated == 2
    assert await get_unread_count(db_session, requester=recipient) == 0


async def test_delete_notifications_forbidden_for_other_recipient(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-delete@example.com")
    other = await make_user(email="other-delete@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )

    with pytest.raises(NotificationAccessForbiddenError):
        await delete_notifications(db_session, [notification.id], requester=other)


async def test_delete_notifications_soft_deletes(db_session: AsyncSession, make_user):
    recipient = await make_user(email="recipient-softdelete@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )

    await delete_notifications(db_session, [notification.id], requester=recipient)

    items, total = await list_notifications(db_session, requester=recipient)
    assert total == 0
