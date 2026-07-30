"""app.services.contact_service: plain CRUD on the standalone Contact entity,
plus role-gated (not ownership-scoped) listing and the Contact Overview
screen.

Contact has no owner_id and no single owning account (see the module
docstring on contact_service.py) -- these operations are role-gated only at
the router level, not ownership-scoped here. Covers: create/get/update/delete
succeed regardless of who's asking; get/update/delete raise
ContactNotFoundError for a missing id; update_contact applies only fields set
(partial update). Account-scoped creation/update (with is_primary) is covered
in tests/services/test_contact_account_service.py instead.

get_contact_overview: derives owner/tier/account from the contact's
representative Account link (oldest is_primary=True link, else oldest link
overall, else all null when unlinked); deal_count is real (via DealContact).
list_contacts: owner_id/account_id/tier/is_primary match if ANY of a
contact's linked accounts satisfies them; search matches name/email;
pagination; contacts with zero linked accounts still appear when unfiltered.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_account import ContactAccount
from app.models.enums import LeadTier
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.contact_service import (
    ContactNotFoundError,
    DuplicateContactEmailError,
    create_contact,
    delete_contact,
    export_contacts,
    get_contact,
    get_contact_overview,
    list_contacts,
    reassign_contact_owners,
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
        phone="555-0001",
        alternate_phone="555-0002",
    )

    contact = await create_contact(db_session, data, requester=actor)

    assert contact.linkedin_url == "https://linkedin.com/in/jane"
    assert contact.phone == "555-0001"
    assert contact.alternate_phone == "555-0002"


async def test_create_contact_raises_duplicate_email_for_existing_email(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-create-dup1@example.com", UserRole.SALES_REP)
    await create_contact(db_session, ContactCreate(first_name="Jane", email="dup-contact@example.com"), requester=actor)

    with pytest.raises(DuplicateContactEmailError):
        await create_contact(
            db_session, ContactCreate(first_name="Someone Else", email="dup-contact@example.com"), requester=actor
        )


async def test_get_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=999_999)


async def test_get_contact_succeeds(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-get-succeeds@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session, ContactCreate(first_name="Getable", email="getable@example.com"), requester=actor
    )

    fetched = await get_contact(db_session, contact_id=created.id)

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
        await get_contact(db_session, contact_id=contact_id)


async def test_reassign_contact_owners_updates_representative_account(
    db_session: AsyncSession, make_account, make_contact
):
    actor = await _make_user(db_session, "actor-reassign@example.com", UserRole.SALES_REP)
    old_owner = await _make_user(db_session, "old-owner-reassign@example.com", UserRole.SALES_REP)
    new_owner = await _make_user(db_session, "new-owner-reassign@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=old_owner.id, company="Reassign Co")
    contact = await make_contact(account_id=account.id, first_name="Sarah", is_primary=True)

    updated_count = await reassign_contact_owners(db_session, [contact.id], new_owner.id, requester=actor)

    await db_session.refresh(account)
    assert updated_count == 1
    assert account.owner_id == new_owner.id


async def test_reassign_contact_owners_dedupes_shared_account(
    db_session: AsyncSession, make_account, make_contact
):
    actor = await _make_user(db_session, "actor-reassign-dedupe@example.com", UserRole.SALES_REP)
    old_owner = await _make_user(db_session, "old-owner-reassign-dedupe@example.com", UserRole.SALES_REP)
    new_owner = await _make_user(db_session, "new-owner-reassign-dedupe@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=old_owner.id, company="Shared Co")
    contact_a = await make_contact(account_id=account.id, first_name="A", is_primary=True)
    contact_b = await make_contact(account_id=account.id, first_name="B", is_primary=False)

    updated_count = await reassign_contact_owners(
        db_session, [contact_a.id, contact_b.id], new_owner.id, requester=actor
    )

    assert updated_count == 1


async def test_reassign_contact_owners_skips_unlinked_contact(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-reassign-unlinked@example.com", UserRole.SALES_REP)
    new_owner = await _make_user(db_session, "new-owner-reassign-unlinked@example.com", UserRole.SALES_REP)
    contact = await create_contact(
        db_session, ContactCreate(first_name="Unlinked", email="unlinked-reassign@example.com"), requester=actor
    )

    updated_count = await reassign_contact_owners(db_session, [contact.id], new_owner.id, requester=actor)

    assert updated_count == 0


async def test_reassign_contact_owners_raises_for_missing_contact(db_session: AsyncSession):
    actor = await _make_user(db_session, "actor-reassign-missing@example.com", UserRole.SALES_REP)

    with pytest.raises(ContactNotFoundError):
        await reassign_contact_owners(db_session, [999999], actor.id, requester=actor)


async def _make_user(db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test") -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


# --- get_contact_overview -----------------------------------------------------


async def test_get_contact_overview_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(ContactNotFoundError):
        await get_contact_overview(db_session, contact_id=999_999)


async def test_get_contact_overview_with_no_linked_accounts_returns_null_derived_fields(
    db_session: AsyncSession,
):
    actor = await _make_user(db_session, "actor-overview-unlinked@example.com", UserRole.SALES_REP)
    created = await create_contact(
        db_session, ContactCreate(first_name="Unlinked", email="unlinked@example.com"), requester=actor
    )

    contact, account_link, deal_count, created_by_name = await get_contact_overview(db_session, created.id)

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

    contact, account_link, _deal_count, created_by_name = await get_contact_overview(db_session, created.id)

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

    _contact, account_link, _deal_count, _created_by_name = await get_contact_overview(db_session, contact.id)

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

    _contact, account_link, _deal_count, _created_by_name = await get_contact_overview(db_session, contact.id)

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

    _contact, _account_link, deal_count, _created_by_name = await get_contact_overview(db_session, contact.id)

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

    rows = await export_contacts(db_session, account_id=account.id)

    assert any(
        row["name"] == "Jane Export"
        and row["email"] == "jane.export@example.com"
        and row["account"] == "Export Contact Co"
        and row["tier"] == "silver"
        and row["is_primary"] is True
        for row in rows
    )


async def test_list_contacts_filters_by_owner_id(db_session: AsyncSession, make_account, make_contact):
    owner_a = await _make_user(db_session, "owner-a-list-contacts@example.com", UserRole.SALES_REP)
    owner_b = await _make_user(db_session, "owner-b-list-contacts@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner_a.id, company="Owner A Co")
    account_b = await make_account(owner_id=owner_b.id, company="Owner B Co")
    contact_a = await make_contact(account_id=account_a.id, first_name="Owned By A")
    await make_contact(account_id=account_b.id, first_name="Owned By B")

    items, total = await list_contacts(db_session, owner_id=owner_a.id)

    assert total == 1
    assert [contact.id for contact, _link in items] == [contact_a.id]


async def test_list_contacts_filters_by_account_id(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-account@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="List Account A")
    account_b = await make_account(owner_id=owner.id, company="List Account B")
    contact_a = await make_contact(account_id=account_a.id, first_name="In Account A")
    await make_contact(account_id=account_b.id, first_name="In Account B")

    items, total = await list_contacts(db_session, account_id=account_a.id)

    assert total == 1
    assert [contact.id for contact, _link in items] == [contact_a.id]


async def test_list_contacts_filters_by_tier(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-tier@example.com", UserRole.SALES_REP)
    gold_account = await make_account(owner_id=owner.id, company="Gold Co", tier=LeadTier.GOLD)
    silver_account = await make_account(owner_id=owner.id, company="Silver Co", tier=LeadTier.SILVER)
    gold_contact = await make_contact(account_id=gold_account.id, first_name="Gold Contact")
    await make_contact(account_id=silver_account.id, first_name="Silver Contact")

    items, total = await list_contacts(db_session, tier=LeadTier.GOLD)

    assert total == 1
    assert [contact.id for contact, _link in items] == [gold_contact.id]


async def test_list_contacts_filters_by_is_primary(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-by-primary@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Primary Filter Co")
    primary_contact = await make_contact(account_id=account.id, first_name="Primary One", is_primary=True)
    await make_contact(account_id=account.id, first_name="Secondary One", is_primary=False)

    items, total = await list_contacts(db_session, is_primary=True)

    assert total == 1
    assert [contact.id for contact, _link in items] == [primary_contact.id]


async def test_list_contacts_search_matches_name_or_email(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-list-search@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Search Co")
    jane = await make_contact(account_id=account.id, first_name="Jane", email="jane-search@example.com")
    await make_contact(account_id=account.id, first_name="Someone", last_name="Else")

    items, _total = await list_contacts(db_session, search="jane")

    assert [contact.id for contact, _link in items] == [jane.id]


async def test_list_contacts_pagination_limit_offset(db_session: AsyncSession, make_account, make_contact):
    owner = await _make_user(db_session, "owner-list-pagination@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Pagination Co")
    for i in range(3):
        await make_contact(account_id=account.id, first_name=f"Paged {i}")

    items, total = await list_contacts(db_session, account_id=account.id, limit=2, offset=1)

    assert total == 3
    assert len(items) == 2


async def test_list_contacts_no_filters_returns_all_contacts_including_unlinked(
    db_session: AsyncSession, make_account, make_contact
):
    owner = await _make_user(db_session, "owner-list-unfiltered@example.com", UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Unfiltered Co")
    linked = await make_contact(account_id=account.id, first_name="Linked")
    unlinked = await create_contact(
        db_session,
        ContactCreate(first_name="Unlinked Contact", email="unlinked-contact@example.com"),
        requester=owner,
    )

    items, _total = await list_contacts(db_session)

    ids = {contact.id for contact, _link in items}
    assert linked.id in ids
    assert unlinked.id in ids


async def test_list_contacts_owner_filter_matches_any_of_multiple_linked_accounts(
    db_session: AsyncSession, make_account, make_contact
):
    owner_a = await _make_user(db_session, "owner-a-multi-link@example.com", UserRole.SALES_REP)
    owner_b = await _make_user(db_session, "owner-b-multi-link@example.com", UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner_a.id, company="Multi Link Account A")
    account_b = await make_account(owner_id=owner_b.id, company="Multi Link Account B")
    contact = await make_contact(account_id=account_a.id, first_name="Multi Linked")


    db_session.add(ContactAccount(contact_id=contact.id, account_id=account_b.id, is_primary=False))
    await db_session.flush()

    items, total = await list_contacts(db_session, owner_id=owner_b.id)

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
