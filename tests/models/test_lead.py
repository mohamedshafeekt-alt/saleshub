"""app.models.lead: Lead ORM model construction + constraints."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource, LeadStatus, LeadTier
from app.models.user import User, UserRole


async def _make_owner(db_session: AsyncSession, email: str = "owner@example.com") -> User:
    owner = User(email=email, hashed_password="x", first_name="Owner", role=UserRole.SALES_REP)
    db_session.add(owner)
    await db_session.flush()
    return owner


async def test_lead_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session)

    lead = Lead(
        first_name="Jane",
        last_name="Doe",
        company="Acme Corp",
        domain="acme.com",
        job_title="VP Sales",
        email="jane.doe@acme.com",
        phone="+1-555-0100",
        linkedin_url="https://linkedin.com/in/janedoe",
        source=LeadSource.REFERRAL,
        tier=LeadTier.DIAMOND,
        owner_id=owner.id,
        next_follow_up_date=date(2026, 8, 1),
        follow_up_note="Call back after Q3 budget review",
    )
    db_session.add(lead)
    await db_session.flush()
    await db_session.refresh(lead)

    assert lead.id is not None
    assert lead.first_name == "Jane"
    assert lead.last_name == "Doe"
    assert lead.company == "Acme Corp"
    assert lead.domain == "acme.com"
    assert lead.job_title == "VP Sales"
    assert lead.email == "jane.doe@acme.com"
    assert lead.phone == "+1-555-0100"
    assert lead.linkedin_url == "https://linkedin.com/in/janedoe"
    assert lead.source == LeadSource.REFERRAL
    assert lead.tier == LeadTier.DIAMOND
    assert lead.owner_id == owner.id
    assert lead.next_follow_up_date == date(2026, 8, 1)
    assert lead.follow_up_note == "Call back after Q3 budget review"
    assert lead.created_at is not None
    assert lead.updated_at is not None


async def test_lead_persists_with_only_required_fields(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session, email="owner2@example.com")

    lead = Lead(
        first_name="Min",
        company="Minimal Co",
        email="min@minimal.co",
        source=LeadSource.WEBSITE,
        tier=LeadTier.BRONZE,
        owner_id=owner.id,
    )
    db_session.add(lead)
    await db_session.flush()
    await db_session.refresh(lead)

    assert lead.last_name is None
    assert lead.domain is None
    assert lead.job_title is None
    assert lead.phone is None
    assert lead.linkedin_url is None
    assert lead.next_follow_up_date is None
    assert lead.follow_up_note is None


async def test_duplicate_email_violates_unique_constraint(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session, email="owner3@example.com")

    db_session.add(
        Lead(
            first_name="A",
            company="Co A",
            email="dupe-lead@example.com",
            source=LeadSource.WEBSITE,
            tier=LeadTier.SILVER,
            owner_id=owner.id,
        )
    )
    await db_session.flush()

    db_session.add(
        Lead(
            first_name="B",
            company="Co B",
            email="dupe-lead@example.com",
            source=LeadSource.COLD_CALL,
            tier=LeadTier.GOLD,
            owner_id=owner.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_company_is_required(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session, email="owner4@example.com")

    db_session.add(
        Lead(
            first_name="No",
            company=None,
            email="no-company@example.com",
            source=LeadSource.WEBSITE,
            tier=LeadTier.SILVER,
            owner_id=owner.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_lead_tier_and_owner_id_are_nullable(db_session: AsyncSession):
    from app.models.lead import Lead

    lead = Lead(
        first_name="No",
        company="Untiered Co",
        email="untiered-unassigned@example.com",
        source=LeadSource.WEBSITE,
        tier=None,
        owner_id=None,
    )
    db_session.add(lead)
    await db_session.flush()
    await db_session.refresh(lead)

    assert lead.tier is None
    assert lead.owner_id is None


async def test_lead_status_defaults_to_not_contacted(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session, email="owner-status-default@example.com")

    lead = Lead(
        first_name="No",
        company="Status Default Co",
        email="status-default-model@example.com",
        source=LeadSource.WEBSITE,
        tier=LeadTier.SILVER,
        owner_id=owner.id,
    )
    db_session.add(lead)
    await db_session.flush()
    await db_session.refresh(lead)

    assert lead.status == LeadStatus.NOT_CONTACTED


async def test_source_is_required(db_session: AsyncSession):
    from app.models.lead import Lead

    owner = await _make_owner(db_session, email="owner5@example.com")

    db_session.add(
        Lead(
            first_name="No",
            company="No Source Co",
            email="no-source@example.com",
            source=None,
            tier=LeadTier.SILVER,
            owner_id=owner.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
