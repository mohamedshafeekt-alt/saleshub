"""app.services.deal_stage_service: CRUD + delete guard when a stage is
still referenced by deals."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.deal_stage import DealStageCreate, DealStageUpdate
from app.services.deal_stage_service import (
    DealStageInUseError,
    DealStageNotFoundError,
    create_deal_stage,
    delete_deal_stage,
    get_deal_stage,
    list_deal_stages,
    update_deal_stage,
)


async def test_create_deal_stage_persists(db_session: AsyncSession, make_company):
    company = await make_company(name="Create Stage Co")

    data = DealStageCreate(company_id=company.id, name="Received Requirement", sort_order=0)
    stage = await create_deal_stage(db_session, data)

    assert stage.id is not None
    assert stage.company_id == company.id
    assert stage.name == "Received Requirement"
    assert stage.is_cold is False


async def test_list_deal_stages_orders_by_sort_order(db_session: AsyncSession, make_company, make_deal_stage):
    company = await make_company(name="List Stage Co")
    second = await make_deal_stage(company_id=company.id, name="Second", sort_order=1)
    first = await make_deal_stage(company_id=company.id, name="First", sort_order=0)

    stages = await list_deal_stages(db_session, company_id=company.id)

    assert [stage.id for stage in stages] == [first.id, second.id]


async def test_list_deal_stages_filters_by_company_id(db_session: AsyncSession, make_company, make_deal_stage):
    company_a = await make_company(name="Filter Stage Co A")
    company_b = await make_company(name="Filter Stage Co B")
    stage_a = await make_deal_stage(company_id=company_a.id, name="Stage A")
    await make_deal_stage(company_id=company_b.id, name="Stage B")

    stages = await list_deal_stages(db_session, company_id=company_a.id)

    assert [stage.id for stage in stages] == [stage_a.id]


async def test_get_deal_stage_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(DealStageNotFoundError):
        await get_deal_stage(db_session, 999_999)


async def test_get_deal_stage_returns_stage(db_session: AsyncSession, make_deal_stage):
    stage = await make_deal_stage(name="Get Stage")

    fetched = await get_deal_stage(db_session, stage.id)

    assert fetched.id == stage.id


async def test_update_deal_stage_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(DealStageNotFoundError):
        await update_deal_stage(db_session, 999_999, DealStageUpdate(name="New Name"))


async def test_update_deal_stage_applies_partial_changes(db_session: AsyncSession, make_deal_stage):
    stage = await make_deal_stage(name="Old Name", sort_order=0)

    updated = await update_deal_stage(db_session, stage.id, DealStageUpdate(name="New Name"))

    assert updated.name == "New Name"
    assert updated.sort_order == 0


async def test_delete_deal_stage_raises_not_found_for_missing_id(db_session: AsyncSession):
    with pytest.raises(DealStageNotFoundError):
        await delete_deal_stage(db_session, 999_999)


async def test_delete_deal_stage_removes_unused_stage(db_session: AsyncSession, make_deal_stage):
    stage = await make_deal_stage(name="Deletable Stage")

    await delete_deal_stage(db_session, stage.id)

    with pytest.raises(DealStageNotFoundError):
        await get_deal_stage(db_session, stage.id)


async def test_delete_deal_stage_raises_in_use_when_referenced_by_a_deal(
    db_session: AsyncSession, make_account, make_deal, make_deal_stage
):
    from tests.support.roles import UserRole, role_id_for
    from app.models.user import User

    owner = User(
        email="owner-stage-in-use@example.com",
        hashed_password="x",
        first_name="Owner",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(owner)
    await db_session.flush()

    account = await make_account(owner_id=owner.id, company="Stage In Use Co")
    stage = await make_deal_stage(name="In Use Stage")
    await make_deal(account_id=account.id, owner_id=owner.id, deal_name="In Use Deal", stage_id=stage.id)

    with pytest.raises(DealStageInUseError):
        await delete_deal_stage(db_session, stage.id)
