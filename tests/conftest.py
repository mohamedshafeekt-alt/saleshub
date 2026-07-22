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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://saleshub:saleshub@localhost:5432/saleshub_test",
)

# Base.metadata.create_all (below) only creates missing tables -- it can't
# express the lead_activities -> leads.updated_at trigger, which lives as raw
# SQL in an Alembic migration. Recreate it here too so a fresh test DB (a new
# clone, CI) doesn't need `alembic upgrade head` run against it first for
# tests/db/test_lead_activity_trigger.py to pass. asyncpg rejects multiple
# commands in a single prepared statement, so each DDL statement is its own
# conn.execute() call rather than one multi-statement string.
_CREATE_TOUCH_LEAD_UPDATED_AT_STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION touch_lead_updated_at() RETURNS TRIGGER AS $$
    BEGIN
        UPDATE leads SET updated_at = clock_timestamp() WHERE id = NEW.lead_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS lead_activities_touch_lead_updated_at ON lead_activities;",
    """
    CREATE TRIGGER lead_activities_touch_lead_updated_at
    AFTER INSERT ON lead_activities
    FOR EACH ROW EXECUTE FUNCTION touch_lead_updated_at();
    """,
]


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    from app.core.rbac_seed import seed_permissions_and_roles

    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in _CREATE_TOUCH_LEAD_UPDATED_AT_STATEMENTS:
            await conn.execute(text(statement))

    session_factory = async_sessionmaker(eng, expire_on_commit=False)
    async with session_factory() as session:
        await seed_permissions_and_roles(session)
        await session.commit()

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
    from app.models.user import User

    from tests.support.roles import UserRole, role_id_for

    async def _make_user(
        email: str = "user@example.com",
        password: str = "correct-password",
        role: UserRole = UserRole.SALES_REP,
        is_active: bool = True,
        first_name: str = "Test",
    ):
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role_id=await role_id_for(db_session, role),
            first_name=first_name,
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

    from app.models.enums import LeadSource
    from app.models.lead import Lead

    async def _make_lead(
        owner_id: int | None = None,
        email: str = "lead@example.com",
        first_name: str = "Leadfirst",
        last_name: str | None = "Leadlast",
        company: str = "Acme Corp",
        source: LeadSource = LeadSource.WEBSITE,
        **kwargs,
    ):
        lead = Lead(
            first_name=first_name,
            last_name=last_name,
            company=company,
            email=email,
            source=source,
            owner_id=owner_id,
            **kwargs,
        )
        db_session.add(lead)
        await db_session.flush()
        await db_session.commit()
        return lead

    return _make_lead


@pytest_asyncio.fixture
async def make_account(db_session: AsyncSession):
    """Factory fixture: await make_account(owner_id=..., company=..., ...) -> Account.

    Constructs the ORM Account directly (bypassing create_account/AccountCreate)
    so service/API tests can set up fixture data without going through the
    thing under test. Mirrors make_lead's style.
    """

    from app.models.account import Account
    from app.models.enums import LeadTier

    async def _make_account(
        owner_id: int,
        company: str = "Acme Corp",
        domain: str | None = None,
        tier: LeadTier = LeadTier.GOLD,
        source_lead_id: int | None = None,
        **kwargs,
    ):
        account = Account(
            company=company,
            domain=domain,
            tier=tier,
            owner_id=owner_id,
            source_lead_id=source_lead_id,
            **kwargs,
        )
        db_session.add(account)
        await db_session.flush()
        await db_session.commit()
        return account

    return _make_account


@pytest_asyncio.fixture
async def make_contact(db_session: AsyncSession):
    """Factory fixture: await make_contact(account_id=..., first_name=..., ...) -> Contact.

    Constructs the ORM Contact directly (bypassing create_contact/ContactCreate),
    plus the ContactAccount row linking it to account_id (is_primary=False
    unless overridden), so service/API tests can set up fixture data without
    going through the thing under test. Mirrors make_account's style.
    """

    from app.models.contact import Contact
    from app.models.contact_account import ContactAccount

    async def _make_contact(
        account_id: int,
        first_name: str = "Contactfirst",
        last_name: str | None = "Contactlast",
        email: str | None = None,
        phone: str | None = None,
        job_title: str | None = None,
        is_primary: bool = False,
        **kwargs,
    ):
        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            job_title=job_title,
            **kwargs,
        )
        db_session.add(contact)
        await db_session.flush()
        db_session.add(
            ContactAccount(contact_id=contact.id, account_id=account_id, is_primary=is_primary)
        )
        await db_session.flush()
        await db_session.commit()
        return contact

    return _make_contact


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


@pytest_asyncio.fixture
async def make_deal(db_session: AsyncSession):
    """Factory fixture: await make_deal(account_id=..., owner_id=..., ...) -> Deal.

    Constructs the ORM Deal directly (bypassing create_deal/DealCreate) so
    service/API tests can set up fixture data without going through the
    thing under test. Mirrors make_contact's style.
    """

    from app.models.deal import Deal
    from app.models.enums import DealStage

    async def _make_deal(
        account_id: int,
        owner_id: int,
        deal_name: str = "Dealname Co Deal",
        currency: str = "USD",
        stage: DealStage = DealStage.RECEIVED_REQUIREMENTS,
        **kwargs,
    ):
        deal = Deal(
            deal_name=deal_name,
            account_id=account_id,
            owner_id=owner_id,
            currency=currency,
            stage=stage,
            **kwargs,
        )
        db_session.add(deal)
        await db_session.flush()
        await db_session.commit()
        return deal

    return _make_deal
