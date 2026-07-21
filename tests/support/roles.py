"""Test-only convenience for referencing the seeded starter roles by the same
names the old UserRole enum used, without hardcoding a fixed role set in
production code. The engine fixture in tests/conftest.py seeds these roles
once per test session via app.core.rbac_seed.seed_permissions_and_roles."""

import enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role


class UserRole(str, enum.Enum):
    SALES_REP = "Sales Rep"
    DELIVERY_SME = "Delivery SME"
    SALES_MANAGER = "Sales Manager"
    ADMIN = "Admin"


async def role_id_for(db_session: AsyncSession, role: UserRole) -> int:
    result = await db_session.execute(select(Role.id).where(Role.name == role.value))
    return result.scalar_one()
