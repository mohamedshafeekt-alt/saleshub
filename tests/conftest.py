"""Shared pytest fixtures: transactional Postgres session + FastAPI test client.

Every test runs against the real `saleshub_test` database, inside an outer
transaction that is rolled back on teardown, so tests never leave data behind
and never touch each other.
"""

import os
from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://saleshub:saleshub@localhost:5432/saleshub_test",
)


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session
        await conn.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    # Imported lazily: app.main doesn't exist yet at test-writing time, and we
    # want collection of *other* test modules to still succeed.
    from app.main import app
    from app.db.session import get_db

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    """Factory fixture: await make_user(email=..., password=..., role=...) -> User.

    Constructs the ORM User directly (bypassing create_user/UserCreate) so tests
    get a user with a *known* plaintext password to log in with. This is
    required now that UserCreate no longer accepts a password (admin-created
    users get a server-generated one emailed to them) — going through
    create_user here would make the password unknown to the test.
    """

    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async def _make_user(
        email: str = "user@example.com",
        password: str = "correct-password",
        role: UserRole = UserRole.SALES_REP,
        is_active: bool = True,
    ):
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=role,
            first_name="Test",
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.commit()
        return user

    return _make_user


@pytest_asyncio.fixture
async def make_lead(db_session: AsyncSession):
    """Factory fixture: await make_lead(owner_id=..., email=..., ...) -> Lead.

    Constructs the ORM Lead directly (bypassing create_lead/LeadCreate) so
    service/API tests can set up fixture data without going through the
    thing under test. Mirrors make_user's style.
    """

    from app.models.enums import LeadSource, LeadTier
    from app.models.lead import Lead

    async def _make_lead(
        owner_id: int,
        email: str = "lead@example.com",
        first_name: str = "Leadfirst",
        last_name: str | None = "Leadlast",
        company: str = "Acme Corp",
        source: LeadSource = LeadSource.WEBSITE,
        tier: LeadTier = LeadTier.GOLD,
        **kwargs,
    ):
        lead = Lead(
            first_name=first_name,
            last_name=last_name,
            company=company,
            email=email,
            source=source,
            tier=tier,
            owner_id=owner_id,
            **kwargs,
        )
        db_session.add(lead)
        await db_session.flush()
        await db_session.commit()
        return lead

    return _make_lead


@pytest_asyncio.fixture
async def auth_headers():
    """Factory fixture: auth_headers(user) -> {"Authorization": "Bearer <token>"}."""

    from app.core.security import create_access_token

    def _auth_headers(user, expires_delta: timedelta | None = None) -> dict[str, str]:
        token = create_access_token(subject=str(user.id), expires_delta=expires_delta)
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
