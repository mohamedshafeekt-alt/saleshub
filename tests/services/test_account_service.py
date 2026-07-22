"""app.services.account_service: create/list/get/update/delete business rules,
plus Lead -> Account conversion.

Covers: successful create (no duplicate-check, no unique constraint on this
table), including saving its `contacts` list to the `contacts` table (only
the first contact needs a name, later ones inherit it since Contact.first_name
is NOT NULL); every returned Account carries owner_name/contact_count/deal_count
(computed properties, eager-loaded to avoid MissingGreenlet); list_accounts
role-scoping (Sales Rep forced to own accounts even when passing a different
owner_id, Manager sees all or filtered); tier/industry exact-match filters;
search across company/domain/owner name; not-found/forbidden checks on
get/update/delete; partial update (including owner_id reassignment refreshing
owner_name); delete. Plus convert_lead_to_account: copies fields from the
lead and sets source_lead_id, marks the lead converted, rejects a second
conversion, reuses lead_service's not-found/forbidden checks, and honors
explicit tier/owner_id overrides.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.enums import DealStage, LeadTier
from app.models.user import User
from app.schemas.account import AccountContactInput, AccountCreate, AccountUpdate
from tests.support.roles import UserRole, role_id_for
from app.services.account_service import (
    AccountAccessForbiddenError,
    AccountNotFoundError,
    LeadAlreadyConvertedError,
    LeadMissingFieldsForConversionError,
    convert_lead_to_account,
    create_account,
    delete_account,
    get_account,
    get_account_overview,
    list_accounts,
    update_account,
)
from app.services.lead_service import LeadAccessForbiddenError, LeadNotFoundError


async def _contacts_for_account(db_session: AsyncSession, account_id: int) -> list[Contact]:
    result = await db_session.execute(
        select(Contact)
        .join(ContactAccount, ContactAccount.contact_id == Contact.id)
        .where(ContactAccount.account_id == account_id)
        .order_by(Contact.id)
    )
    return list(result.scalars().all())


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def test_create_account_succeeds(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-acc@example.com", UserRole.SALES_REP)

    data = AccountCreate(company="Acme Corp", domain="acme.example.com", tier=LeadTier.GOLD, owner_id=owner.id)
    account = await create_account(db_session, data)

    assert account.id is not None
    assert account.company == "Acme Corp"
    assert account.domain == "acme.example.com"
    assert account.owner_id == owner.id
    assert account.source_lead_id is None


async def test_create_account_with_no_contacts_creates_none(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-acc-no-contacts@example.com", UserRole.SALES_REP)
    data = AccountCreate(
        company="No Contact Co", domain="nocontact.example.com", tier=LeadTier.GOLD, owner_id=owner.id
    )

    account = await create_account(db_session, data)

    contacts = await _contacts_for_account(db_session, account.id)
    assert contacts == []


async def test_create_account_saves_first_contact_with_its_own_name(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-acc-c1@example.com", UserRole.SALES_REP)
    data = AccountCreate(
        company="Contact Co",
        domain="contact.example.com",
        tier=LeadTier.GOLD,
        owner_id=owner.id,
        contacts=[
            AccountContactInput(
                first_name="Jane", last_name="Doe", email="jane@example.com", job_title="VP of Sales"
            )
        ],
    )

    account = await create_account(db_session, data)

    contacts = await _contacts_for_account(db_session, account.id)
    assert len(contacts) == 1
    assert contacts[0].first_name == "Jane"
    assert contacts[0].last_name == "Doe"
    assert contacts[0].email == "jane@example.com"
    assert contacts[0].job_title == "VP of Sales"


async def test_create_account_nameless_extra_contacts_inherit_first_contacts_name(
    db_session: AsyncSession,
):
    owner = await _make_user(db_session, "owner-acc-c2@example.com", UserRole.SALES_REP)
    data = AccountCreate(
        company="Multi Contact Co",
        domain="multi.example.com",
        tier=LeadTier.GOLD,
        owner_id=owner.id,
        contacts=[
            AccountContactInput(first_name="Jane", last_name="Doe", email="jane@example.com"),
            AccountContactInput(email="jane-work@example.com", phone="+1-555-0100"),
        ],
    )

    account = await create_account(db_session, data)

    contacts = await _contacts_for_account(db_session, account.id)
    assert len(contacts) == 2
    assert contacts[1].first_name == "Jane"
    assert contacts[1].last_name == "Doe"
    assert contacts[1].email == "jane-work@example.com"
    assert contacts[1].phone == "+1-555-0100"


async def test_create_account_returns_owner_name_and_contact_count(db_session: AsyncSession):
    owner = await _make_user(
        db_session, "owner-acc-name@example.com", UserRole.SALES_REP, first_name="Karthick"
    )
    data = AccountCreate(
        company="Named Co",
        domain="named.example.com",
        tier=LeadTier.GOLD,
        owner_id=owner.id,
        contacts=[AccountContactInput(first_name="Jane", email="jane@example.com")],
    )

    account = await create_account(db_session, data)

    assert account.owner_name == "Karthick"
    assert account.contact_count == 1
    assert account.deal_count == 0


async def test_get_account_includes_owner_name_and_deal_count(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(
        db_session, "owner-acc-deals@example.com", UserRole.SALES_REP, first_name="Vishnu"
    )
    account = await make_account(owner_id=owner.id, company="Deal Count Co")
    await make_deal(account_id=account.id, owner_id=owner.id)
    await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Second Deal")

    fetched = await get_account(db_session, account_id=account.id, requester=owner)

    assert fetched.owner_name == "Vishnu"
    assert fetched.deal_count == 2
    assert fetched.contact_count == 0


async def test_list_accounts_filters_by_industry(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-industry-acc@example.com", UserRole.SALES_REP)
    software_account = await make_account(owner_id=owner.id, company="Software Co", industry="Software")
    await make_account(owner_id=owner.id, company="Healthcare Co", industry="Healthcare")

    results, _total = await list_accounts(db_session, requester=owner, industry="Software")

    assert [account.id for account in results] == [software_account.id]


async def test_list_accounts_search_matches_domain(db_session: AsyncSession, make_account):
    manager = await _make_user(db_session, "manager-search-domain-acc@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search-domain-acc@example.com", UserRole.SALES_REP)
    match = await make_account(owner_id=owner.id, company="Domain Match Co", domain="rocketship.io")
    await make_account(owner_id=owner.id, company="No Match Co", domain="other.io")

    results, _total = await list_accounts(db_session, requester=manager, search="rocketship")

    assert [account.id for account in results] == [match.id]


async def test_list_accounts_sales_rep_only_sees_own_accounts_even_with_owner_id_param(
    db_session: AsyncSession, make_account
):
    rep_a = await _make_user(db_session, "rep-a-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-acc@example.com", UserRole.SALES_REP)
    own_account = await make_account(owner_id=rep_a.id, company="Own Co")
    await make_account(owner_id=rep_b.id, company="Other Co")

    results, _total = await list_accounts(db_session, requester=rep_a, owner_id=rep_b.id)

    assert [account.id for account in results] == [own_account.id]


async def test_list_accounts_manager_sees_all_when_no_owner_id_given(db_session: AsyncSession, make_account):
    rep_a = await _make_user(db_session, "rep-c-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-d-acc@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-acc@example.com", UserRole.SALES_MANAGER)
    account_a = await make_account(owner_id=rep_a.id, company="Co A")
    account_b = await make_account(owner_id=rep_b.id, company="Co B")

    results, _total = await list_accounts(db_session, requester=manager)

    ids = {account.id for account in results}
    assert ids == {account_a.id, account_b.id}


async def test_list_accounts_manager_filters_by_owner_id_when_given(db_session: AsyncSession, make_account):
    rep_a = await _make_user(db_session, "rep-e-acc@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-f-acc@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager2-acc@example.com", UserRole.SALES_MANAGER)
    account_a = await make_account(owner_id=rep_a.id, company="Co E")
    await make_account(owner_id=rep_b.id, company="Co F")

    results, _total = await list_accounts(db_session, requester=manager, owner_id=rep_a.id)

    assert [account.id for account in results] == [account_a.id]


async def test_list_accounts_filters_by_tier(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-tier-acc@example.com", UserRole.SALES_REP)
    gold_account = await make_account(owner_id=owner.id, company="Tier Gold Co", tier=LeadTier.GOLD)
    await make_account(owner_id=owner.id, company="Tier Bronze Co", tier=LeadTier.BRONZE)

    results, _total = await list_accounts(db_session, requester=owner, tier=LeadTier.GOLD)

    assert [account.id for account in results] == [gold_account.id]


async def test_list_accounts_search_matches_company_name(db_session: AsyncSession, make_account):
    manager = await _make_user(db_session, "manager-search-acc1@example.com", UserRole.SALES_MANAGER)
    owner = await _make_user(db_session, "owner-search-acc1@example.com", UserRole.SALES_REP)
    match = await make_account(owner_id=owner.id, company="Rocketship Inc")
    await make_account(owner_id=owner.id, company="Other Co")

    results, _total = await list_accounts(db_session, requester=manager, search="rocketship")

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

    results, _total = await list_accounts(db_session, requester=manager, search="alexandra")

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


async def test_update_account_owner_id_change_refreshes_owner_name(
    db_session: AsyncSession, make_account
):
    original_owner = await _make_user(
        db_session, "owner-upd-original@example.com", UserRole.SALES_MANAGER, first_name="Original"
    )
    new_owner = await _make_user(
        db_session, "owner-upd-new@example.com", UserRole.SALES_REP, first_name="Newowner"
    )
    account = await make_account(owner_id=original_owner.id, company="Reassign Co")

    updated = await update_account(
        db_session,
        account_id=account.id,
        data=AccountUpdate(owner_id=new_owner.id),
        requester=original_owner,
    )

    assert updated.owner_id == new_owner.id
    assert updated.owner_name == "Newowner"


async def test_update_account_adds_contacts(db_session: AsyncSession, make_account):
    owner = await _make_user(db_session, "owner-upd-contacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Add Contacts Co")

    updated = await update_account(
        db_session,
        account_id=account.id,
        data=AccountUpdate(
            contacts=[
                AccountContactInput(first_name="Jane", last_name="Doe", email="jane@example.com"),
                AccountContactInput(email="jane-work@example.com", phone="+1-555-0100"),
            ]
        ),
        requester=owner,
    )

    contacts = await _contacts_for_account(db_session, account.id)
    assert len(contacts) == 2
    assert contacts[0].first_name == "Jane"
    assert contacts[1].first_name == "Jane"  # inherited from the first contact
    assert contacts[1].email == "jane-work@example.com"
    assert updated.contact_count == 2


async def test_update_account_without_contacts_does_not_touch_existing_ones(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-upd-no-contacts@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Untouched Contacts Co")
    await make_contact(account_id=account.id, first_name="Existing")

    updated = await update_account(
        db_session, account_id=account.id, data=AccountUpdate(company="Renamed Co"), requester=owner
    )

    assert updated.company == "Renamed Co"
    assert updated.contact_count == 1


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


# --- get_account_overview -----------------------------------------------------


async def test_get_account_overview_open_deal_value_excludes_closed_and_cold_deals(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-overview-value@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Overview Value Co")
    await make_deal(account_id=account.id, owner_id=owner.id, stage=DealStage.PROPOSALS, value=650_000)
    await make_deal(
        account_id=account.id, owner_id=owner.id, stage=DealStage.EVALUATION, value=1_200_000
    )
    await make_deal(
        account_id=account.id, owner_id=owner.id, stage=DealStage.CLOSED_WON, value=999_999
    )
    await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        stage=DealStage.COLD_DEALS,
        value=1,
        cold_reason="Went quiet",
    )

    _account, active_deals, open_deal_value = await get_account_overview(
        db_session, account_id=account.id, requester=owner
    )

    assert open_deal_value == 1_850_000
    assert {deal.stage for deal in active_deals} == {DealStage.PROPOSALS, DealStage.EVALUATION}


async def test_get_account_overview_zero_deals_returns_zero_value(
    db_session: AsyncSession, make_account
):
    owner = await _make_user(db_session, "owner-overview-zero@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Overview Zero Co")

    _account, active_deals, open_deal_value = await get_account_overview(
        db_session, account_id=account.id, requester=owner
    )

    assert active_deals == []
    assert open_deal_value == 0


async def test_get_account_overview_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "overview-404@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await get_account_overview(db_session, account_id=999_999, requester=requester)


async def test_get_account_overview_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account
):
    owner = await _make_user(db_session, "owner-overview-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-overview@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Overview Forbidden Co")

    with pytest.raises(AccountAccessForbiddenError):
        await get_account_overview(db_session, account_id=account.id, requester=other_rep)


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
    )

    account = await convert_lead_to_account(
        db_session, lead_id=lead.id, requester=owner, tier=LeadTier.GOLD
    )

    assert account.company == "Convert Co"
    assert account.domain == "convert.example.com"
    assert account.tier == LeadTier.GOLD
    assert account.owner_id == owner.id
    assert account.source_lead_id == lead.id


async def test_convert_lead_to_account_marks_lead_as_converted(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-convert-flag@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-flag@example.com")

    await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner, tier=LeadTier.GOLD)

    assert lead.is_converted is True


async def test_convert_lead_to_account_raises_for_already_converted_lead(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert-twice@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-twice@example.com")
    await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner, tier=LeadTier.GOLD)

    with pytest.raises(LeadAlreadyConvertedError):
        await convert_lead_to_account(db_session, lead_id=lead.id, requester=owner, tier=LeadTier.GOLD)


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


async def test_convert_lead_to_account_owner_override_takes_precedence_over_lead_owner(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-convert-override@example.com", UserRole.SALES_REP)
    other_owner = await _make_user(
        db_session, "other-owner-convert-override@example.com", UserRole.SALES_REP
    )
    lead = await make_lead(owner_id=owner.id, email="convert-override@example.com")

    account = await convert_lead_to_account(
        db_session, lead_id=lead.id, requester=owner, tier=LeadTier.DIAMOND, owner_id=other_owner.id
    )

    assert account.tier == LeadTier.DIAMOND
    assert account.owner_id == other_owner.id


async def test_convert_lead_to_account_raises_when_tier_and_owner_both_missing(
    db_session: AsyncSession, make_lead
):
    manager = await _make_user(db_session, "manager-convert-missing-svc@example.com", UserRole.SALES_MANAGER)
    lead = await make_lead(owner_id=None, email="convert-missing-svc@example.com")

    with pytest.raises(LeadMissingFieldsForConversionError):
        await convert_lead_to_account(db_session, lead_id=lead.id, requester=manager)


async def test_convert_lead_to_account_missing_fields_resolved_by_overrides(
    db_session: AsyncSession, make_lead
):
    manager = await _make_user(db_session, "manager-convert-resolved-svc@example.com", UserRole.SALES_MANAGER)
    new_owner = await _make_user(db_session, "owner-convert-resolved-svc@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=None, email="convert-resolved-svc@example.com")

    account = await convert_lead_to_account(
        db_session, lead_id=lead.id, requester=manager, tier=LeadTier.GOLD, owner_id=new_owner.id
    )

    assert account.tier == LeadTier.GOLD
    assert account.owner_id == new_owner.id
