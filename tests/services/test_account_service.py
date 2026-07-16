"""app.services.account_service: create/list/get/update/delete business rules,
plus Lead -> Account conversion.

Covers: successful create (no duplicate-check, no unique constraint on this
table); list_accounts role-scoping (Sales Rep forced to own accounts even
when passing a different owner_id, Manager sees all or filtered); tier
exact-match filter; search across company + owner name; not-found/forbidden
checks on get/update/delete; partial update; delete. Plus
convert_lead_to_account: copies fields from the lead and sets
source_lead_id, marks the lead converted, rejects a second conversion,
reuses lead_service's not-found/forbidden checks, and honors explicit
tier/owner_id overrides.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User, UserRole
from app.schemas.account import AccountCreate, AccountUpdate
from app.services.account_service import (
    AccountAccessForbiddenError,
    AccountNotFoundError,
    LeadAlreadyConvertedError,
    LeadMissingFieldsForConversionError,
    convert_lead_to_account,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)
from app.services.lead_service import LeadAccessForbiddenError, LeadNotFoundError


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_account_succeeds(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-acc@example.com", UserRole.SALES_REP)

    data = AccountCreate(company="Acme Corp", tier=LeadTier.GOLD, owner_id=owner.id)
    account = await create_account(db_session, data)

    assert account.id is not None
    assert account.company == "Acme Corp"
    assert account.owner_id == owner.id
    assert account.source_lead_id is None


async def test_list_accounts_sales_rep_only_sees_own_accounts_even_with_owner_id_param(
    db_session: AsyncSession, make_account
):
    rep_a = await _make_user(db_session, "rep-a-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-acc@example.com", UserRole.SALES_REP)
    own_account = await make_account(owner_id=rep_a.id, company="Own Co")
    await make_account(owner_id=rep_b.id, company="Other Co")

    results = await list_accounts(db_session, requester=rep_a, owner_id=rep_b.id)

    assert [account.id for account in results] == [own_account.id]


async def test_list_accounts_manager_sees_all_when_no_owner_id_given(db_session: AsyncSession, make_account):
    rep_a = await _make_user(db_session, "rep-c-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-d-acc@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-acc@example.com", UserRole.SALES_MANAGER)
    account_a = await make_account(owner_id=rep_a.id, company="Co A")
    account_b = await make_account(owner_id=rep_b.id, company="Co B")

    results = await list_accounts(db_session, requester=manager)

    ids = {account.id for account in results}
    assert ids == {account_a.id, account_b.id}


async def test_list_accounts_manager_filters_by_owner_id_when_given(db_session: AsyncSession, make_account):
    rep_a = await _make_user(db_session, "rep-e-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-f-acc@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager2-acc@example.com", UserRole.SALES_MANAGER)
    account_a = await make_account(owner_id=rep_a.id, company="Co E")
    await make_account(owner_id=rep_b.id, company="Co F")

    results = await list_accounts(db_session, requester=manager, owner_id=rep_a.id)

    assert [account.id for account in results] == [account_a.id]


async def test_list_accounts_filters_by_tier(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-tier-acc@example.com", UserRole.SALES_REP)
    gold_account = await make_account(owner_id=owner.id, company="Tier Gold Co", tier=LeadTier.GOLD)
    await make_account(owner_id=owner.id, company="Tier Bronze Co", tier=LeadTier.BRONZE)

    results = await list_accounts(db_session, requester=owner, tier=LeadTier.GOLD)

    assert [account.id for account in results] == [gold_account.id]


async def test_list_accounts_search_matches_company_name(db_session: AsyncSession, make_account):
    manager = await _make_user(db_session, "manager-search-acc1@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search-acc1@example.com", UserRole.SALES_REP)
    match = await make_account(owner_id=owner.id, company="Rocketship Inc")
    await make_account(owner_id=owner.id, company="Other Co")

    results = await list_accounts(db_session, requester=manager, search="rocketship")

    assert [account.id for account in results] == [match.id]


async def test_list_accounts_search_matches_owner_name(db_session: AsyncSession, make_account):
    manager = await _make_user(db_session, "manager-search-acc2@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(
        db_session,
        "owner-search-acc2@example.com",
        UserRole.SALES_REP,
        first_name="Alexandra",
        last_name="Ng",
    )
    other_owner = await _make_user(db_session, "owner-search-acc3@example.com", UserRole.SALES_REP)
    match = await make_account(owner_id=owner.id, company="Search Match Co")
    await make_account(owner_id=other_owner.id, company="No Match Co")

    results = await list_accounts(db_session, requester=manager, search="alexandra")

    assert [account.id for account in results] == [match.id]


async def test_get_account_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "getter-acc@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await get_account(db_session, account_id=999_999, requester=requester)


async def test_get_account_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-forbidden-acc@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-acc@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Get Co")

    with pytest.raises(AccountAccessForbiddenError):
        await get_account(db_session, account_id=account.id, requester=other_rep)


async def test_get_account_succeeds_for_owning_sales_rep(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-ok-acc@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Owned Get Co")

    fetched = await get_account(db_session, account_id=account.id, requester=owner)

    assert fetched.id == account.id


async def test_update_account_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "updater-acc@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await update_account(
            db_session, account_id=999_999, data=AccountUpdate(company="New Co"), requester=requester
        )


async def test_update_account_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account
):
    owner = await _make_user(db_session, "owner-upd-forbidden-acc@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upd-acc@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Update Co")

    with pytest.raises(AccountAccessForbiddenError):
        await update_account(
            db_session, account_id=account.id, data=AccountUpdate(company="New Co"), requester=other_rep
        )


async def test_update_account_applies_partial_changes(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-upd-ok-acc@example.com", UserRole.SALES_REP)
    account = await make_account(
        owner_id=owner.id, company="Old Co", domain="old.example.com", tier=LeadTier.BRONZE
    )

    updated = await update_account(
        db_session, account_id=account.id, data=AccountUpdate(company="New Co"), requester=owner
    )

    assert updated.company == "New Co"
    assert updated.tier == LeadTier.BRONZE  # untouched field preserved
    assert updated.domain == "old.example.com"  # untouched field preserved


async def test_delete_account_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "deleter-acc@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await delete_account(db_session, account_id=999_999, requester=requester)


async def test_delete_account_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account
):
    owner = await _make_user(db_session, "owner-del-forbidden-acc@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-del-acc@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Forbidden Delete Co")

    with pytest.raises(AccountAccessForbiddenError):
        await delete_account(db_session, account_id=account.id, requester=other_rep)


async def test_delete_account_removes_the_row(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-del-ok-acc@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="To Be Deleted Co")
    account_id = account.id

    await delete_account(db_session, account_id=account_id, requester=owner)

    with pytest.raises(AccountNotFoundError):
        await get_account(db_session, account_id=account_id, requester=owner)


# --- convert_lead_to_account -------------------------------------------------


async def test_convert_lead_to_account_copies_fields_and_sets_source_lead_id(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert@example.com", UserRole.SALES_REP)
    lead = await make_lead(
        owner_id=owner.id,
        email="convert-me@example.com",
        company="Convert Co",
        domain="convert.example.com",
        tier=LeadTier.GOLD,
    )

    account = await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner)

    assert account.company == "Convert Co"
    assert account.domain == "convert.example.com"
    assert account.tier == LeadTier.GOLD
    assert account.owner_id == owner.id
    assert account.source_lead_id == lead.id


async def test_convert_lead_to_account_marks_lead_as_converted(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-convert-flag@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-flag@example.com")

    await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner)

    assert lead.is_converted is True


async def test_convert_lead_to_account_raises_for_already_converted_lead(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert-twice@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-twice@example.com")
    await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner)

    with pytest.raises(LeadAlreadyConvertedError):
        await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner)


async def test_convert_lead_to_account_raises_not_found_for_missing_lead(db_session: AsyncSession):
    requester = await _make_user(db_session, "converter-404@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await convert_lead_to_account(db_session, lead_id=999_999, requester=requester)


async def test_convert_lead_to_account_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-convert@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-forbidden@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await convert_lead_to_account(db_session, lead_id=lead.id, requester=other_rep)


async def test_convert_lead_to_account_overrides_take_precedence_over_lead_values(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert-override@example.com", UserRole.SALES_REP)
    other_owner = await _make_user(
        db_session, "other-owner-convert-override@example.com", UserRole.SALES_REP
    )
    lead = await make_lead(owner_id=owner.id, email="convert-override@example.com", tier=LeadTier.BRONZE)

    account = await convert_lead_to_account(
        db_session, lead_id=lead.id, requester=owner, tier=LeadTier.DIAMOND, owner_id=other_owner.id
    )

    assert account.tier == LeadTier.DIAMOND
    assert account.owner_id == other_owner.id


async def test_convert_lead_to_account_raises_when_tier_and_owner_both_missing(
    db_session: AsyncSession, make_lead
):
    manager = await _make_user(db_session, "manager-convert-missing-svc@example.com", UserRole.SALES_MANAGER)
    lead = await make_lead(owner_id=None, email="convert-missing-svc@example.com", tier=None)

    with pytest.raises(LeadMissingFieldsForConversionError):
        await convert_lead_to_account(db_session, lead_id=lead.id, requester=manager)


async def test_convert_lead_to_account_missing_fields_resolved_by_overrides(
    db_session: AsyncSession, make_lead
):
    manager = await _make_user(db_session, "manager-convert-resolved-svc@example.com", UserRole.SALES_MANAGER)
    new_owner = await _make_user(db_session, "owner-convert-resolved-svc@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=None, email="convert-resolved-svc@example.com", tier=None)

    account = await convert_lead_to_account(
        db_session, lead_id=lead.id, requester=manager, tier=LeadTier.GOLD, owner_id=new_owner.id
    )

    assert account.tier == LeadTier.GOLD
    assert account.owner_id == new_owner.id
