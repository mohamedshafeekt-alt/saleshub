"""app.services.contact_service: plain CRUD on the standalone Contact entity,
plus scoped listing and the Contact Overview screen.

Contact has no owner_id and no single owning account (see the module
docstring on contact_service.py). Covers: create/get/update/delete succeed
for someone with visibility into the contact; get/update/delete raise
ContactNotFoundError for a missing id; update_contact applies only fields set
(partial update). Account-scoped creation/update (with is_primary) is covered
in tests/services/test_contact_account_service.py instead.

get_contact_overview: derives owner/tier/account from the contact's
representative Account link (oldest is_primary=True link, else oldest link
overall, else all null when unlinked); deal_count is real (via DealContact).
list_contacts: owner_id/account_id/tier/is_primary match if ANY of a
contact's linked accounts satisfies them; search matches name/email;
pagination. Most filter-mechanic tests below use a contacts.view_all
requester (Sales Manager) so the filter itself is exercised independent of
scoping -- see the "contacts.access / contacts.view_all scoping" section at
the bottom for the actual scoping behavior (contacts.access-only sees only
contacts linked to an Account/Deal it owns, or an unlinked contact it
created itself; contacts.view_all sees everything).
"""

from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_account import ContactAccount
from app.models.enums import LeadTier
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.contact_service import (
    ContactAccessForbiddenError,
    ContactNotFoundError,
    DuplicateContactEmailError,
    create_contact,
    delete_contact,
    export_contacts,
    get_contact,
    get_contact_overview,
    list_contacts,
    update_contact,
)
from tests.support.roles import UserRole, role_id_for


