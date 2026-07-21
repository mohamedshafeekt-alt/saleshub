"""DB-level trigger: inserting into lead_activities bumps the parent lead's
updated_at, even when the row is added directly with raw SQL rather than
through the ORM/service layer (the case the requirement calls out explicitly).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadSource
from app.models.lead import Lead
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def test_raw_sql_insert_into_lead_activities_touches_lead_updated_at(db_session: AsyncSession):
    user = User(email="trigger-user@example.com", hashed_password="x", first_name="Rep", role_id=await role_id_for(db_session, UserRole.SALES_REP))
    db_session.add(user)
    await db_session.flush()

    lead = Lead(
        first_name="Jane",
        company="Acme Corp",
        email="trigger-lead@example.com",
        source=LeadSource.WEBSITE,
        owner_id=user.id,
    )
    db_session.add(lead)
    await db_session.flush()
    await db_session.refresh(lead)
    original_updated_at = lead.updated_at

    await db_session.execute(
        text(
            "INSERT INTO lead_activities (lead_id, type, note, created_by) "
            "VALUES (:lead_id, 'note', 'raw insert', :user_id)"
        ),
        {"lead_id": lead.id, "user_id": user.id},
    )

    await db_session.refresh(lead)

    assert lead.updated_at > original_updated_at
