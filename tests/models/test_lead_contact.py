"""app.models.lead_contact: LeadContact ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource
from app.models.lead import Lead
from app.models.lead_contact import LeadContact
from app.models.user import User, UserRole


async def _make_lead(db_session: AsyncSession, email: str = "lead@example.com") -> Lead:
    owner = User(email=f"owner-{email}", hashed_password="x", first_name="Owner", role=UserRole.SALES_REP)
    db_session.add(owner)
    await db_session.flush()

    lead = Lead(
        first_name="Jane",
        company="Acme Corp",
        email=email,
        source=LeadSource.WEBSITE,
        owner_id=owner.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def test_lead_contact_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    lead = await _make_lead(db_session)

    contact = LeadContact(lead_id=lead.id, email="extra@example.com", phone="+1-555-0100")
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.id is not None
    assert contact.lead_id == lead.id
    assert contact.email == "extra@example.com"
    assert contact.phone == "+1-555-0100"
    assert contact.created_at is not None
    assert contact.updated_at is not None


async def test_lead_contact_email_and_phone_are_nullable(db_session: AsyncSession):
    lead = await _make_lead(db_session, email="nullable-fields@example.com")

    contact = LeadContact(lead_id=lead.id, email=None, phone=None)
    db_session.add(contact)
    await db_session.flush()
    await db_session.refresh(contact)

    assert contact.email is None
    assert contact.phone is None


async def test_lead_id_is_required(db_session: AsyncSession):
    db_session.add(LeadContact(lead_id=None, email="orphan@example.com"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
