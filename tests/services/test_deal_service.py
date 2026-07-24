"""app.services.deal_service: create/list/get/update/delete business rules,
stage-history logging, and cold-reason enforcement.

Covers: create_deal (account/stage-existence checks -- a deal's owner_id is
independent of the parent account's owner -- plus the initial stage-history
row written on creation); list_deals role-scoping (Sales Rep forced to own
deals even when passing a different owner_id, Manager sees everything,
filters by owner_id/account_id/stage_id/search, sort_by/sort_dir); board
grouping via list_deals_board; get/update/delete not-found and forbidden
checks; update_deal partial update, stage-history row written on stage
change with correct from/to, no history row when stage is absent from the
payload or unchanged, the cold-reason-required rule (driven by the stage's
is_cold flag) and its same-request escape hatch, and that an already-cold
deal with a reason already set tolerates unrelated patches; list_stage_history
ordering (oldest first); list_deals_for_account gated through the ACCOUNT's
ownership rather than individual deal ownership; export_deals rows.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier, NotificationType
from app.models.user import User
from tests.support.roles import UserRole, role_id_for
from app.schemas.deal import DealCreate, DealUpdate
from app.services.account_service import AccountAccessForbiddenError, AccountNotFoundError
from app.services.contact_service import ContactNotFoundError
from app.services.deal_service import (
    ColdReasonRequiredError,
    DealAccessForbiddenError,
    DealNotFoundError,
    DealStageNotFoundError,
    create_deal,
    delete_deal,
    export_deals,
    get_deal,
    get_deal_contact_ids,
    list_deals,
    list_deals_board,
    list_deals_for_account,
    list_deals_for_contact,
    list_stage_history,
    update_deal,
)


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test"
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


# --- create_deal --------------------------------------------------------


async def test_create_deal_succeeds_with_defaults(db_session: AsyncSession, make_account, make_deal_stage):
    owner = await _make_user(db_session, "owner-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Deal Co")
    stage = await make_deal_stage(name="Received Requirement")

    data = DealCreate(deal_name="New Deal", account_id=account.id, owner_id=owner.id, stage_id=stage.id)
    deal = await create_deal(db_session, data, requester=owner)

    assert deal.id is not None
    assert deal.deal_name == "New Deal"
    assert deal.account_id == account.id
    assert deal.owner_id == owner.id
    assert deal.currency == "USD"
    assert deal.stage_id == stage.id


async def test_create_deal_with_multiple_contact_ids(
    db_session: AsyncSession, make_account, make_deal_stage, make_contact
):
    owner = await _make_user(db_session, "owner-deal-contacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Deal Contacts Co")
    stage = await make_deal_stage(name="Contacts Stage")
    contact_a = await make_contact(account_id=account.id)
    contact_b = await make_contact(account_id=account.id)

    data = DealCreate(
        deal_name="Multi Contact Deal",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=stage.id,
        contact_ids=[contact_a.id, contact_b.id],
    )
    deal = await create_deal(db_session, data, requester=owner)

    linked_ids = set(await get_deal_contact_ids(db_session, deal.id))
    assert linked_ids == {contact_a.id, contact_b.id}


async def test_create_deal_with_no_contacts_has_empty_contact_ids(
    db_session: AsyncSession, make_account, make_deal_stage
):
    owner = await _make_user(db_session, "owner-deal-nocontacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Deal No Contacts Co")
    stage = await make_deal_stage(name="No Contacts Stage")

    data = DealCreate(deal_name="No Contact Deal", account_id=account.id, owner_id=owner.id, stage_id=stage.id)
    deal = await create_deal(db_session, data, requester=owner)

    assert await get_deal_contact_ids(db_session, deal.id) == []


async def test_create_deal_raises_not_found_for_missing_contact(
    db_session: AsyncSession, make_account, make_deal_stage
):
    owner = await _make_user(db_session, "owner-deal-badcontact@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Deal Bad Contact Co")
    stage = await make_deal_stage(name="Bad Contact Stage")

    data = DealCreate(
        deal_name="Bad Contact Deal",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=stage.id,
        contact_ids=[999_999],
    )

    with pytest.raises(ContactNotFoundError):
        await create_deal(db_session, data, requester=owner)


async def test_create_deal_raises_not_found_for_missing_account(
    db_session: AsyncSession, make_deal_stage
):
    owner = await _make_user(db_session, "owner-deal-404@example.com", UserRole.SALES_REP)
    stage = await make_deal_stage()

    data = DealCreate(deal_name="Orphan Deal", account_id=999_999, owner_id=owner.id, stage_id=stage.id)

    with pytest.raises(AccountNotFoundError):
        await create_deal(db_session, data, requester=owner)


async def test_create_deal_raises_stage_not_found_for_missing_stage(
    db_session: AsyncSession, make_account
):
    owner = await _make_user(db_session, "owner-deal-stage-404@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Missing Stage Co")

    data = DealCreate(deal_name="Stageless Deal", account_id=account.id, owner_id=owner.id, stage_id=999_999)

    with pytest.raises(DealStageNotFoundError):
        await create_deal(db_session, data, requester=owner)


async def test_create_deal_succeeds_against_account_owned_by_a_different_user(
    db_session: AsyncSession, make_account, make_deal_stage
):
    # Account existence is checked, but NOT account ownership -- a deal's
    # owner_id is independent of who owns the parent account.
    rep_a = await _make_user(db_session, "rep-a-deal-cross@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-deal-cross@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep_b.id, company="Cross Owned Co")
    stage = await make_deal_stage()

    data = DealCreate(
        deal_name="Cross Owner Deal", account_id=account.id, owner_id=rep_a.id, stage_id=stage.id
    )
    deal = await create_deal(db_session, data, requester=rep_a)

    assert deal.account_id == account.id
    assert deal.owner_id == rep_a.id


async def test_create_deal_writes_initial_stage_history_row(
    db_session: AsyncSession, make_account, make_deal_stage
):
    owner = await _make_user(db_session, "owner-deal-hist@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="History Create Co")
    stage = await make_deal_stage(name="Qualified to buy")

    data = DealCreate(
        deal_name="History Deal",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=stage.id,
    )
    deal = await create_deal(db_session, data, requester=owner)

    history = await list_stage_history(db_session, deal.id, requester=owner)

    assert len(history) == 1
    assert history[0].from_stage_id is None
    assert history[0].to_stage_id == stage.id
    assert history[0].changed_by == owner.id


async def test_create_deal_raises_cold_reason_required_when_stage_is_cold_without_reason(
    db_session: AsyncSession, make_account, make_deal_stage
):
    owner = await _make_user(db_session, "owner-create-cold-required@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Cold Required Co")
    cold_stage = await make_deal_stage(name="Cold deals", is_cold=True)

    data = DealCreate(
        deal_name="Cold From Birth",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=cold_stage.id,
    )

    with pytest.raises(ColdReasonRequiredError):
        await create_deal(db_session, data, requester=owner)


async def test_create_deal_succeeds_with_cold_stage_and_reason_provided(
    db_session: AsyncSession, make_account, make_deal_stage
):
    owner = await _make_user(db_session, "owner-create-cold-ok@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Create Cold Ok Co")
    cold_stage = await make_deal_stage(name="Cold deals", is_cold=True)

    data = DealCreate(
        deal_name="Cold From Birth Ok",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=cold_stage.id,
        cold_reason="Never had budget",
    )
    deal = await create_deal(db_session, data, requester=owner)

    assert deal.stage_id == cold_stage.id
    assert deal.cold_reason == "Never had budget"


# --- list_deals ----------------------------------------------------------


async def test_list_deals_sales_rep_only_sees_own_deals_even_with_owner_id_param(
    db_session: AsyncSession, make_account, make_deal
):
    rep_a = await _make_user(db_session, "rep-a-deal-list@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-deal-list@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep_a.id, company="List Deal Co")
    own_deal = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="Own Deal")
    await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="Other Deal")

    results, _total = await list_deals(db_session, requester=rep_a, owner_id=rep_b.id)

    assert [deal.id for deal in results] == [own_deal.id]


async def test_list_deals_manager_sees_all_when_no_filter(
    db_session: AsyncSession, make_account, make_deal
):
    rep_a = await _make_user(db_session, "rep-c-deal-list@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-d-deal-list@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-deal-list@example.com", UserRole.SALES_MANAGER)
    account = await make_account(owner_id=rep_a.id, company="Manager List Co")
    deal_a = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="Deal A")
    deal_b = await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="Deal B")

    results, _total = await list_deals(db_session, requester=manager)

    ids = {deal.id for deal in results}
    assert ids == {deal_a.id, deal_b.id}


async def test_list_deals_filters_by_owner_id(db_session: AsyncSession, make_account, make_deal):
    manager = await _make_user(db_session, "manager-deal-owner@example.com", UserRole.SALES_MANAGER)
    rep_a = await _make_user(db_session, "rep-e-deal-owner@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-f-deal-owner@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep_a.id, company="Owner Filter Co")
    deal_a = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="Owner Deal A")
    await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="Owner Deal B")

    results, _total = await list_deals(db_session, requester=manager, owner_id=rep_a.id)

    assert [deal.id for deal in results] == [deal_a.id]


async def test_list_deals_filters_by_account_id(db_session: AsyncSession, make_account, make_deal):
    manager = await _make_user(db_session, "manager-deal-acct@example.com", UserRole.SALES_MANAGER)
    rep = await _make_user(db_session, "rep-deal-acct@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=rep.id, company="Acct Filter Co A")
    account_b = await make_account(owner_id=rep.id, company="Acct Filter Co B")
    deal_a = await make_deal(account_id=account_a.id, owner_id=rep.id, deal_name="Acct Deal A")
    await make_deal(account_id=account_b.id, owner_id=rep.id, deal_name="Acct Deal B")

    results, _total = await list_deals(db_session, requester=manager, account_id=account_a.id)

    assert [deal.id for deal in results] == [deal_a.id]


async def test_list_deals_filters_by_stage_id(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    rep = await _make_user(db_session, "rep-deal-stage@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Stage Filter Co")
    stage_a = await make_deal_stage(name="Eval Stage")
    stage_b = await make_deal_stage(name="Proposal Stage")
    eval_deal = await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Eval Deal", stage_id=stage_a.id
    )
    await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Proposal Deal", stage_id=stage_b.id
    )

    results, _total = await list_deals(db_session, requester=rep, stage_id=stage_a.id)

    assert [deal.id for deal in results] == [eval_deal.id]


async def test_list_deals_filters_by_search_matches_deal_name(
    db_session: AsyncSession, make_account, make_deal
):
    rep = await _make_user(db_session, "rep-deal-search@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Search Filter Co")
    match = await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Rocketship Expansion")
    await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Unrelated Deal")

    results, _total = await list_deals(db_session, requester=rep, search="rocketship")

    assert [deal.id for deal in results] == [match.id]


async def test_list_deals_filters_by_search_matches_account_company(
    db_session: AsyncSession, make_account, make_deal
):
    rep = await _make_user(db_session, "rep-deal-search-acct@example.com", UserRole.SALES_REP)
    account_match = await make_account(owner_id=rep.id, company="Nebula Dynamics")
    account_other = await make_account(owner_id=rep.id, company="Other Co")
    match = await make_deal(account_id=account_match.id, owner_id=rep.id, deal_name="Deal One")
    await make_deal(account_id=account_other.id, owner_id=rep.id, deal_name="Deal Two")

    results, _total = await list_deals(db_session, requester=rep, search="nebula")

    assert [deal.id for deal in results] == [match.id]


async def test_list_deals_sorts_by_value_ascending(db_session: AsyncSession, make_account, make_deal):
    rep = await _make_user(db_session, "rep-deal-sort@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Sort Deal Co")
    low = await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Low Deal", value=100.0)
    high = await make_deal(account_id=account.id, owner_id=rep.id, deal_name="High Deal", value=999.0)

    results, _total = await list_deals(db_session, requester=rep, sort_by="value", sort_dir="asc")

    assert [deal.id for deal in results] == [low.id, high.id]


# --- list_deals_board ------------------------------------------------------


async def test_list_deals_board_groups_by_stage_ordered_by_sort_order(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    rep = await _make_user(db_session, "rep-deal-board@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Board Deal Co")
    stage_first = await make_deal_stage(name="Board Stage First", sort_order=0)
    stage_second = await make_deal_stage(name="Board Stage Second", sort_order=1)
    await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Board Deal A", stage_id=stage_second.id, value=100.0
    )
    await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Board Deal B", stage_id=stage_first.id, value=50.0
    )
    await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Board Deal C", stage_id=stage_first.id, value=25.0
    )

    columns = await list_deals_board(db_session, requester=rep)

    assert [stage.id for stage, _deals in columns] == [stage_first.id, stage_second.id]
    first_column_deals = dict(columns)[stage_first]
    assert len(first_column_deals) == 2
    assert sum(deal.value for deal in first_column_deals) == 75.0


async def test_list_deals_board_has_no_pagination_returns_all_matching(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    rep = await _make_user(db_session, "rep-deal-board-all@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Board All Deal Co")
    stage = await make_deal_stage(name="Board All Stage")
    for i in range(25):
        await make_deal(
            account_id=account.id, owner_id=rep.id, deal_name=f"Board Deal {i}", stage_id=stage.id
        )

    columns = await list_deals_board(db_session, requester=rep)

    assert len(columns) == 1
    assert len(columns[0][1]) == 25


# --- get_deal --------------------------------------------------------------


async def test_get_deal_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "getter-deal@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await get_deal(db_session, deal_id=999_999, requester=requester)


async def test_get_deal_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-forbidden-deal@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Get Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Forbidden Deal")

    with pytest.raises(DealAccessForbiddenError):
        await get_deal(db_session, deal_id=deal.id, requester=other_rep)


async def test_get_deal_succeeds_for_owning_sales_rep(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-ok-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Owned Get Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Owned Deal")

    fetched = await get_deal(db_session, deal_id=deal.id, requester=owner)

    assert fetched.id == deal.id


async def test_get_deal_succeeds_for_manager_regardless_of_owner(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-for-manager-deal@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-get-deal@example.com", UserRole.SALES_MANAGER)
    account = await make_account(owner_id=owner.id, company="Manager Get Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Manager Visible Deal")

    fetched = await get_deal(db_session, deal_id=deal.id, requester=manager)

    assert fetched.id == deal.id


# --- update_deal -----------------------------------------------------------


async def test_update_deal_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "updater-deal@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await update_deal(
            db_session, deal_id=999_999, data=DealUpdate(deal_name="New Name"), requester=requester
        )


async def test_update_deal_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upd-forbidden-deal@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upd-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Update Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Forbidden Update Deal")

    with pytest.raises(DealAccessForbiddenError):
        await update_deal(
            db_session, deal_id=deal.id, data=DealUpdate(deal_name="New Name"), requester=other_rep
        )


async def test_update_deal_applies_partial_changes(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-upd-ok-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Partial Update Deal Co")
    deal = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Old Deal Name", value=1000.0
    )

    updated = await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(deal_name="New Deal Name"), requester=owner
    )

    assert updated.deal_name == "New Deal Name"
    assert updated.value == 1000.0  # untouched field preserved


async def test_update_deal_can_set_tier_and_contacts(
    db_session: AsyncSession, make_account, make_deal, make_contact
):
    owner = await _make_user(db_session, "owner-upd-tier-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Tier Update Deal Co")
    contact_a = await make_contact(account_id=account.id)
    contact_b = await make_contact(account_id=account.id)
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Tier Deal")

    updated = await update_deal(
        db_session,
        deal_id=deal.id,
        data=DealUpdate(tier=LeadTier.SILVER, contact_ids=[contact_a.id, contact_b.id]),
        requester=owner,
    )

    assert updated.tier == LeadTier.SILVER
    linked_ids = set(await get_deal_contact_ids(db_session, updated.id))
    assert linked_ids == {contact_a.id, contact_b.id}


async def test_update_deal_omitting_contact_ids_leaves_links_untouched(
    db_session: AsyncSession, make_account, make_deal, make_contact
):
    owner = await _make_user(db_session, "owner-upd-omit-contacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Omit Contacts Deal Co")
    contact = await make_contact(account_id=account.id)
    deal = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Omit Contacts Deal", contact_ids=[contact.id]
    )

    updated = await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(deal_name="Renamed"), requester=owner
    )

    assert updated.deal_name == "Renamed"
    assert await get_deal_contact_ids(db_session, updated.id) == [contact.id]


async def test_update_deal_with_empty_contact_ids_clears_links(
    db_session: AsyncSession, make_account, make_deal, make_contact
):
    owner = await _make_user(db_session, "owner-upd-clear-contacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Clear Contacts Deal Co")
    contact = await make_contact(account_id=account.id)
    deal = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Clear Contacts Deal", contact_ids=[contact.id]
    )

    updated = await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(contact_ids=[]), requester=owner
    )

    assert await get_deal_contact_ids(db_session, updated.id) == []


async def test_update_deal_raises_not_found_for_nonexistent_contact_id(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upd-bad-contact@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Bad Contact Update Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Bad Contact Deal")

    with pytest.raises(ContactNotFoundError):
        await update_deal(
            db_session, deal_id=deal.id, data=DealUpdate(contact_ids=[999999]), requester=owner
        )


async def test_update_deal_raises_not_found_for_nonexistent_account_id(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upd-bad-account@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Reassign Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Reassign Deal")

    with pytest.raises(AccountNotFoundError):
        await update_deal(
            db_session, deal_id=deal.id, data=DealUpdate(account_id=999_999), requester=owner
        )


async def test_update_deal_raises_stage_not_found_for_nonexistent_stage_id(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upd-bad-stage@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Reassign Stage Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Reassign Stage Deal")

    with pytest.raises(DealStageNotFoundError):
        await update_deal(
            db_session, deal_id=deal.id, data=DealUpdate(stage_id=999_999), requester=owner
        )


async def test_update_deal_writes_stage_history_row_on_stage_change(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-upd-stage-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Stage Change Deal Co")
    stage_from = await make_deal_stage(name="From Stage")
    stage_to = await make_deal_stage(name="To Stage")
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Stage Change Deal",
        stage_id=stage_from.id,
    )

    await update_deal(
        db_session,
        deal_id=deal.id,
        data=DealUpdate(stage_id=stage_to.id, note="Qualified after call"),
        requester=owner,
    )

    history = await list_stage_history(db_session, deal.id, requester=owner)

    assert len(history) == 1
    assert history[0].from_stage_id == stage_from.id
    assert history[0].to_stage_id == stage_to.id
    assert history[0].changed_by == owner.id
    assert history[0].note == "Qualified after call"


async def test_update_deal_stage_change_notifies_owner(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    from app.models.notification import Notification

    owner = await _make_user(db_session, "owner-notif-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Notify Deal Co")
    stage_from = await make_deal_stage(name="Notify From Stage")
    stage_to = await make_deal_stage(name="Notify To Stage")
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Notify Deal",
        stage_id=stage_from.id,
    )

    await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(stage_id=stage_to.id), requester=owner
    )

    result = await db_session.execute(
        select(Notification).where(
            Notification.recipient_id == owner.id, Notification.type == NotificationType.DEAL_STAGE_CHANGED
        )
    )
    notification = result.scalar_one()
    assert notification.entity_id == deal.id
    assert stage_to.name in notification.body


async def test_update_deal_does_not_write_stage_history_when_stage_absent_from_payload(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upd-nostage-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="No Stage Change Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="No Stage Change Deal")

    await update_deal(db_session, deal_id=deal.id, data=DealUpdate(value=2000.0), requester=owner)

    history = await list_stage_history(db_session, deal.id, requester=owner)

    assert history == []


async def test_update_deal_does_not_write_stage_history_when_stage_unchanged(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-upd-samestage-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Same Stage Deal Co")
    stage = await make_deal_stage(name="Same Stage")
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Same Stage Deal",
        stage_id=stage.id,
    )

    await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(stage_id=stage.id), requester=owner
    )

    history = await list_stage_history(db_session, deal.id, requester=owner)

    assert history == []


async def test_update_deal_raises_cold_reason_required_when_stage_set_to_cold_without_reason(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-cold-required-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Cold Required Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Cold Candidate Deal")
    cold_stage = await make_deal_stage(name="Cold Required Stage", is_cold=True)

    with pytest.raises(ColdReasonRequiredError):
        await update_deal(
            db_session, deal_id=deal.id, data=DealUpdate(stage_id=cold_stage.id), requester=owner
        )


async def test_update_deal_succeeds_when_cold_reason_provided_in_same_request(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-cold-ok-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Cold Ok Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Cold Ok Deal")
    cold_stage = await make_deal_stage(name="Cold Ok Stage", is_cold=True)

    updated = await update_deal(
        db_session,
        deal_id=deal.id,
        data=DealUpdate(stage_id=cold_stage.id, cold_reason="Budget cut"),
        requester=owner,
    )

    assert updated.stage_id == cold_stage.id
    assert updated.cold_reason == "Budget cut"


async def test_update_deal_unrelated_field_does_not_retrigger_cold_reason_check(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-cold-unrelated-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Cold Unrelated Deal Co")
    cold_stage = await make_deal_stage(name="Cold Unrelated Stage", is_cold=True)
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Already Cold Deal",
        stage_id=cold_stage.id,
        cold_reason="Already set",
    )

    updated = await update_deal(db_session, deal_id=deal.id, data=DealUpdate(value=500.0), requester=owner)

    assert updated.value == 500.0
    assert updated.stage_id == cold_stage.id
    assert updated.cold_reason == "Already set"


# --- delete_deal -----------------------------------------------------------


async def test_delete_deal_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "deleter-deal@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await delete_deal(db_session, deal_id=999_999, requester=requester)


async def test_delete_deal_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-del-forbidden-deal@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-del-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Delete Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Forbidden Delete Deal")

    with pytest.raises(DealAccessForbiddenError):
        await delete_deal(db_session, deal_id=deal.id, requester=other_rep)


async def test_delete_deal_removes_the_row(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-del-ok-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Ok Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="To Be Deleted Deal")
    deal_id = deal.id

    await delete_deal(db_session, deal_id=deal_id, requester=owner)

    with pytest.raises(DealNotFoundError):
        await get_deal(db_session, deal_id=deal_id, requester=owner)


# --- list_stage_history ------------------------------------------------------


async def test_list_stage_history_raises_not_found_for_missing_deal(db_session: AsyncSession):
    requester = await _make_user(db_session, "history-404-deal@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await list_stage_history(db_session, deal_id=999_999, requester=requester)


async def test_list_stage_history_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-history-forbidden-deal@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-history-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="History Forbidden Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="History Forbidden Deal")

    with pytest.raises(DealAccessForbiddenError):
        await list_stage_history(db_session, deal_id=deal.id, requester=other_rep)


async def test_list_stage_history_returns_rows_ordered_oldest_first(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    owner = await _make_user(db_session, "owner-history-order-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="History Order Deal Co")
    stage_1 = await make_deal_stage(name="History Order Stage 1")
    stage_2 = await make_deal_stage(name="History Order Stage 2")
    stage_3 = await make_deal_stage(name="History Order Stage 3")
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="History Order Deal",
        stage_id=stage_1.id,
    )

    await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(stage_id=stage_2.id), requester=owner
    )
    await update_deal(
        db_session, deal_id=deal.id, data=DealUpdate(stage_id=stage_3.id), requester=owner
    )

    history = await list_stage_history(db_session, deal.id, requester=owner)

    assert [row.to_stage_id for row in history] == [stage_2.id, stage_3.id]
    assert history[0].created_at <= history[1].created_at


# --- list_deals_for_account --------------------------------------------------


async def test_list_deals_for_account_raises_not_found_for_missing_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "account-deals-404@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await list_deals_for_account(db_session, account_id=999_999, requester=requester)


async def test_list_deals_for_account_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    # Gated on the ACCOUNT's ownership, not the individual deal's owner_id.
    account_owner = await _make_user(db_session, "account-owner-deals@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-account-deals@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=account_owner.id, company="Account Gated Deal Co")
    await make_deal(account_id=account.id, owner_id=account_owner.id, deal_name="Gated Deal")

    with pytest.raises(AccountAccessForbiddenError):
        await list_deals_for_account(db_session, account_id=account.id, requester=other_rep)


async def test_list_deals_for_account_returns_deals_scoped_to_that_account(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-scoped-deals@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Scoped Deal Co A")
    account_b = await make_account(owner_id=owner.id, company="Scoped Deal Co B")
    deal_a = await make_deal(account_id=account_a.id, owner_id=owner.id, deal_name="Scoped Deal A")
    await make_deal(account_id=account_b.id, owner_id=owner.id, deal_name="Scoped Deal B")

    results = await list_deals_for_account(db_session, account_id=account_a.id, requester=owner)

    assert [deal.id for deal in results] == [deal_a.id]


# --- list_deals_for_contact ---------------------------------------------------


async def test_list_deals_for_contact_raises_not_found_for_missing_contact(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await list_deals_for_contact(db_session, contact_id=999_999)


async def test_list_deals_for_contact_returns_empty_list_when_no_deals_linked(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-contact-deals-empty@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="No Deals Co")
    contact = await make_contact(account_id=account.id)

    results = await list_deals_for_contact(db_session, contact_id=contact.id)

    assert results == []


async def test_list_deals_for_contact_returns_linked_deals(
    db_session: AsyncSession, make_account, make_contact, make_deal
):
    owner = await _make_user(db_session, "owner-contact-deals@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Contact Deals Co")
    contact = await make_contact(account_id=account.id)
    deal_a = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Contact Deal A", contact_ids=[contact.id]
    )
    deal_b = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Contact Deal B", contact_ids=[contact.id]
    )

    results = await list_deals_for_contact(db_session, contact_id=contact.id)

    assert {deal.id for deal in results} == {deal_a.id, deal_b.id}


async def test_list_deals_for_contact_excludes_deals_for_other_contacts(
    db_session: AsyncSession, make_account, make_contact, make_deal
):
    owner = await _make_user(db_session, "owner-contact-deals-excl@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Contact Deals Excl Co")
    contact = await make_contact(account_id=account.id)
    other_contact = await make_contact(account_id=account.id, email="other-contact-deals-excl@example.com")
    await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Other's Deal", contact_ids=[other_contact.id]
    )

    results = await list_deals_for_contact(db_session, contact_id=contact.id)

    assert results == []


# --- export_deals ------------------------------------------------------------


async def test_export_deals_returns_rows_spanning_all_accounts(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-export-deal@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Export Deal Co A")
    account_b = await make_account(owner_id=owner.id, company="Export Deal Co B")
    deal_a = await make_deal(account_id=account_a.id, owner_id=owner.id, deal_name="Export Deal A")
    deal_b = await make_deal(account_id=account_b.id, owner_id=owner.id, deal_name="Export Deal B")

    rows = await export_deals(db_session, requester=owner)

    names = {row["deal_name"] for row in rows}
    assert {deal_a.deal_name, deal_b.deal_name} <= names


async def test_export_deals_scopes_to_requester_when_not_view_all(
    db_session: AsyncSession, make_account, make_deal
):
    rep_a = await _make_user(db_session, "rep-a-export-deal@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-export-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep_a.id, company="Export Scope Co")
    own_deal = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="Own Export Deal")
    await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="Other Export Deal")

    rows = await export_deals(db_session, requester=rep_a)

    assert [row["deal_name"] for row in rows] == [own_deal.deal_name]


async def test_export_deals_includes_expected_columns(
    db_session: AsyncSession, make_account, make_deal, make_contact
):
    owner = await _make_user(db_session, "owner-export-cols-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Export Cols Co")
    contact_a = await make_contact(account_id=account.id, first_name="Cara", last_name="Contact")
    contact_b = await make_contact(account_id=account.id, first_name="Dara", last_name="Contact")
    deal = await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Export Cols Deal",
        contact_ids=[contact_a.id, contact_b.id],
        value=500.0,
        currency="EUR",
        tier=LeadTier.GOLD,
    )

    rows = await export_deals(db_session, requester=owner)

    row = next(r for r in rows if r["deal_name"] == deal.deal_name)
    assert row["account"] == account.company
    assert row["contact"] == "Cara Contact, Dara Contact"
    assert row["value"] == 500.0
    assert row["currency"] == "EUR"
    assert row["tier"] == "gold"
    assert row["owner"] == owner.first_name


async def test_export_deals_contact_is_none_when_no_contacts(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-export-nocontact-deal@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Export No Contact Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="No Contact Deal")

    rows = await export_deals(db_session, requester=owner)

    row = next(r for r in rows if r["deal_name"] == deal.deal_name)
    assert row["contact"] is None
