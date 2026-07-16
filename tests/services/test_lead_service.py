"""app.services.lead_service: create/list/get/update/delete business rules.

Covers: successful create; duplicate-email guard; list_leads role-scoping
(Sales Rep forced to own leads, Manager/Admin see all or filtered);
source/tier exact-match filters; search across company + owner name;
not-found/forbidden checks on get/update/delete; partial update; delete.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource, LeadTier
from app.models.user import User, UserRole
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services.lead_service import (
    DuplicateLeadEmailError,
    LeadAccessForbiddenError,
    LeadNotFoundError,
    create_lead,
    delete_lead,
    get_lead,
    list_leads,
    update_lead,
)


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_lead_succeeds(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner@example.com", UserRole.SALES_REP)

    data = LeadCreate(
        first_name="Jane",
        company="Acme Corp",
        email="jane@acme.com",
        source=LeadSource.WEBSITE,
        tier=LeadTier.GOLD,
        owner_id=owner.id,
    )
    lead = await create_lead(db_session, data)

    assert lead.id is not None
    assert lead.email == "jane@acme.com"
    assert lead.owner_id == owner.id


async def test_create_lead_duplicate_email_raises(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-dup@example.com", UserRole.SALES_REP)

    data = LeadCreate(
        first_name="Jane",
        company="Acme Corp",
        email="dup@acme.com",
        source=LeadSource.WEBSITE,
        tier=LeadTier.GOLD,
        owner_id=owner.id,
    )
    await create_lead(db_session, data)

    dup_data = LeadCreate(
        first_name="John",
        company="Other Corp",
        email="dup@acme.com",
        source=LeadSource.REFERRAL,
        tier=LeadTier.SILVER,
        owner_id=owner.id,
    )
    with pytest.raises(DuplicateLeadEmailError):
        await create_lead(db_session, dup_data)


async def test_create_lead_bad_owner_id_raises_integrity_error_not_duplicate_email(db_session: AsyncSession):
    # A foreign-key violation on owner_id must not be mislabeled as a
    # duplicate-email conflict just because both errors are IntegrityErrors.
    data = LeadCreate(
        first_name="Jane",
        company="Acme Corp",
        email="unique-email-bad-owner@acme.com",
        source=LeadSource.WEBSITE,
        tier=LeadTier.GOLD,
        owner_id=999_999_999,
    )
    with pytest.raises(IntegrityError):
        await create_lead(db_session, data)


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

    results = await list_leads(db_session, requester=rep_a, owner_id=rep_b.id)

    assert results == []


async def test_list_leads_sales_rep_sees_unassigned_leads(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-unassigned-a@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-unassigned-b@example.com", UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-svc@example.com")
    await make_lead(owner_id=rep_b.id, email="other-svc@example.com")

    results = await list_leads(db_session, requester=rep_a)

    ids = {lead.id for lead in results}
    assert unassigned.id in ids


async def test_list_leads_delivery_sme_sees_own_and_unassigned_leads(db_session: AsyncSession, make_lead):
    sme = await _make_user(db_session, "sme-svc@example.com", UserRole.DELIVERY_SME)
    other_rep = await _make_user(db_session, "rep-svc-other@example.com", UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-sme-svc@example.com")
    await make_lead(owner_id=other_rep.id, email="other-owned-sme-svc@example.com")

    results = await list_leads(db_session, requester=sme)

    ids = {lead.id for lead in results}
    assert unassigned.id in ids


async def test_list_leads_manager_sees_all_when_no_owner_id_given(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-c@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-d@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager@example.com", UserRole.SALES_MANAGER)
    lead_a = await make_lead(owner_id=rep_a.id, email="lead-a@example.com")
    lead_b = await make_lead(owner_id=rep_b.id, email="lead-b@example.com")

    results = await list_leads(db_session, requester=manager)

    ids = {lead.id for lead in results}
    assert ids == {lead_a.id, lead_b.id}


async def test_list_leads_manager_filters_by_owner_id_when_given(db_session: AsyncSession, make_lead):
    rep_a = await _make_user(db_session, "rep-e@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-f@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager2@example.com", UserRole.SALES_MANAGER)
    lead_a = await make_lead(owner_id=rep_a.id, email="lead-e@example.com")
    await make_lead(owner_id=rep_b.id, email="lead-f@example.com")

    results = await list_leads(db_session, requester=manager, owner_id=rep_a.id)

    assert [lead.id for lead in results] == [lead_a.id]


async def test_list_leads_filters_by_source(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-src@example.com", UserRole.SALES_REP)
    website_lead = await make_lead(
        owner_id=owner.id, email="src-website@example.com", source=LeadSource.WEBSITE
    )
    await make_lead(owner_id=owner.id, email="src-referral@example.com", source=LeadSource.REFERRAL)

    results = await list_leads(db_session, requester=owner, source=LeadSource.WEBSITE)

    assert [lead.id for lead in results] == [website_lead.id]


async def test_list_leads_filters_by_tier(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-tier@example.com", UserRole.SALES_REP)
    gold_lead = await make_lead(owner_id=owner.id, email="tier-gold@example.com", tier=LeadTier.GOLD)
    await make_lead(owner_id=owner.id, email="tier-bronze@example.com", tier=LeadTier.BRONZE)

    results = await list_leads(db_session, requester=owner, tier=LeadTier.GOLD)

    assert [lead.id for lead in results] == [gold_lead.id]


async def test_list_leads_search_matches_company_name(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-search1@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search1@example.com", UserRole.SALES_REP)
    match = await make_lead(owner_id=owner.id, email="search-company@example.com", company="Rocketship Inc")
    await make_lead(owner_id=owner.id, email="no-match-company@example.com", company="Other Co")

    results = await list_leads(db_session, requester=manager, search="rocketship")

    assert [lead.id for lead in results] == [match.id]


async def test_list_leads_search_matches_owner_name(db_session: AsyncSession, make_lead):
    manager = await _make_user(db_session, "manager-search2@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(
        db_session, "owner-search2@example.com", UserRole.SALES_REP, first_name="Alexandra", last_name="Ng"
    )
    other_owner = await _make_user(db_session, "owner-search3@example.com", UserRole.SALES_REP)
    match = await make_lead(owner_id=owner.id, email="search-owner@example.com")
    await make_lead(owner_id=other_owner.id, email="no-match-owner@example.com")

    results = await list_leads(db_session, requester=manager, search="alexandra")

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
        await update_lead(db_session, lead_id=999_999, data=LeadUpdate(company="New Co"), requester=requester)


async def test_update_lead_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upd@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="forbidden-update@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await update_lead(
            db_session, lead_id=lead.id, data=LeadUpdate(company="New Co"), requester=other_rep
        )


async def test_update_lead_applies_partial_changes(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-ok@example.com", UserRole.SALES_REP)
    lead = await make_lead(
        owner_id=owner.id, email="partial-update@example.com", company="Old Co", tier=LeadTier.BRONZE
    )

    updated = await update_lead(
        db_session, lead_id=lead.id, data=LeadUpdate(company="New Co"), requester=owner
    )

    assert updated.company == "New Co"
    assert updated.tier == LeadTier.BRONZE  # untouched field preserved
    assert updated.email == "partial-update@example.com"  # untouched field preserved


async def test_update_lead_duplicate_email_raises(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-upd-dup@example.com", UserRole.SALES_REP)
    await make_lead(owner_id=owner.id, email="taken@example.com")
    lead_to_update = await make_lead(owner_id=owner.id, email="not-taken@example.com")

    with pytest.raises(DuplicateLeadEmailError):
        await update_lead(
            db_session, lead_id=lead_to_update.id, data=LeadUpdate(email="taken@example.com"), requester=owner
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
