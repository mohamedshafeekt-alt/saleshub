"""app.core.error_handler: global exception handlers registered on `app`.

Locks in two things:
1. SQLAlchemyError and unhandled Exception get turned into the structured
   `ErrorResponse` JSON shape (status_code/status/message) by global handlers.
2. Deliberate `HTTPException`s raised in existing routes (auth/RBAC) are NOT
   touched by those global handlers -- FastAPI's default `{"detail": ...}`
   shape must keep working. This is the highest-regression-risk part of the
   change, hence the dedicated regression-guard tests below.

Temp-route mounting follows the same save/restore pattern as
tests/api/test_rbac_dependency.py: save `app.router.routes`, mount a
throwaway route inside a fixture, yield a client, restore routes after.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def error_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import get_db
    from app.main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    routes_before = list(app.router.routes)

    @app.get("/__test__/raise-sqlalchemy-error")
    async def _raise_sqlalchemy_error() -> None:
        raise SQLAlchemyError("boom")

    @app.get("/__test__/raise-unhandled-exception")
    async def _raise_unhandled_exception() -> None:
        raise Exception("boom")

    @app.get("/__test__/raise-http-exception")
    async def _raise_http_exception() -> None:
        raise HTTPException(status_code=403, detail="nope")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.router.routes = routes_before
    app.dependency_overrides.clear()


async def test_sqlalchemy_error_returns_structured_error_response(error_client: AsyncClient) -> None:
    """A raised SQLAlchemyError is caught by the global handler and turned into
    an ErrorResponse-shaped 400, not an unhandled 500 or a raw traceback."""

    response = await error_client.get("/__test__/raise-sqlalchemy-error")

    assert response.status_code == 400
    body = response.json()
    assert set(body.keys()) == {"status_code", "status", "message"}
    assert body["status_code"] == 400
    assert isinstance(body["message"], str)
    assert body["message"] != ""


async def test_unhandled_exception_returns_structured_error_response(error_client: AsyncClient) -> None:
    """A raised plain Exception falls through to the catch-all handler and
    still comes back as an ErrorResponse-shaped 500, never a bare 500 with no
    body or a leaked traceback."""

    response = await error_client.get("/__test__/raise-unhandled-exception")

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == {"status_code", "status", "message"}
    assert body["status_code"] == 500
    assert isinstance(body["message"], str)
    assert body["message"] != ""


async def test_http_exception_from_route_keeps_default_detail_shape(error_client: AsyncClient) -> None:
    """Regression guard: an HTTPException raised directly in a route must
    still produce FastAPI's default {"detail": ...} body -- the new global
    handlers must not shadow FastAPI's own HTTPException handling."""

    response = await error_client.get("/__test__/raise-http-exception")

    assert response.status_code == 403
    assert response.json() == {"detail": "nope"}


async def test_existing_auth_401_still_returns_detail_shape(client: AsyncClient, make_user) -> None:
    """Regression guard using a real, already-shipped endpoint: wrong-password
    login must keep returning {"detail": ...}, not get rewritten into the new
    ErrorResponse shape by the global handlers."""

    await make_user(email="errhandler-wrongpw@example.com", password="correct-password")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "errhandler-wrongpw@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    body = response.json()
    assert "detail" in body
    assert "status" not in body
    assert "status_code" not in body