async def test_create_contact_succeeds(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-create-succeeds@example.com", UserRole.SALES_REP)
    data = ContactCreate(first_name="Jane", last_name="Doe", email="jane@example.com")

    contact = await create_contact(db_session, data, requester=actor)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.last_name == "Doe"
    assert contact.email == "jane@example.com"


async def test_create_contact_with_linkedin_and_alternate_phone(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-create-linkedin@example.com", UserRole.SALES_REP)
    data = ContactCreate(
        first_name="Jane",
        email="jane-linkedin@example.com",
        linkedin_url="https://linkedin.com/in/jane",
        phone="555-000-0001",
        alternate_phone="555-000-0002",
    )

    contact = await create_contact(db_session, data, requester=actor)

    assert contact.linkedin_url == "https://linkedin.com/in/jane"
    assert contact.phone == "5550000001"
    assert contact.alternate_phone == "5550000002"


async def test_create_contact_raises_duplicate_email_for_existing_email(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-create-dup1@example.com", UserRole.SALES_REP)
    await create_contact(db_session, ContactCreate(first_name="Jane", email="dup-contact@example.com"), requester=actor)

    with pytest.raises(DuplicateContactEmailError):
        await create_contact(
            db_session, ContactCreate(first_name="Someone Else", email="dup-contact@example.com"), requester=actor
        )


async def test_get_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-get-missing@example.com", UserRole.SALES_REP)
    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=999_999, requester=actor)


async def test_get_contact_succeeds(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-get-succeeds@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session, ContactCreate(first_name="Getable", email="getable@example.com"), requester=actor
    )

    fetched = await get_contact(db_session, contact_id=created.id, requester=actor)

    assert fetched.id == created.id


async def test_update_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-update-missing@example.com", UserRole.SALES_REP)
    with pytest.raises(ContactNotFoundError):
        await update_contact(db_session, contact_id=999_999, data=ContactUpdate(first_name="New"), requester=actor)


async def test_update_contact_applies_partial_changes(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-update-partial@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session,
        ContactCreate(first_name="Old", last_name="Name", email="old-name@example.com", job_title="Old Title"),
        requester=actor,
    )

    updated = await update_contact(
        db_session, contact_id=created.id, data=ContactUpdate(first_name="New"), requester=actor
    )

    assert updated.first_name == "New"
    assert updated.last_name == "Name"  # untouched field preserved
    assert updated.job_title == "Old Title"  # untouched field preserved


async def test_create_contact_duplicate_email_raises(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-create-dup2@example.com", UserRole.SALES_REP)
    await create_contact(db_session, ContactCreate(first_name="First", email="dup-contact@example.com"), requester=actor)

    with pytest.raises(DuplicateContactEmailError):
        await create_contact(
            db_session, ContactCreate(first_name="Second", email="dup-contact@example.com"), requester=actor
        )


async def test_update_contact_duplicate_email_raises(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-update-dup@example.com", UserRole.SALES_REP)
    await create_contact(db_session, ContactCreate(first_name="First", email="taken@example.com"), requester=actor)
    other = await create_contact(
        db_session, ContactCreate(first_name="Second", email="free@example.com"), requester=actor
    )

    with pytest.raises(DuplicateContactEmailError):
        await update_contact(
            db_session, contact_id=other.id, data=ContactUpdate(email="taken@example.com"), requester=actor
        )


async def test_delete_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-delete-missing@example.com", UserRole.SALES_REP)
    with pytest.raises(ContactNotFoundError):
        await delete_contact(db_session, contact_id=999_999, requester=actor)


async def test_delete_contact_removes_the_row(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-delete-row@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session, ContactCreate(first_name="To Delete", email="to-delete@example.com"), requester=actor
    )
    contact_id = created.id

    await delete_contact(db_session, contact_id=contact_id, requester=actor)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=contact_id, requester=actor)


async def _make_user(db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test") -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


# --- get_contact_overview -----------------------------------------------------


async def test_get_contact_overview_raises_not_found_for_missing_id(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-overview-missing@example.com", UserRole.SALES_REP)
    with pytest.raises(ContactNotFoundError):
        await get_contact_overview(db_session, contact_id=999_999, requester=actor)


async def test_get_contact_overview_with_no_linked_accounts_returns_null_derived_fields(
    db_session: AsyncSession,
):
    actor = await _make_user(db_session, "actor-overview-unlinked@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session, ContactCreate(first_name="Unlinked", email="unlinked@example.com"), requester=actor
    )

    contact, account_link, deal_count, created_by_name = await get_contact_overview(
        db_session, created.id, requester=actor
    )

    assert contact.id == created.id
    assert account_link is None
    assert deal_count == 0
    assert created_by_name == "Test"


async def test_get_contact_overview_derives_owner_tier_account_from_single_link(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-overview-single@example.com", UserRole.SALES_REP, "Karthick")
    account = await make_account(owner_id=owner.id, company="Nexbridge Tech", tier=LeadTier.GOLD)
    created = await make_contact(account_id=account.id, first_name="Sarah", is_primary=True)

    contact, account_link, _deal_count, created_by_name = await get_contact_overview(
        db_session, created.id, requester=owner
    )

    assert account_link is not None
    assert account_link.is_primary is True
    assert account_link.account.id == account.id
    assert account_link.account.company == "Nexbridge Tech"
    assert account_link.account.tier == LeadTier.GOLD
    assert created_by_name is None  # made via make_contact, bypasses create_contact -- no audit row
    assert account_link.account.owner_id == owner.id
    assert account_link.account.owner_name == "Karthick"


async def test_get_contact_overview_prefers_oldest_primary_link_when_multiple_accounts(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-overview-tiebreak@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Account A")
    account_b = await make_account(owner_id=owner.id, company="Account B")
    account_c = await make_account(owner_id=owner.id, company="Account C")
    contact = await make_contact(account_id=account_a.id, first_name="Multi", is_primary=False)

    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_b.id, is_primary=True))
    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_c.id, is_primary=True))
    await db_session.flush()

    _contact, account_link, _deal_count, _created_by_name = await get_contact_overview(
        db_session, contact.id, requester=owner
    )

    assert account_link is not None
    assert account_link.account.company == "Account B"  # oldest is_primary=True link


async def test_get_contact_overview_falls_back_to_oldest_link_when_none_primary(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-overview-fallback@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="First Linked Co")
    account_b = await make_account(owner_id=owner.id, company="Second Linked Co")
    contact = await make_contact(account_id=account_a.id, first_name="Neither Primary", is_primary=False)


    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_b.id, is_primary=False))
    await db_session.flush()

    _contact, account_link, _deal_count, _created_by_name = await get_contact_overview(
        db_session, contact.id, requester=owner
    )

    assert account_link is not None
    assert account_link.account.company == "First Linked Co"  # oldest link overall


async def test_get_contact_overview_deal_count_reflects_linked_deals(
    db_session: AsyncSession, make_account, make_contact, make_deal
):
    owner = await _make_user(db_session, "owner-overview-deals@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Deal Count Co")
    contact = await make_contact(account_id=account.id)
    other_contact = await make_contact(account_id=account.id, email="other-overview-deals@example.com")
    await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Deal One", contact_ids=[contact.id])
    await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Deal Two", contact_ids=[contact.id])
    await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="Other's Deal", contact_ids=[other_contact.id]
    )

    _contact, _account_link, deal_count, _created_by_name = await get_contact_overview(
        db_session, contact.id, requester=owner
    )

    assert deal_count == 2


