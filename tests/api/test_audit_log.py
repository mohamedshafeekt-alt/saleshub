import pytest

from tests.support.roles import UserRole

pytestmark = pytest.mark.anyio

AUDIT_LOG_URL = "/api/v1/audit-log"


async def test_audit_log_no_auth_header_returns_401(client):
    response = await client.get(AUDIT_LOG_URL)
    assert response.status_code == 401


async def test_audit_log_as_sales_rep_returns_403(client, make_user, auth_headers):
    rep = await make_user(email="audit-api-rep@example.com", role=UserRole.SALES_REP)
    response = await client.get(AUDIT_LOG_URL, headers=auth_headers(rep))
    assert response.status_code == 403


async def test_audit_log_as_admin_returns_paginated_list(client, make_user, auth_headers, db_session):
    from app.models.enums import AuditAction
    from app.services.audit_service import log_audit

    admin = await make_user(email="audit-api-admin@example.com", role=UserRole.ADMIN)
    await log_audit(
        db_session, table_name="leads", record_id=1, action=AuditAction.CREATED,
        actor_id=admin.id, description="Lead 'Acme' created",
    )
    await db_session.commit()

    response = await client.get(AUDIT_LOG_URL, headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["items"][0]["description"] == "Lead 'Acme' created"
    assert body["items"][0]["actor_name"] == admin.first_name


async def test_audit_log_filters_by_table_name(client, make_user, auth_headers, db_session):
    from app.models.enums import AuditAction
    from app.services.audit_service import log_audit

    admin = await make_user(email="audit-api-admin2@example.com", role=UserRole.ADMIN)
    await log_audit(db_session, table_name="leads", record_id=1, action=AuditAction.CREATED, actor_id=admin.id, description="a")
    await log_audit(db_session, table_name="deals", record_id=2, action=AuditAction.CREATED, actor_id=admin.id, description="b")
    await db_session.commit()

    response = await client.get(f"{AUDIT_LOG_URL}?table_name=deals", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["table_name"] == "deals"
