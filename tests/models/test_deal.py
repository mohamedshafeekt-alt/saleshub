"""app.models.deal: Deal ORM model construction + defaults."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def _make_owner(db_session: AsyncSession, email: str = "owner@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role_id=await role_id_for(db_session, UserRole.SALES_REP))
    db_session.add(owner)
    await db_session.flush()
    return owner


async def _make_account(db_session: AsyncSession, owner_id: int, suffix: str = "1"):
    from app.models.account import Account

    account = Account(company=f"Deal Model Co {suffix}", tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


async def _make_stage(db_session: AsyncSession, suffix: str = "1", is_cold: bool = False):
    from app.models.company import Company
    from app.models.deal_stage import DealStage

    company = Company(name=f"Deal Model Stage Co {suffix}")
    db_session.add(company)
    await db_session.flush()

    stage = DealStage(company_id=company.id, name=f"Stage {suffix}", sort_order=0, is_cold=is_cold)
    db_session.add(stage)
    await db_session.flush()
    return stage


async def test_deal_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session)
    account = await _make_account(db_session, owner.id, "1")
    stage = await _make_stage(db_session, "1")

    deal = Deal(
        deal_name="Big Deal",
        account_id=account.id,
        value=50000.0,
        currency="EUR",
        expected_close_date=date(2026, 12, 31),
        stage_id=stage.id,
        tier=LeadTier.DIAMOND,
        cold_reason=None,
        owner_id=owner.id,
    )
    db_session.add(deal)
    await db_session.flush()
    await db_session.refresh(deal)

    assert deal.id is not None
    assert deal.deal_name == "Big Deal"
    assert deal.account_id == account.id
    assert deal.value == 50000.0
    assert deal.currency == "EUR"
    assert deal.expected_close_date == date(2026, 12, 31)
    assert deal.stage_id == stage.id
    assert deal.tier == LeadTier.DIAMOND
    assert deal.cold_reason is None
    assert deal.owner_id == owner.id
    assert deal.created_at is not None
    assert deal.updated_at is not None


async def test_deal_persists_with_only_required_fields_and_applies_defaults(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner2@example.com")
    account = await _make_account(db_session, owner.id, "2")
    stage = await _make_stage(db_session, "2")

    deal = Deal(deal_name="Minimal Deal", account_id=account.id, owner_id=owner.id, stage_id=stage.id)
    db_session.add(deal)
    await db_session.flush()
    await db_session.refresh(deal)

    assert deal.currency == "USD"
    assert deal.value is None
    assert deal.expected_close_date is None
    assert deal.cold_reason is None
    assert deal.tier is None


async def test_deal_name_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner3@example.com")
    account = await _make_account(db_session, owner.id, "3")
    stage = await _make_stage(db_session, "3")

    db_session.add(Deal(deal_name=None, account_id=account.id, owner_id=owner.id, stage_id=stage.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_account_id_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner4@example.com")
    stage = await _make_stage(db_session, "4")

    db_session.add(
        Deal(deal_name="No Account Deal", account_id=None, owner_id=owner.id, stage_id=stage.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_owner_id_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner5@example.com")
    account = await _make_account(db_session, owner.id, "5")
    stage = await _make_stage(db_session, "5")

    db_session.add(
        Deal(deal_name="No Owner Deal", account_id=account.id, owner_id=None, stage_id=stage.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_stage_id_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner6@example.com")
    account = await _make_account(db_session, owner.id, "6")

    db_session.add(
        Deal(deal_name="No Stage Deal", account_id=account.id, owner_id=owner.id, stage_id=None)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deal_can_reference_multiple_contacts(db_session: AsyncSession):
    from app.models.contact import Contact
    from app.models.deal import Deal
    from app.models.deal_contact import DealContact
    from sqlalchemy import select

    owner = await _make_owner(db_session, email="owner7@example.com")
    account = await _make_account(db_session, owner.id, "7")
    stage = await _make_stage(db_session, "7")
    contact_a = Contact(first_name="Cara", account_id=account.id)
    contact_b = Contact(first_name="Dara", account_id=account.id)
    db_session.add_all([contact_a, contact_b])
    await db_session.flush()

    deal = Deal(
        deal_name="Contact Deal",
        account_id=account.id,
        owner_id=owner.id,
        stage_id=stage.id,
    )
    db_session.add(deal)
    await db_session.flush()

    db_session.add_all(
        [
            DealContact(deal_id=deal.id, contact_id=contact_a.id),
            DealContact(deal_id=deal.id, contact_id=contact_b.id),
        ]
    )
    await db_session.flush()

    result = await db_session.execute(select(DealContact.contact_id).where(DealContact.deal_id == deal.id))
    linked_ids = set(result.scalars().all())
    assert linked_ids == {contact_a.id, contact_b.id}
