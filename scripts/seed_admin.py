"""Idempotently seed the permission catalog + starter roles, and an admin
user from ADMIN_EMAIL / ADMIN_PASSWORD env vars.

Usage: PYTHONPATH=. ADMIN_EMAIL=... ADMIN_PASSWORD=... uv run python scripts/seed_admin.py

Note: this bypasses app.services.user_service.create_user on purpose.
create_user always generates its own random password and emails it, which
would make the caller-supplied ADMIN_PASSWORD unusable for a bootstrap
script that must not depend on SMTP being configured/working. So the User
row is constructed directly here, the same way tests/conftest.py's
make_user fixture does.
"""

import asyncio
import os
import sys

from sqlalchemy import select

from app.core.rbac_seed import seed_permissions_and_roles
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.user import User


async def seed_admin() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        print("ADMIN_EMAIL and ADMIN_PASSWORD must both be set in the environment.", file=sys.stderr)
        sys.exit(1)

    async with async_session_factory() as db:
        roles_by_name = await seed_permissions_and_roles(db)
        await db.commit()

        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            print(f"Admin user already exists: {email}")
            return

        db.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                first_name="Admin",
                role_id=roles_by_name["Admin"].id,
            )
        )
        await db.commit()
        print(f"Admin user created: {email}")


if __name__ == "__main__":
    asyncio.run(seed_admin())
