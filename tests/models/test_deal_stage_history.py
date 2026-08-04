"""app.models.deal_stage_history: DealStageHistory ORM model construction."""

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


async def _make_stage(db_session: AsyncSession, suffix: str = "1"):
    from app.models.company import Company
    from app.models.deal_stage import DealStage

    company = Company(name=f"History Stage Co {suffix}")
    db_session.add(company)
    await db_session.flush()

    stage = DealStage(company_id=company.id, name=f"History Stage {suffix}", sort_order=0)
    db_session.add(stage)
    await db_session.flush()
    return stage


async def _make_deal(db_session: AsyncSession, owner_id: int, suffix: str = "1"):
    from app.models.account import Account
    from app.models.deal import Deal

    account = Account(company=f"History Model Co {suffix}", tier=LeadTier.GOLD, owner_id=owner_id)
    db_session.add(account)
    await db_session.flush()

    stage = await _make_stage(db_session, suffix)
    deal = Deal(deal_name=f"History Model Deal {suffix}", account_id=account.id, owner_id=owner_id, stage_id=stage.id)
    db_session.add(deal)
    await db_session.flush()
    return deal


async def test_deal_stage_history_persists_with_all_fields_and_inherits_timestamps(
    db_session: AsyncSession,
):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session)
    deal = await _make_deal(db_session, owner.id, "1")
    next_stage = await _make_stage(db_session, "1-next")

    history = DealStageHistory(
        deal_id=deal.id,
        from_stage_id=deal.stage_id,
        to_stage_id=next_stage.id,
        changed_by=owner.id,
        note="Moved forward",
    )
    db_session.add(history)
    await db_session.flush()
    await db_session.refresh(history)

    assert history.id is not None
    assert history.deal_id == deal.id
    assert history.from_stage_id == deal.stage_id
    assert history.to_stage_id == next_stage.id
    assert history.changed_by == owner.id
    assert history.note == "Moved forward"
    assert history.created_at is not None
    assert history.updated_at is not None


async def test_from_stage_can_be_null(db_session: AsyncSession):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session, email="owner2@example.com")
    deal = await _make_deal(db_session, owner.id, "2")

    history = DealStageHistory(
        deal_id=deal.id,
        from_stage_id=None,
        to_stage_id=deal.stage_id,
        changed_by=owner.id,
    )
    db_session.add(history)
    await db_session.flush()
    await db_session.refresh(history)

    assert history.from_stage_id is None
    assert history.note is None


async def test_deal_id_is_required(db_session: AsyncSession):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session, email="owner3@example.com")
    stage = await _make_stage(db_session, "3")

    db_session.add(
        DealStageHistory(
            deal_id=None,
            from_stage_id=None,
            to_stage_id=stage.id,
            changed_by=owner.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_to_stage_is_required(db_session: AsyncSession):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session, email="owner4@example.com")
    deal = await _make_deal(db_session, owner.id, "4")

    db_session.add(
        DealStageHistory(deal_id=deal.id, from_stage_id=None, to_stage_id=None, changed_by=owner.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_changed_by_name_reflects_the_acting_user(db_session: AsyncSession):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session, email="owner6@example.com")
    owner.last_name = "Smith"
    deal = await _make_deal(db_session, owner.id, "6")
    next_stage = await _make_stage(db_session, "6-next")

    history = DealStageHistory(
        deal_id=deal.id,
        from_stage_id=deal.stage_id,
        to_stage_id=next_stage.id,
        changed_by=owner.id,
    )
    db_session.add(history)
    await db_session.flush()
    await db_session.refresh(history)

    assert history.changed_by_name == "Owner Smith"


async def test_changed_by_is_required(db_session: AsyncSession):
    from app.models.deal_stage_history import DealStageHistory

    owner = await _make_owner(db_session, email="owner5@example.com")
    deal = await _make_deal(db_session, owner.id, "5")

    db_session.add(
        DealStageHistory(
            deal_id=deal.id,
            from_stage_id=None,
            to_stage_id=deal.stage_id,
            changed_by=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
