"""DB-level trigger: inserting into account_activities bumps the parent
account's updated_at, even via raw SQL bypassing the service layer.
Mirrors tests/db/test_lead_activity_trigger.py.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def test_raw_sql_insert_into_account_activities_touches_account_updated_at(
    db_session: AsyncSession, make_account
):
    user = User(
        email="trigger-user-account@example.com",
        hashed_password="x",
        first_name="Rep",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    account = await make_account(owner_id=user.id, company="Acme Corp")
    original_updated_at = account.updated_at

    await db_session.execute(
        text(
            "INSERT INTO account_activities (account_id, type, note, created_by) "
            "VALUES (:account_id, 'note', 'raw insert', :user_id)"
        ),
        {"account_id": account.id, "user_id": user.id},
    )

    await db_session.refresh(account)

    assert account.updated_at > original_updated_at
