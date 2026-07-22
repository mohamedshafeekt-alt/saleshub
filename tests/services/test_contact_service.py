"""app.services.contact_service: create/list/get/update/delete business rules.

Covers: create_contact propagates AccountNotFoundError for a nonexistent
account_id and AccountAccessForbiddenError when a non-owning Sales Rep
targets someone else's account; succeeds for the owning rep and for
Manager/Admin regardless of account owner. list_contacts_for_account scopes
results to the given account and enforces the same ownership gate.
get_contact/update_contact/delete_contact raise ContactNotFoundError for a
missing contact id, and delegate access-forbidden checks to the contact's
PARENT ACCOUNT (Contact has no owner_id of its own); succeed for the owning
rep and for Manager/Admin. update_contact applies only fields set (partial
update). delete_contact removes the row.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User
from tests.support.roles import UserRole, role_id_for
from app.schemas.contact import ContactCreate, ContactUpdate
from app.services.account_service import AccountAccessForbiddenError, AccountNotFoundError
from app.services.contact_service import (
    ContactNotFoundError,
    create_contact,
    delete_contact,
    get_contact,
    list_contacts_for_account,
    update_contact,
)


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test", last_name: str | None = None
) -> User:
    user = User(email=email, hashed_password="x", first_name=first_name, last_name=last_name, role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def _make_account(db_session: AsyncSession, owner_id: int, company: str = "Acme Corp"):
    from app.models.account import Account

    account = Account(company=company, tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


# --- create_contact ----------------------------------------------------------


async def test_create_contact_raises_not_found_for_nonexistent_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "creator-contact@example.com", UserRole.SALES_MANAGER)

    data = ContactCreate(first_name="Jane", account_id=999_999)
    with pytest.raises(AccountNotFoundError):
        await create_contact(db_session, data, requester=requester)


async def test_create_contact_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-create-contact@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-create-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Forbidden Create Co")

    data = ContactCreate(first_name="Jane", account_id=account.id)
    with pytest.raises(AccountAccessForbiddenError):
        await create_contact(db_session, data, requester=other_rep)


async def test_create_contact_succeeds_for_owning_sales_rep(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-create-ok-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Owned Create Co")

    data = ContactCreate(first_name="Jane", last_name="Doe", account_id=account.id)
    contact = await create_contact(db_session, data, requester=owner)

    assert contact.id is not None
    assert contact.first_name == "Jane"
    assert contact.account_id == account.id


async def test_create_contact_succeeds_for_manager_regardless_of_owner(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-create-mgr-contact@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-create-contact@example.com", UserRole.SALES_MANAGER)
    account = await _make_account(db_session, owner.id, company="Manager Create Co")

    data = ContactCreate(first_name="Jane", account_id=account.id)
    contact = await create_contact(db_session, data, requester=manager)

    assert contact.account_id == account.id


async def test_create_contact_succeeds_for_admin_regardless_of_owner(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-create-admin-contact@example.com", UserRole.SALES_REP)
    admin = await _make_user(db_session, "admin-create-contact@example.com", UserRole.ADMIN)
    account = await _make_account(db_session, owner.id, company="Admin Create Co")

    data = ContactCreate(first_name="Jane", account_id=account.id)
    contact = await create_contact(db_session, data, requester=admin)

    assert contact.account_id == account.id


# --- list_contacts_for_account -----------------------------------------------


async def test_list_contacts_for_account_returns_only_that_accounts_contacts(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-list-contact@example.com", UserRole.SALES_REP)
    account_a = await _make_account(db_session, owner.id, company="List Co A")
    account_b = await _make_account(db_session, owner.id, company="List Co B")
    contact_a = await make_contact(account_id=account_a.id, first_name="A Contact")
    await make_contact(account_id=account_b.id, first_name="B Contact")

    results, _total = await list_contacts_for_account(db_session, account_id=account_a.id, requester=owner)

    assert [contact.id for contact in results] == [contact_a.id]


async def test_list_contacts_for_account_raises_not_found_for_missing_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "lister-404-contact@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await list_contacts_for_account(db_session, account_id=999_999, requester=requester)


async def test_list_contacts_for_account_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-list-forbidden-contact@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-list-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="List Forbidden Co")
    await make_contact(account_id=account.id)

    with pytest.raises(AccountAccessForbiddenError):
        await list_contacts_for_account(db_session, account_id=account.id, requester=other_rep)


# --- get_contact --------------------------------------------------------------


async def test_get_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "getter-contact@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=999_999, requester=requester)


async def test_get_contact_raises_forbidden_for_non_owning_sales_rep_via_parent_account(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-get-forbidden-contact@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-get-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Get Forbidden Co")
    contact = await make_contact(account_id=account.id)

    with pytest.raises(AccountAccessForbiddenError):
        await get_contact(db_session, contact_id=contact.id, requester=other_rep)


async def test_get_contact_succeeds_for_owning_sales_rep(db_session: AsyncSession, make_contact):
    owner = await _make_user(db_session, "owner-get-ok-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Get Ok Co")
    contact = await make_contact(account_id=account.id)

    fetched = await get_contact(db_session, contact_id=contact.id, requester=owner)

    assert fetched.id == contact.id


async def test_get_contact_succeeds_for_manager_regardless_of_owner(db_session: AsyncSession, make_contact):
    owner = await _make_user(db_session, "owner-get-mgr-contact@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-get-contact@example.com", UserRole.SALES_MANAGER)
    account = await _make_account(db_session, owner.id, company="Get Manager Co")
    contact = await make_contact(account_id=account.id)

    fetched = await get_contact(db_session, contact_id=contact.id, requester=manager)

    assert fetched.id == contact.id


# --- update_contact -------------------------------------------------------------


async def test_update_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "updater-contact@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(ContactNotFoundError):
        await update_contact(
            db_session, contact_id=999_999, data=ContactUpdate(first_name="New"), requester=requester
        )


async def test_update_contact_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-upd-forbidden-contact@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upd-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Update Forbidden Co")
    contact = await make_contact(account_id=account.id)

    with pytest.raises(AccountAccessForbiddenError):
        await update_contact(
            db_session, contact_id=contact.id, data=ContactUpdate(first_name="New"), requester=other_rep
        )


async def test_update_contact_applies_partial_changes(db_session: AsyncSession, make_contact):
    owner = await _make_user(db_session, "owner-upd-ok-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Update Ok Co")
    contact = await make_contact(
        account_id=account.id, first_name="Old", last_name="Name", job_title="Old Title"
    )

    updated = await update_contact(
        db_session, contact_id=contact.id, data=ContactUpdate(first_name="New"), requester=owner
    )

    assert updated.first_name == "New"
    assert updated.last_name == "Name"  # untouched field preserved
    assert updated.job_title == "Old Title"  # untouched field preserved


async def test_update_contact_succeeds_for_admin_regardless_of_owner(db_session: AsyncSession, make_contact):
    owner = await _make_user(db_session, "owner-upd-admin-contact@example.com", UserRole.SALES_REP)
    admin = await _make_user(db_session, "admin-upd-contact@example.com", UserRole.ADMIN)
    account = await _make_account(db_session, owner.id, company="Update Admin Co")
    contact = await make_contact(account_id=account.id)

    updated = await update_contact(
        db_session, contact_id=contact.id, data=ContactUpdate(first_name="Admin Updated"), requester=admin
    )

    assert updated.first_name == "Admin Updated"


# --- delete_contact -------------------------------------------------------------


async def test_delete_contact_raises_not_found_for_missing_id(db_session: AsyncSession):
    requester = await _make_user(db_session, "deleter-contact@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(ContactNotFoundError):
        await delete_contact(db_session, contact_id=999_999, requester=requester)


async def test_delete_contact_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-del-forbidden-contact@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-del-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Delete Forbidden Co")
    contact = await make_contact(account_id=account.id)

    with pytest.raises(AccountAccessForbiddenError):
        await delete_contact(db_session, contact_id=contact.id, requester=other_rep)


async def test_delete_contact_removes_the_row(db_session: AsyncSession, make_contact):
    owner = await _make_user(db_session, "owner-del-ok-contact@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Delete Ok Co")
    contact = await make_contact(account_id=account.id)
    contact_id = contact.id

    await delete_contact(db_session, contact_id=contact_id, requester=owner)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=contact_id, requester=owner)


async def test_delete_contact_succeeds_for_manager_regardless_of_owner(
    db_session: AsyncSession, make_contact
):
    owner = await _make_user(db_session, "owner-del-mgr-contact@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-del-contact@example.com", UserRole.SALES_MANAGER)
    account = await _make_account(db_session, owner.id, company="Delete Manager Co")
    contact = await make_contact(account_id=account.id)
    contact_id = contact.id

    await delete_contact(db_session, contact_id=contact_id, requester=manager)

    with pytest.raises(ContactNotFoundError):
        await get_contact(db_session, contact_id=contact_id, requester=manager)
