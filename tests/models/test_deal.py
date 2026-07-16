"""app.models.deal: Deal ORM model construction + defaults."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadTier
from app.models.user import User, UserRole


async def _make_owner(db_session: AsyncSession, email: str = "owner@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role=UserRole.SALES_REP)
    db_session.add(owner)
    await db_session.flush()
    return owner


async def _make_account(db_session: AsyncSession, owner_id: int, suffix: str = "1"):
    from app.models.account import Account

    account = Account(company=f"Deal Model Co {suffix}", tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()
    return account


async def test_deal_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    from app.models.deal import Deal
    from app.models.enums import DealStage

    owner = await _make_owner(db_session)
    account = await _make_account(db_session, owner.id, "1")

    deal = Deal(
        deal_name="Big Deal",
        account_id=account.id,
        value=50000.0,
        currency="EUR",
        expected_close_date=date(2026, 12, 31),
        stage=DealStage.EVALUATION,
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
    assert deal.stage == DealStage.EVALUATION
    assert deal.cold_reason is None
    assert deal.owner_id == owner.id
    assert deal.created_at is not None
    assert deal.updated_at is not None


async def test_deal_persists_with_only_required_fields_and_applies_defaults(db_session: AsyncSession):
    from app.models.deal import Deal
    from app.models.enums import DealStage

    owner = await _make_owner(db_session, email="owner2@example.com")
    account = await _make_account(db_session, owner.id, "2")

    deal = Deal(deal_name="Minimal Deal", account_id=account.id, owner_id=owner.id)
    db_session.add(deal)
    await db_session.flush()
    await db_session.refresh(deal)

    assert deal.currency == "USD"
    assert deal.stage == DealStage.RECEIVED_REQUIREMENTS
    assert deal.value is None
    assert deal.expected_close_date is None
    assert deal.cold_reason is None


async def test_deal_name_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner3@example.com")
    account = await _make_account(db_session, owner.id, "3")

    db_session.add(Deal(deal_name=None, account_id=account.id, owner_id=owner.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_account_id_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner4@example.com")

    db_session.add(Deal(deal_name="No Account Deal", account_id=None, owner_id=owner.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_owner_id_is_required(db_session: AsyncSession):
    from app.models.deal import Deal

    owner = await _make_owner(db_session, email="owner5@example.com")
    account = await _make_account(db_session, owner.id, "5")

    db_session.add(Deal(deal_name="No Owner Deal", account_id=account.id, owner_id=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
