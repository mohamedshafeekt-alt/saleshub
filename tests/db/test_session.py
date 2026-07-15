from sqlalchemy import text

from app.db.session import get_db


async def test_get_db_yields_working_session():
    async for session in get_db():
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