# --- list_contacts -------------------------------------------------------------


async def test_export_contacts_returns_flat_rows_with_account_and_owner(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-export-contact@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Export Contact Co", tier=LeadTier.SILVER)
    await make_contact(
        account_id=account.id,
        first_name="Jane",
        last_name="Export",
        email="jane.export@example.com",
        is_primary=True,
    )

    rows = await export_contacts(db_session, requester=owner, account_id=account.id)

    assert any(
        row["name"] == "Jane Export"
        and row["email"] == "jane.export@example.com"
        and row["account"] == "Export Contact Co"
        and row["tier"] == "silver"
        and row["is_primary"] is True
        for row in rows
    )


async def test_list_contacts_filters_by_owner_id(db_session: AsyncSession, make_account, make_contact):
    manager = await _make_user(db_session, "manager-list-contacts@example.com", UserRole.SALES_MANAGER)
    owner_a = await _make_user(db_session, "owner-a-list-contacts@example.com", UserRole.SALES_REP)
    owner_b = await _make_user(db_session, "owner-b-list-contacts@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner_a.id, company="Owner A Co")
    account_b = await make_account(owner_id=owner_b.id, company="Owner B Co")
    contact_a = await make_contact(account_id=account_a.id, first_name="Owned By A")
    await make_contact(account_id=account_b.id, first_name="Owned By B")

    items, total = await list_contacts(db_session, requester=manager, owner_id=owner_a.id)

    assert total == 1
    assert [contact.id for contact, _link in items] == [contact_a.id]


async def test_list_contacts_filters_by_account_id(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-account@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="List Account A")
    account_b = await make_account(owner_id=owner.id, company="List Account B")
    contact_a = await make_contact(account_id=account_a.id, first_name="In Account A")
    await make_contact(account_id=account_b.id, first_name="In Account B")

    items, total = await list_contacts(db_session, requester=owner, account_id=account_a.id)

    assert total == 1
    assert [contact.id for contact, _link in items] == [contact_a.id]


async def test_list_contacts_filters_by_tier(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-tier@example.com", UserRole.SALES_REP)
    gold_account = await make_account(owner_id=owner.id, company="Gold Co", tier=LeadTier.GOLD)
    silver_account = await make_account(owner_id=owner.id, company="Silver Co", tier=LeadTier.SILVER)
    gold_contact = await make_contact(account_id=gold_account.id, first_name="Gold Contact")
    await make_contact(account_id=silver_account.id, first_name="Silver Contact")

    items, total = await list_contacts(db_session, requester=owner, tier=LeadTier.GOLD)

    assert total == 1
    assert [contact.id for contact, _link in items] == [gold_contact.id]


async def test_list_contacts_filters_by_is_primary(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-primary@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Primary Filter Co")
    primary_contact = await make_contact(account_id=account.id, first_name="Primary One", is_primary=True)
    await make_contact(account_id=account.id, first_name="Secondary One", is_primary=False)

    items, total = await list_contacts(db_session, requester=owner, is_primary=True)

    assert total == 1
    assert [contact.id for contact, _link in items] == [primary_contact.id]


async def test_list_contacts_search_matches_name_or_email(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-list-search@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Search Co")
    jane = await make_contact(account_id=account.id, first_name="Jane", email="jane-search@example.com")
    await make_contact(account_id=account.id, first_name="Someone", last_name="Else")

    items, _total = await list_contacts(db_session, requester=owner, search="jane")

    assert [contact.id for contact, _link in items] == [jane.id]


async def test_list_contacts_pagination_limit_offset(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-pagination@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Pagination Co")
    for i in range(3):
        await make_contact(account_id=account.id, first_name=f"Paged {i}")

    items, total = await list_contacts(db_session, requester=owner, account_id=account.id, limit=2, offset=1)

    assert total == 3
    assert len(items) == 2


async def test_list_contacts_no_filters_returns_all_contacts_including_unlinked(
    db_session: AsyncSession, make_account, make_contact
):
    """Unfiltered still means "everything requester can see", not literally
    everything -- owner here can see both because it owns the linked
    contact's account and created the unlinked one. See the scoping section
    below for a requester with neither."""
    owner = await _make_user(db_session, "owner-list-unfiltered@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Unfiltered Co")
    linked = await make_contact(account_id=account.id, first_name="Linked")
    unlinked = await create_contact(
        db_session,
        ContactCreate(first_name="Unlinked Contact", email="unlinked-contact@example.com"),
        requester=owner,
    )

    items, _total = await list_contacts(db_session, requester=owner)

    ids = {contact.id for contact, _link in items}
    assert linked.id in ids
    assert unlinked.id in ids


async def test_list_contacts_filters_by_created_at_range(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-list-date-range@example.com", UserRole.SALES_REP)
    early = await create_contact(
        db_session, ContactCreate(first_name="Early", email="early-date-range@example.com"), requester=actor
    )
    early.created_at = date(2026, 6, 1)
    in_range = await create_contact(
        db_session, ContactCreate(first_name="InRange", email="in-range-date-range@example.com"), requester=actor
    )
    in_range.created_at = date(2026, 7, 10)
    late = await create_contact(
        db_session, ContactCreate(first_name="Late", email="late-date-range@example.com"), requester=actor
    )
    late.created_at = date(2026, 8, 1)
    await db_session.flush()

    items, total = await list_contacts(
        db_session, requester=actor, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )

    assert total == 1
    assert [contact.id for contact, _link in items] == [in_range.id]


async def test_list_contacts_date_to_includes_contacts_created_on_the_end_date(db_session: AsyncSession):
    """date_to is inclusive -- see account_service.list_accounts for why."""
    actor = await _make_user(db_session, "actor-date-to-inclusive@example.com", UserRole.SALES_REP)
    on_end_date = await create_contact(
        db_session, ContactCreate(first_name="OnEndDate", email="on-end-date@example.com"), requester=actor
    )
    on_end_date.created_at = datetime(2026, 8, 11, 15, 30)
    after_end_date = await create_contact(
        db_session, ContactCreate(first_name="AfterEndDate", email="after-end-date@example.com"), requester=actor
    )
    after_end_date.created_at = datetime(2026, 8, 12, 9, 0)
    await db_session.flush()

    items, total = await list_contacts(
        db_session, requester=actor, date_from=date(2026, 8, 1), date_to=date(2026, 8, 11)
    )

    assert total == 1
    assert [contact.id for contact, _link in items] == [on_end_date.id]


async def test_list_contacts_owner_filter_matches_any_of_multiple_linked_accounts(
    db_session: AsyncSession, make_account, make_contact
):
    manager = await _make_user(db_session, "manager-multi-link@example.com", UserRole.SALES_MANAGER)
    owner_a = await _make_user(db_session, "owner-a-multi-link@example.com", UserRole.SALES_REP)
    owner_b = await _make_user(db_session, "owner-b-multi-link@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner_a.id, company="Multi Link Account A")
    account_b = await make_account(owner_id=owner_b.id, company="Multi Link Account B")
    contact = await make_contact(account_id=account_a.id, first_name="Multi Linked")


    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_b.id, is_primary=False))
    await db_session.flush()

    items, total = await list_contacts(db_session, requester=manager, owner_id=owner_b.id)

    assert total == 1
    assert [c.id for c, _link in items] == [contact.id]


# --- audit log ------------------------------------------------------------


async def test_create_contact_writes_audit_log(db_session, make_user):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    actor = await make_user(email="contact-audit-actor@example.com")
    data = ContactCreate(first_name="John", last_name="Doe", email="contact-audit-1@example.com")
    contact = await create_contact(db_session, data, requester=actor)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "contacts", AuditLog.record_id == contact.id, AuditLog.action == "created")
    )
    assert result.scalar_one() is not None


async def test_update_contact_writes_audit_log(db_session, make_user, make_account, make_contact):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    actor = await make_user(email="contact-audit-actor2@example.com")
    account = await make_account(owner_id=actor.id)
    contact = await make_contact(account_id=account.id)
    await update_contact(db_session, contact.id, ContactUpdate(first_name="Jane"), requester=actor)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "contacts", AuditLog.record_id == contact.id, AuditLog.action == "updated")
    )
    assert result.scalar_one() is not None


async def test_delete_contact_writes_audit_log(db_session, make_user, make_account, make_contact):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    actor = await make_user(email="contact-audit-actor3@example.com")
    account = await make_account(owner_id=actor.id)
    contact = await make_contact(account_id=account.id)
    contact_id = contact.id
    await delete_contact(db_session, contact_id, requester=actor)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "contacts", AuditLog.record_id == contact_id, AuditLog.action == "deleted")
    )
    assert result.scalar_one() is not None


