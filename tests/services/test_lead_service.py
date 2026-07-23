"""app.services.lead_service: create/list/get/update/delete business rules.

Covers: successful create; duplicate-email guard; list_leads role-scoping
(Sales Rep forced to own leads, Manager/Admin see all or filtered);
source exact-match filter; search across company + owner name;
not-found/forbidden checks on get/update/delete; partial update; delete.
"""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadActivityType, LeadSource, NotificationType
from app.models.lead_activity import LeadActivity
from app.models.lead_contact import LeadContact
from app.models.user import User
from tests.support.roles import UserRole, role_id_for
from app.schemas.lead import LeadContactInput, LeadUpsert
from app.services.lead_service import (
    DuplicateLeadEmailError,
    LeadAccessForbiddenError,
    LeadNotFoundError,
    create_lead,
    delete_lead,
    export_leads,
    get_lead,
    get_lead_detail,
    list_leads,
    update_lead,
)


class FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def test_create_lead_succeeds(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner@example.com", UserRole.SALES_REP)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="jane@acme.com",
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
    )
    lead = await create_lead(db_session, data, FakeEmailSender())

    assert lead.id is not None
    assert lead.email == "jane@acme.com"
    assert lead.owner_id == owner.id


async def test_create_lead_owner_relationship_is_loaded_even_when_owner_row_was_not_already_in_session(
    db_session: AsyncSession,
):
    # Regression test: a plain in-test session shares identity map state
    # between fixture setup and the call under test, which would silently
    # mask this bug (the owner row ends up already loaded "for free"). A real
    # request session doesn't share state with wherever the owner was last
    # queried, so expunge it here to force create_lead to genuinely need to
    # load Lead.owner itself rather than finding it already cached.
    owner = await _make_user(db_session, "owner-fresh-session@example.com", UserRole.SALES_REP)
    db_session.expunge(owner)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="fresh-session-owner@acme.com",
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
    )
    lead = await create_lead(db_session, data, FakeEmailSender())

    assert lead.owner is not None
    assert lead.owner.id == owner.id
    assert lead.owner_name == "Test"


async def test_create_lead_inserts_primary_contact_into_lead_contacts(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-primary-contact@example.com", UserRole.SALES_REP)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="primary-contact@acme.com",
        phone="+1-555-0100",
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
    )
    lead = await create_lead(db_session, data, FakeEmailSender())

    result = await db_session.execute(select(LeadContact).where(LeadContact.lead_id == lead.id))
    contacts = result.scalars().all()

    assert len(contacts) == 1
    assert contacts[0].email == "primary-contact@acme.com"
    assert contacts[0].phone == "+1-555-0100"


async def test_create_lead_inserts_extra_contacts_alongside_primary(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-extra-contact@example.com", UserRole.SALES_REP)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="primary-with-extra@acme.com",
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
        contacts=[LeadContactInput(email="second@acme.com"), LeadContactInput(email="third@acme.com")],
    )
    lead = await create_lead(db_session, data, FakeEmailSender())

    result = await db_session.execute(select(LeadContact).where(LeadContact.lead_id == lead.id))
    emails = {contact.email for contact in result.scalars().all()}

    assert emails == {"primary-with-extra@acme.com", "second@acme.com", "third@acme.com"}


async def test_create_lead_notifies_all_admins(db_session: AsyncSession):
    admin_a = await _make_user(db_session, "admin-a@example.com", UserRole.ADMIN)
    admin_b = await _make_user(db_session, "admin-b@example.com", UserRole.ADMIN)
    await _make_user(db_session, "rep-not-notified@example.com", UserRole.SALES_REP)
    fake_sender = FakeEmailSender()

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="notify-admins@acme.com",
        source=LeadSource.WEBSITE,
    )
    await create_lead(db_session, data, fake_sender)

    notified = {call["to"] for call in fake_sender.calls}
    assert notified == {admin_a.email, admin_b.email}


