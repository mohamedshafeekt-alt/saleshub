"""DB-level trigger: inserting into deal_activities bumps the parent deal's
updated_at, even via raw SQL bypassing the service layer.
Mirrors tests/db/test_lead_activity_trigger.py.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def test_raw_sql_insert_into_deal_activities_touches_deal_updated_at(
    db_session: AsyncSession, make_account, make_deal
):
    user = User(
        email="trigger-user-deal@example.com",
        hashed_password="x",
        first_name="Rep",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    account = await make_account(owner_id=user.id, company="Acme Corp Deal")
    deal = await make_deal(account_id=account.id, owner_id=user.id, deal_name="Trigger Deal")
    original_updated_at = deal.updated_at

    await db_session.execute(
        text(
            "INSERT INTO deal_activities (deal_id, type, note, created_by) "
            "VALUES (:deal_id, 'note', 'raw insert', :user_id)"
        ),
        {"deal_id": deal.id, "user_id": user.id},
    )

    await db_session.refresh(deal)

    assert deal.updated_at > original_updated_at