# --- contacts.access / contacts.view_all scoping ---------------------------
#
# Without contacts.view_all, a requester only sees a Contact linked (via
# ContactAccount or DealContact) to an Account/Deal it owns, or -- for a
# Contact with no links at all -- one it created itself. contacts.view_all
# (seeded on the Sales Manager starter role) bypasses this entirely.


async def test_list_contacts_access_only_hides_others_contacts_and_unlinked(
    db_session: AsyncSession, make_account, make_contact
):
    rep_a = await _make_user(db_session, "rep-a-scoping-list@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-scoping-list@example.com", UserRole.SALES_REP)
    account_b = await make_account(owner_id=rep_b.id, company="Rep B Co")
    await make_contact(account_id=account_b.id, first_name="Rep B's Contact")
    await create_contact(
        db_session,
        ContactCreate(first_name="Rep B's Unlinked", email="rep-b-unlinked@example.com"),
        requester=rep_b,
    )

    items, total = await list_contacts(db_session, requester=rep_a)

    assert total == 0
    assert items == []


async def test_list_contacts_view_all_sees_others_contacts_and_unlinked(
    db_session: AsyncSession, make_account, make_contact
):
    manager = await _make_user(db_session, "manager-scoping-list@example.com", UserRole.SALES_MANAGER)
    rep = await _make_user(db_session, "rep-scoping-list@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Rep Co")
    linked = await make_contact(account_id=account.id, first_name="Rep's Contact")
    unlinked = await create_contact(
        db_session, ContactCreate(first_name="Rep's Unlinked", email="rep-unlinked@example.com"), requester=rep
    )

    items, _total = await list_contacts(db_session, requester=manager)

    ids = {contact.id for contact, _link in items}
    assert linked.id in ids
    assert unlinked.id in ids


