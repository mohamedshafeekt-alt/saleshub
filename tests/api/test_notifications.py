"""HTTP-level contract for /api/v1/notifications.

Covers: 401 no auth, list + unread_only/type filters, unread-count,
PATCH /{id} {"is_read": bool} to toggle one notification's read state in
either direction (200 + 404 for someone else's / missing id), mark-all
(with and without an ids body), bulk delete (200 + 403 for someone else's
notification).
"""

from httpx import AsyncClient

from app.models.enums import NotificationType
from app.services.notification_service import create_notification

NOTIFICATIONS_URL = "/api/v1/notifications"


async def test_list_notifications_requires_auth(client: AsyncClient):
    response = await client.get(NOTIFICATIONS_URL)
    assert response.status_code == 401


async def test_list_notifications_returns_own_notifications(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-recipient@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="New lead", body="body", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.get(NOTIFICATIONS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "New lead"


async def test_list_notifications_type_filter(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-type-filter@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.DEAL_STAGE_CHANGED,
        title="b", body="b", entity_type="deal", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.get(f"{NOTIFICATIONS_URL}?type=deal_stage_changed", headers=headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_unread_count(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-unread-count@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.get(f"{NOTIFICATIONS_URL}/unread-count", headers=headers)

    assert response.status_code == 200
    assert response.json()["unread_count"] == 1


async def test_update_notification_marks_read(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-mark-one@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.patch(
        f"{NOTIFICATIONS_URL}/{notification.id}", json={"is_read": True}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is True


async def test_update_notification_marks_unread(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-mark-unread@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)
    await client.patch(f"{NOTIFICATIONS_URL}/{notification.id}", json={"is_read": True}, headers=headers)

    response = await client.patch(
        f"{NOTIFICATIONS_URL}/{notification.id}", json={"is_read": False}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is False


async def test_update_notification_not_found(client: AsyncClient, make_user, auth_headers):
    recipient = await make_user(email="api-mark-notfound@example.com")
    headers = auth_headers(recipient)

    response = await client.patch(f"{NOTIFICATIONS_URL}/999999", json={"is_read": True}, headers=headers)

    assert response.status_code == 404


async def test_update_notification_forbidden_for_other_recipient(
    client: AsyncClient, make_user, auth_headers, db_session
):
    recipient = await make_user(email="api-mark-owner@example.com")
    other = await make_user(email="api-mark-other@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(other)

    response = await client.patch(
        f"{NOTIFICATIONS_URL}/{notification.id}", json={"is_read": True}, headers=headers
    )

    assert response.status_code == 403


async def test_mark_all_read_without_body(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-mark-all@example.com")
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="b", body="b", entity_type="lead", entity_id=2,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.post(f"{NOTIFICATIONS_URL}/read-all", headers=headers, json={})

    assert response.status_code == 200
    count_response = await client.get(f"{NOTIFICATIONS_URL}/unread-count", headers=headers)
    assert count_response.json()["unread_count"] == 0


async def test_bulk_delete(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-bulk-delete@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(recipient)

    response = await client.request(
        "DELETE", NOTIFICATIONS_URL, headers=headers, json={"ids": [notification.id]}
    )

    assert response.status_code == 200
    list_response = await client.get(NOTIFICATIONS_URL, headers=headers)
    assert list_response.json()["total"] == 0


async def test_bulk_delete_forbidden_for_other_recipient(client: AsyncClient, make_user, auth_headers, db_session):
    recipient = await make_user(email="api-delete-owner@example.com")
    other = await make_user(email="api-delete-other@example.com")
    notification = await create_notification(
        db_session, recipient_id=recipient.id, type=NotificationType.NEW_LEAD,
        title="a", body="a", entity_type="lead", entity_id=1,
    )
    await db_session.commit()
    headers = auth_headers(other)

    response = await client.request(
        "DELETE", NOTIFICATIONS_URL, headers=headers, json={"ids": [notification.id]}
    )

    assert response.status_code == 403
