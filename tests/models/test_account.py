"""app.models.account: Account ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource, LeadTier
from app.models.user import User, UserRole


async def _make_owner(db_session: AsyncSession, email: str = "owner@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role=UserRole.SALES_REP)
    db_session.add(owner)
    await db_session.flush()
    return owner


async def test_account_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    from app.models.account import Account
    from app.models.lead import Lead

    owner = await _make_owner(db_session)
    source_lead = Lead(
        first_name="Jane",
        company="Acme Corp",
        email="jane.doe@acme.com",
        source=LeadSource.WEBSITE,
        tier=LeadTier.GOLD,
        owner_id=owner.id,
    )
    db_session.add(source_lead)
    await db_session.flush()

    account = Account(
        company="Acme Corp",
        domain="acme.com",
        tier=LeadTier.DIAMOND,
        owner_id=owner.id,
        source_lead_id=source_lead.id,
    )
    db_session.add(account)
    await db_session.flush()
    await db_session.refresh(account)

    assert account.id is not None
    assert account.company == "Acme Corp"
    assert account.domain == "acme.com"
    assert account.tier == LeadTier.DIAMOND
    assert account.owner_id == owner.id
    assert account.source_lead_id == source_lead.id
    assert account.created_at is not None
    assert account.updated_at is not None


async def test_account_persists_with_only_required_fields(db_session: AsyncSession):
    from app.models.account import Account

    owner = await _make_owner(db_session, email="owner2@example.com")

    account = Account(company="Minimal Co", tier=LeadTier.BRONZE, owner_id=owner.id)
    db_session.add(account)
    await db_session.flush()
    await db_session.refresh(account)

    assert account.domain is None
    assert account.source_lead_id is None


async def test_account_accepts_all_lead_tier_values(db_session: AsyncSession):
    from app.models.account import Account

    owner = await _make_owner(db_session, email="owner3@example.com")

    for index, tier in enumerate(LeadTier):
        account = Account(company=f"Tier Co {index}", tier=tier, owner_id=owner.id)
        db_session.add(account)
        await db_session.flush()
        await db_session.refresh(account)
        assert account.tier == tier


async def test_company_is_required(db_session: AsyncSession):
    from app.models.account import Account

    owner = await _make_owner(db_session, email="owner4@example.com")

    db_session.add(Account(company=None, tier=LeadTier.SILVER, owner_id=owner.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_owner_id_is_required(db_session: AsyncSession):
    from app.models.account import Account

    db_session.add(Account(company="No Owner Co", tier=LeadTier.SILVER, owner_id=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_tier_is_required(db_session: AsyncSession):
    from app.models.account import Account

    owner = await _make_owner(db_session, email="owner5@example.com")

    db_session.add(Account(company="No Tier Co", tier=None, owner_id=owner.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