async def test_list_contacts_access_only_sees_contact_linked_via_owned_deal(
    db_session: AsyncSession, make_account, make_deal
):
    """Visibility via DealContact, independent of any Account link -- the
    contact here has zero ContactAccount rows."""
    rep = await _make_user(db_session, "rep-scoping-via-deal@example.com", UserRole.SALES_REP)
    other = await _make_user(db_session, "other-scoping-via-deal@example.com", UserRole.SALES_REP)
    contact = await create_contact(
        db_session,
        ContactCreate(first_name="Deal Stakeholder", email="deal-stakeholder@example.com"),
        requester=other,  # created by someone else -- only the deal link should grant rep visibility
    )
    account = await make_account(owner_id=rep.id, company="Rep Deal Co")
    await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Rep's Deal", contact_ids=[contact.id])

    items, total = await list_contacts(db_session, requester=rep)

    assert total == 1
    assert [c.id for c, _link in items] == [contact.id]


async def test_get_contact_raises_forbidden_for_non_owning_non_creator(
    db_session: AsyncSession, make_account, make_contact
):
    rep_a = await _make_user(db_session, "rep-a-scoping-get@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-scoping-get@example.com", UserRole.SALES_REP)
    account_b = await make_account(owner_id=rep_b.id, company="Rep B Get Co")
    contact = await make_contact(account_id=account_b.id, first_name="Rep B's Contact")

    with pytest.raises(ContactAccessForbiddenError):
        await get_contact(db_session, contact.id, requester=rep_a)


