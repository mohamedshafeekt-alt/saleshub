"""app.services.contact_account_service: the "Add Contact"/"Edit Contact"
modal on the Account Detail page.

Covers: create_account_contact creates a Contact + its ContactAccount link
in one call, propagates AccountNotFoundError/AccountAccessForbiddenError via
account_service.get_account, and raises PrimaryContactAlreadyExistsError if
is_primary=True is requested for an account that already has one.
update_account_contact updates Contact fields (partial) and/or is_primary,
creates the link if one doesn't exist yet (associating an existing contact
with a new account), raises ContactNotFoundError for a missing contact id,
and enforces the same one-primary-per-account rule -- except re-saving the
CURRENT primary as still-primary is a no-op, not a conflict.
list_account_contacts scopes results to the given account (with each
contact's is_primary for that account) and enforces the same ownership gate.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User
from app.schemas.contact_account import AccountContactUpsert
from tests.support.roles import UserRole, role_id_for
from app.services.account_service import (
    AccountAccessForbiddenError,
    AccountNotFoundError,
    PrimaryContactAlreadyExistsError,
)
from app.services.contact_account_service import (
    ContactNotFoundError,
    create_account_contact,
    list_account_contacts,
    update_account_contact,
)
from app.services.contact_service import DuplicateContactEmailError


async def _make_user(
    db_session: AsyncSession, email: str, role: UserRole, first_name: str = "Test"
) -> User:
    user = User(
        email=email,
        hashed_password="x",
        first_name=first_name,
        role_id=await role_id_for(db_session, role),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_account(db_session: AsyncSession, owner_id: int, company: str = "Acme Corp"):
    from app.models.account import Account

    account = Account(company=company, tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


# --- create_account_contact ---------------------------------------------------


async def test_create_account_contact_creates_contact_and_link(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-cac-create@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Create Contact Co")

    data = AccountContactUpsert(
        first_name="Sarah",
        last_name="Jenkins",
        email="sarah-cac-create@example.com",
        job_title="CTO",
        is_primary=True,
    )
    contact, contact_account = await create_account_contact(db_session, account.id, data, requester=owner)

    assert contact.id is not None
    assert contact.first_name == "Sarah"
    assert contact_account.account_id == account.id
    assert contact_account.contact_id == contact.id
    assert contact_account.is_primary is True


async def test_create_account_contact_writes_audit_log(db_session: AsyncSession):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    owner = await _make_user(db_session, "owner-cac-audit-create@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Audit Contact Co")

    data = AccountContactUpsert(
        first_name="Priya", last_name="Nair", email="priya-cac-audit@example.com",
    )
    contact, _ = await create_account_contact(db_session, account.id, data, requester=owner)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "contacts", AuditLog.record_id == contact.id)
    )
    entry = result.scalar_one()
    assert entry.action == "created"
    assert entry.actor_id == owner.id


async def test_create_account_contact_raises_not_found_for_nonexistent_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "cac-404@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await create_account_contact(
            db_session,
            999_999,
            AccountContactUpsert(first_name="Jane", email="jane-cac-404@example.com"),
            requester=requester,
        )


async def test_create_account_contact_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-cac-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-cac-forbidden@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Forbidden Contact Co")

    with pytest.raises(AccountAccessForbiddenError):
        await create_account_contact(
            db_session,
            account.id,
            AccountContactUpsert(first_name="Jane", email="jane-cac-forbidden@example.com"),
            requester=other_rep,
        )


async def test_create_account_contact_raises_conflict_when_primary_already_exists(
    db_session: AsyncSession,
):
    owner = await _make_user(db_session, "owner-cac-conflict@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Primary Conflict Co")
    await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="First", email="first-cac-conflict@example.com", is_primary=True),
        requester=owner,
    )

    with pytest.raises(PrimaryContactAlreadyExistsError):
        await create_account_contact(
            db_session,
            account.id,
            AccountContactUpsert(
                first_name="Second", email="second-cac-conflict@example.com", is_primary=True
            ),
            requester=owner,
        )


async def test_create_account_contact_second_non_primary_contact_succeeds(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-cac-second@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Second Contact Co")
    await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="First", email="first-cac-second@example.com", is_primary=True),
        requester=owner,
    )

    contact, contact_account = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Second", email="second-cac-second@example.com"),
        requester=owner,
    )

    assert contact.first_name == "Second"
    assert contact_account.is_primary is False


async def test_create_account_contact_raises_duplicate_email_for_existing_email_anywhere(
    db_session: AsyncSession,
):
    """Email uniqueness is global across all contacts, not scoped to one
    account -- a different name and a different (or the same) account still
    counts as a duplicate."""
    owner_a = await _make_user(db_session, "owner-cac-dup-a@example.com", UserRole.SALES_REP)
    owner_b = await _make_user(db_session, "owner-cac-dup-b@example.com", UserRole.SALES_REP)
    account_a = await _make_account(db_session, owner_a.id, company="Dup Email Co A")
    account_b = await _make_account(db_session, owner_b.id, company="Dup Email Co B")
    await create_account_contact(
        db_session,
        account_a.id,
        AccountContactUpsert(first_name="Original", email="dup-cac@example.com"),
        requester=owner_a,
    )

    with pytest.raises(DuplicateContactEmailError):
        await create_account_contact(
            db_session,
            account_b.id,
            AccountContactUpsert(first_name="Completely Different Name", email="dup-cac@example.com"),
            requester=owner_b,
        )


# --- update_account_contact ----------------------------------------------------


async def test_update_account_contact_writes_audit_log(db_session: AsyncSession):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    owner = await _make_user(db_session, "owner-uac-audit@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Audit Update Co")
    contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Old", email="old-uac-audit@example.com"),
        requester=owner,
    )

    await update_account_contact(
        db_session, account.id, contact.id,
        AccountContactUpsert(contact_id=contact.id, first_name="New"), requester=owner,
    )
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.table_name == "contacts", AuditLog.record_id == contact.id, AuditLog.action == "updated"
        )
    )
    assert result.scalar_one() is not None


async def test_update_account_contact_updates_contact_fields(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-uac-fields@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Update Fields Co")
    contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Old", email="old-uac-fields@example.com", job_title="Old Title"),
        requester=owner,
    )

    updated_contact, _ = await update_account_contact(
        db_session,
        account.id,
        contact.id,
        AccountContactUpsert(contact_id=contact.id, first_name="New"),
        requester=owner,
    )

    assert updated_contact.first_name == "New"
    assert updated_contact.job_title == "Old Title"  # untouched field preserved


async def test_update_account_contact_raises_not_found_for_missing_contact(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-uac-404@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Missing Contact Co")

    with pytest.raises(ContactNotFoundError):
        await update_account_contact(
            db_session,
            account.id,
            999_999,
            AccountContactUpsert(contact_id=999_999, first_name="New"),
            requester=owner,
        )


async def test_update_account_contact_raises_not_found_for_missing_account(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-uac-acc-404@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Real Account Co")
    contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Real", email="real-uac-acc-404@example.com"),
        requester=owner,
    )

    with pytest.raises(AccountNotFoundError):
        await update_account_contact(
            db_session,
            999_999,
            contact.id,
            AccountContactUpsert(contact_id=contact.id, first_name="New"),
            requester=owner,
        )


async def test_update_account_contact_creates_link_for_existing_contact_new_account(
    db_session: AsyncSession,
):
    owner = await _make_user(db_session, "owner-uac-relink@example.com", UserRole.SALES_REP)
    account_a = await _make_account(db_session, owner.id, company="Origin Co")
    account_b = await _make_account(db_session, owner.id, company="Destination Co")
    contact, _ = await create_account_contact(
        db_session,
        account_a.id,
        AccountContactUpsert(first_name="Shared", email="shared-uac-relink@example.com"),
        requester=owner,
    )

    _, contact_account = await update_account_contact(
        db_session, account_b.id, contact.id, AccountContactUpsert(contact_id=contact.id), requester=owner
    )

    assert contact_account.account_id == account_b.id
    assert contact_account.contact_id == contact.id
    assert contact_account.is_primary is False

    results, _total = await list_account_contacts(db_session, account_b.id, requester=owner)
    assert [c.id for c, _is_primary in results] == [contact.id]


async def test_update_account_contact_sets_is_primary(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-uac-primary@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Set Primary Co")
    contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="ToPromote", email="topromote-uac-primary@example.com"),
        requester=owner,
    )

    _, contact_account = await update_account_contact(
        db_session,
        account.id,
        contact.id,
        AccountContactUpsert(contact_id=contact.id, is_primary=True),
        requester=owner,
    )

    assert contact_account.is_primary is True


async def test_update_account_contact_resaving_current_primary_is_not_a_conflict(
    db_session: AsyncSession,
):
    owner = await _make_user(db_session, "owner-uac-resave@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Resave Primary Co")
    contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(
            first_name="AlreadyPrimary", email="alreadyprimary-uac-resave@example.com", is_primary=True
        ),
        requester=owner,
    )

    # Should not raise even though this account already has a primary contact
    # -- it's the same contact being re-saved, not a new claim on the slot.
    _, contact_account = await update_account_contact(
        db_session,
        account.id,
        contact.id,
        AccountContactUpsert(contact_id=contact.id, job_title="Updated Title", is_primary=True),
        requester=owner,
    )

    assert contact_account.is_primary is True


async def test_update_account_contact_raises_conflict_promoting_second_contact(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-uac-conflict@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="Promote Conflict Co")
    await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Existing", email="existing-uac-conflict@example.com", is_primary=True),
        requester=owner,
    )
    second_contact, _ = await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Second", email="second-uac-conflict@example.com"),
        requester=owner,
    )

    with pytest.raises(PrimaryContactAlreadyExistsError):
        await update_account_contact(
            db_session,
            account.id,
            second_contact.id,
            AccountContactUpsert(contact_id=second_contact.id, is_primary=True),
            requester=owner,
        )


# --- list_account_contacts ------------------------------------------------------


async def test_list_account_contacts_returns_only_that_accounts_contacts_with_is_primary(
    db_session: AsyncSession,
):
    owner = await _make_user(db_session, "owner-lac-scope@example.com", UserRole.SALES_REP)
    account_a = await _make_account(db_session, owner.id, company="List Co A")
    account_b = await _make_account(db_session, owner.id, company="List Co B")
    contact_a, _ = await create_account_contact(
        db_session,
        account_a.id,
        AccountContactUpsert(first_name="A Contact", email="a-contact-lac-scope@example.com", is_primary=True),
        requester=owner,
    )
    await create_account_contact(
        db_session,
        account_b.id,
        AccountContactUpsert(first_name="B Contact", email="b-contact-lac-scope@example.com"),
        requester=owner,
    )

    results, total = await list_account_contacts(db_session, account_a.id, requester=owner)

    assert total == 1
    assert [(c.id, is_primary) for c, is_primary in results] == [(contact_a.id, True)]


async def test_list_account_contacts_raises_not_found_for_missing_account(db_session: AsyncSession):
    requester = await _make_user(db_session, "lac-404@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(AccountNotFoundError):
        await list_account_contacts(db_session, 999_999, requester=requester)


async def test_list_account_contacts_raises_forbidden_for_non_owning_sales_rep(db_session: AsyncSession):
    owner = await _make_user(db_session, "owner-lac-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-lac-forbidden@example.com", UserRole.SALES_REP)
    account = await _make_account(db_session, owner.id, company="List Forbidden Co")
    await create_account_contact(
        db_session,
        account.id,
        AccountContactUpsert(first_name="Someone", email="someone-lac-forbidden@example.com"),
        requester=owner,
    )

    with pytest.raises(AccountAccessForbiddenError):
        await list_account_contacts(db_session, account.id, requester=other_rep)