async def test_create_lead_creates_in_app_notifications_for_notifiable_users(db_session: AsyncSession):
    from app.models.notification import Notification

    admin = await _make_user(db_session, "admin-notif@example.com", UserRole.ADMIN)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="notify-in-app@acme.com",
        source=LeadSource.WEBSITE,
    )
    lead = await create_lead(db_session, data, FakeEmailSender())

    result = await db_session.execute(
        select(Notification).where(
            Notification.recipient_id == admin.id, Notification.type == NotificationType.NEW_LEAD
        )
    )
    notification = result.scalar_one()
    assert notification.entity_type == "lead"
    assert notification.entity_id == lead.id


async def test_update_lead_reassignment_notifies_new_owner(db_session: AsyncSession, make_lead):
    from app.models.notification import Notification

    old_owner = await _make_user(db_session, "old-owner@example.com", UserRole.SALES_REP)
    new_owner = await _make_user(db_session, "new-owner@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=old_owner.id, email="reassign-me@acme.com")

    await update_lead(db_session, lead.id, LeadUpsert(id=lead.id, owner_id=new_owner.id), requester=old_owner)

    result = await db_session.execute(select(Notification).where(Notification.recipient_id == new_owner.id))
    notification = result.scalar_one()
    assert notification.entity_id == lead.id
    assert notification.type == NotificationType.LEAD_ASSIGNED


async def test_create_lead_duplicate_email_raises(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-dup@example.com", UserRole.SALES_REP)

    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="dup@acme.com",
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
    )
    await create_lead(db_session, data, FakeEmailSender())

    dup_data = LeadUpsert(
        first_name="John",
        company="Other Corp",
        email="dup@acme.com",
        source=LeadSource.REFERRAL,
        owner_id=owner.id,
    )
    with pytest.raises(DuplicateLeadEmailError):
        await create_lead(db_session, dup_data, FakeEmailSender())


async def test_create_lead_bad_owner_id_raises_integrity_error_not_duplicate_email(db_session: AsyncSession):
    # A foreign-key violation on owner_id must not be mislabeled as a
    # duplicate-email conflict just because both errors are IntegrityErrors.
    data = LeadUpsert(
        first_name="Jane",
        company="Acme Corp",
        email="unique-email-bad-owner@acme.com",
        source=LeadSource.WEBSITE,
        owner_id=999_999_999,
    )
    with pytest.raises(IntegrityError):
        await create_lead(db_session, data, FakeEmailSender())


async def test_list_leads_sales_rep_owner_id_param_does_not_leak_other_reps_leads(
    db_session: AsyncSession, make_lead
):
    # An explicit owner_id filter ANDs on top of the Sales Rep's own-or-unassigned
    # base scope, so asking for another rep's owner_id yields nothing -- it does
    # NOT fall back to "just show my own leads".
    rep_a = await _make_user(db_session, "rep-a@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b@example.com", UserRole.SALES_REP)
    await make_lead(owner_id=rep_a.id, email="own-lead@example.com")
    await make_lead(owner_id=rep_b.id, email="other-lead@example.com")

    results, _total = await list_leads(db_session, requester=rep_a, owner_id=rep_b.id)

    assert results == []


async def test_list_leads_sales_rep_sees_unassigned_leads(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-unassigned-a@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-unassigned-b@example.com", UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-svc@example.com")
    await make_lead(owner_id=rep_b.id, email="other-svc@example.com")

    results, _total = await list_leads(db_session, requester=rep_a)

    ids = {lead.id for lead in results}
    assert unassigned.id in ids


async def test_list_leads_delivery_sme_sees_own_and_unassigned_leads(db_session: AsyncSession, make_lead):
    sme = await _make_user(db_session, "sme-svc@example.com", UserRole.DELIVERY_SME)
    other_rep = await _make_user(db_session, "rep-svc-other@example.com", UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-sme-svc@example.com")
    await make_lead(owner_id=other_rep.id, email="other-owned-sme-svc@example.com")

    results, _total = await list_leads(db_session, requester=sme)

    ids = {lead.id for lead in results}
    assert unassigned.id in ids


async def test_list_leads_manager_sees_all_when_no_owner_id_given(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-c@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-d@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager@example.com", UserRole.SALES_MANAGER)
    lead_a = await make_lead(owner_id=rep_a.id, email="lead-a@example.com")
    lead_b = await make_lead(owner_id=rep_b.id, email="lead-b@example.com")

    results, _total = await list_leads(db_session, requester=manager)

    ids = {lead.id for lead in results}
    assert ids == {lead_a.id, lead_b.id}


async def test_list_leads_manager_filters_by_owner_id_when_given(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-e@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-f@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager2@example.com", UserRole.SALES_MANAGER)
    lead_a = await make_lead(owner_id=rep_a.id, email="lead-e@example.com")
    await make_lead(owner_id=rep_b.id, email="lead-f@example.com")

    results, _total = await list_leads(db_session, requester=manager, owner_id=rep_a.id)

    assert [lead.id for lead in results] == [lead_a.id]


async def test_list_leads_filters_by_source(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-src@example.com", UserRole.SALES_REP)
    website_lead = await make_lead(
        owner_id=owner.id, email="src-website@example.com", source=LeadSource.WEBSITE
    )
    await make_lead(owner_id=owner.id, email="src-referral@example.com", source=LeadSource.REFERRAL)

    results, _total = await list_leads(db_session, requester=owner, source=LeadSource.WEBSITE)

    assert [lead.id for lead in results] == [website_lead.id]


async def test_list_leads_search_matches_company_name(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-search1@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search1@example.com", UserRole.SALES_REP)
    match = await make_lead(owner_id=owner.id, email="search-company@example.com", company="Rocketship Inc")
    await make_lead(owner_id=owner.id, email="no-match-company@example.com", company="Other Co")

    results, _total = await list_leads(db_session, requester=manager, search="rocketship")

    assert [lead.id for lead in results] == [match.id]


async def test_list_leads_search_matches_lead_name(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-search2@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search2@example.com", UserRole.SALES_REP)
    match = await make_lead(
        owner_id=owner.id, email="search-owner@example.com", first_name="Alexandra", last_name="Ng"
    )
    await make_lead(owner_id=owner.id, email="no-match-owner@example.com", first_name="Priya", last_name="Rao")

    results, _total = await list_leads(db_session, requester=manager, search="alexandra")

    assert [lead.id for lead in results] == [match.id]


async def test_list_leads_search_matches_email(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-search3@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search3@example.com", UserRole.SALES_REP)
    match = await make_lead(owner_id=owner.id, email="search-target@rocket.io")
    await make_lead(owner_id=owner.id, email="no-match@other.io")

    results, _total = await list_leads(db_session, requester=manager, search="rocket.io")

    assert [lead.id for lead in results] == [match.id]


async def test_get_lead_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "getter@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await get_lead(db_session, lead_id=999_999, requester=requester)


async def test_get_lead_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="forbidden-get@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await get_lead(db_session, lead_id=lead.id, requester=other_rep)


async def test_get_lead_succeeds_for_owning_sales_rep(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-ok@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="owned-get@example.com")

    fetched = await get_lead(db_session, lead_id=lead.id, requester=owner)

    assert fetched.id == lead.id


async def test_update_lead_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "updater@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await update_lead(
            db_session, lead_id=999_999, data=LeadUpsert(id=999_999, company="New Co"), requester=requester
        )


async def test_update_lead_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upd@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="forbidden-update@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await update_lead(
            db_session, lead_id=lead.id, data=LeadUpsert(id=lead.id, company="New Co"), requester=other_rep
        )


async def test_update_lead_applies_partial_changes(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-ok@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="partial-update@example.com", company="Old Co")

    updated = await update_lead(
        db_session, lead_id=lead.id, data=LeadUpsert(id=lead.id, company="New Co"), requester=owner
    )

    assert updated.company == "New Co"
    assert updated.email == "partial-update@example.com"  # untouched field preserved


async def test_update_lead_duplicate_email_raises(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-dup@example.com", UserRole.SALES_REP)
    await make_lead(owner_id=owner.id, email="taken@example.com")
    lead_to_update = await make_lead(owner_id=owner.id, email="not-taken@example.com")

    with pytest.raises(DuplicateLeadEmailError):
        await update_lead(
            db_session,
            lead_id=lead_to_update.id,
            data=LeadUpsert(id=lead_to_update.id, email="taken@example.com"),
            requester=owner,
        )


async def test_delete_lead_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "deleter@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await delete_lead(db_session, lead_id=999_999, requester=requester)


async def test_delete_lead_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-del-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-del@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="forbidden-delete@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await delete_lead(db_session, lead_id=lead.id, requester=other_rep)


async def test_delete_lead_removes_the_row(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-del-ok@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="to-be-deleted@example.com")
    lead_id = lead.id

    await delete_lead(db_session, lead_id=lead_id, requester=owner)

    with pytest.raises(LeadNotFoundError):
        await get_lead(db_session, lead_id=lead_id, requester=owner)


async def test_delete_lead_cascades_activities(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-del-cascade@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="cascade-delete@example.com")
    lead_id = lead.id
    db_session.add(LeadActivity(lead_id=lead_id, type=LeadActivityType.NOTE, note="call me", created_by=owner.id))
    await db_session.flush()

    await delete_lead(db_session, lead_id=lead_id, requester=owner)

    remaining = (
        await db_session.execute(select(LeadActivity).where(LeadActivity.lead_id == lead_id))
    ).scalars().all()
    assert remaining == []


async def test_get_lead_detail_last_contact_at_is_none_without_activities(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-no-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="no-activity@example.com")

    detail = await get_lead_detail(db_session, lead_id=lead.id, requester=owner)

    assert detail.last_contact_at is None


async def test_get_lead_detail_last_contact_at_is_latest_activity_updated_at(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-with-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="with-activity@example.com")
    older = LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="first", created_by=owner.id)
    newer = LeadActivity(lead_id=lead.id, type=LeadActivityType.CALL, note="second", created_by=owner.id)
    db_session.add_all([older, newer])
    await db_session.flush()
    older.updated_at = datetime(2024, 1, 1, tzinfo=None)
    newer.updated_at = datetime(2024, 6, 1, tzinfo=None)
    await db_session.flush()

    detail = await get_lead_detail(db_session, lead_id=lead.id, requester=owner)

    assert detail.last_contact_at == newer.updated_at
    assert detail.last_contact_at > older.updated_at


async def test_export_leads_scopes_to_owner_and_unassigned_for_non_view_all_role(
    db_session: AsyncSession, make_lead
):
    rep_a = await _make_user(db_session, "rep-export-svc@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "rep-export-svc-other@example.com", UserRole.SALES_REP)
    own = await make_lead(owner_id=rep_a.id, email="own-export-svc@example.com", company="Own Export Co")
    unassigned = await make_lead(owner_id=None, email="unassigned-export-svc@example.com")
    await make_lead(owner_id=other_rep.id, email="other-export-svc@example.com")

    rows = await export_leads(db_session, requester=rep_a)

    companies = {row["company"] for row in rows}
    assert own.company in companies
    assert unassigned.company in companies
    assert len(rows) == 2


async def test_export_leads_sees_all_for_view_all_role(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-export-svc@example.com", UserRole.SALES_MANAGER)
    rep = await _make_user(db_session, "rep-export-svc-2@example.com", UserRole.SALES_REP)
    await make_lead(owner_id=rep.id, email="rep-owned-export-svc@example.com")
    await make_lead(owner_id=None, email="unassigned-export-svc-2@example.com")

    rows = await export_leads(db_session, requester=manager)

    assert len(rows) >= 2
