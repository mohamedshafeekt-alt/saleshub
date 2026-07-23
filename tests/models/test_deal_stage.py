"""app.models.deal_stage: DealStage ORM model construction + defaults."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_company(db_session: AsyncSession, suffix: str = "1"):
    from app.models.company import Company

    company = Company(name=f"Stage Model Co {suffix}")
    db_session.add(company)
    await db_session.flush()
    return company


async def test_deal_stage_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    from app.models.deal_stage import DealStage

    company = await _make_company(db_session, "1")

    stage = DealStage(company_id=company.id, name="Received Requirement", sort_order=0, is_cold=False)
    db_session.add(stage)
    await db_session.flush()
    await db_session.refresh(stage)

    assert stage.id is not None
    assert stage.company_id == company.id
    assert stage.name == "Received Requirement"
    assert stage.sort_order == 0
    assert stage.is_cold is False
    assert stage.created_at is not None
    assert stage.updated_at is not None


async def test_deal_stage_is_cold_defaults_to_false(db_session: AsyncSession):
    from app.models.deal_stage import DealStage

    company = await _make_company(db_session, "2")

    stage = DealStage(company_id=company.id, name="Qualified to buy", sort_order=1)
    db_session.add(stage)
    await db_session.flush()
    await db_session.refresh(stage)

    assert stage.is_cold is False


async def test_company_id_is_required(db_session: AsyncSession):
    from app.models.deal_stage import DealStage

    db_session.add(DealStage(company_id=None, name="Orphan Stage", sort_order=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_name_is_required(db_session: AsyncSession):
    from app.models.deal_stage import DealStage

    company = await _make_company(db_session, "3")

    db_session.add(DealStage(company_id=company.id, name=None, sort_order=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_company_id_and_name_must_be_unique_together(db_session: AsyncSession):
    from app.models.deal_stage import DealStage

    company = await _make_company(db_session, "4")

    db_session.add(DealStage(company_id=company.id, name="Closed", sort_order=0))
    await db_session.flush()

    db_session.add(DealStage(company_id=company.id, name="Closed", sort_order=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()