async def test_get_contact_succeeds_for_view_all_regardless_of_ownership(
    db_session: AsyncSession, make_account, make_contact
):
    manager = await _make_user(db_session, "manager-scoping-get@example.com", UserRole.SALES_MANAGER)
    rep = await _make_user(db_session, "rep-scoping-get@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Rep Get Co")
    contact = await make_contact(account_id=account.id, first_name="Rep's Contact")

    fetched = await get_contact(db_session, contact.id, requester=manager)

    assert fetched.id == contact.id


async def test_update_contact_raises_forbidden_for_non_owning_non_creator(
    db_session: AsyncSession, make_account, make_contact
):
    rep_a = await _make_user(db_session, "rep-a-scoping-update@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-scoping-update@example.com", UserRole.SALES_REP)
    account_b = await make_account(owner_id=rep_b.id, company="Rep B Update Co")
    contact = await make_contact(account_id=account_b.id, first_name="Rep B's Contact")

    with pytest.raises(ContactAccessForbiddenError):
        await update_contact(db_session, contact.id, ContactUpdate(first_name="Hijacked"), requester=rep_a)


async def test_delete_contact_raises_forbidden_for_non_owning_non_creator(
    db_session: AsyncSession, make_account, make_contact
):
    rep_a = await _make_user(db_session, "rep-a-scoping-delete@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-scoping-delete@example.com", UserRole.SALES_REP)
    account_b = await make_account(owner_id=rep_b.id, company="Rep B Delete Co")
    contact = await make_contact(account_id=account_b.id, first_name="Rep B's Contact")

    with pytest.raises(ContactAccessForbiddenError):
        await delete_contact(db_session, contact.id, requester=rep_a)


async def test_get_contact_overview_raises_forbidden_for_non_owning_non_creator(
    db_session: AsyncSession, make_account, make_contact
):
    rep_a = await _make_user(db_session, "rep-a-scoping-overview@example.com", UserRole.SALES_REP)
    rep_b = await _make_user(db_session, "rep-b-scoping-overview@example.com", UserRole.SALES_REP)
    account_b = await make_account(owner_id=rep_b.id, company="Rep B Overview Co")
    contact = await make_contact(account_id=account_b.id, first_name="Rep B's Contact")

    with pytest.raises(ContactAccessForbiddenError):
        await get_contact_overview(db_session, contact.id, requester=rep_a)


async def test_unlinked_contact_visible_to_creator_but_forbidden_to_others(db_session: AsyncSession):
    creator = await _make_user(db_session, "creator-scoping-unlinked@example.com", UserRole.SALES_REP)
    other = await _make_user(db_session, "other-scoping-unlinked@example.com", UserRole.SALES_REP)
    contact = await create_contact(
        db_session, ContactCreate(first_name="Freshly Created", email="freshly-created@example.com"), requester=creator
    )

    fetched = await get_contact(db_session, contact.id, requester=creator)
    assert fetched.id == contact.id

    with pytest.raises(ContactAccessForbiddenError):
        await get_contact(db_session, contact.id, requester=other)
