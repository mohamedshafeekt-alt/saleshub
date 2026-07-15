"""Global FastAPI exception handling.

Deliberately does NOT register a handler for HTTPException /
StarletteHTTPException -- FastAPI's own default handler for it (the
`{"detail": ...}` shape) must keep working untouched for existing
401/403/409 responses.

SQLAlchemyError is registered as a normal `add_exception_handler`: it's a
regular subclass, so Starlette's `ExceptionMiddleware` handles it and turns
it straight into a response.

The catch-all for a bare `Exception` can NOT use `add_exception_handler`,
though: Starlette special-cases a handler registered for the literal
`Exception` class -- it gets pulled out into `ServerErrorMiddleware`, which
*always* re-raises the exception after building the response (so a real
server can still log it / a test client can still opt into seeing it). That
re-raise propagates straight through httpx's `ASGITransport` (which defaults
`raise_app_exceptions=True`), so the client never sees our JSON body --
it sees the raw exception. A plain HTTP middleware sits *inside*
`ServerErrorMiddleware`, so catching the exception there returns a normal
response and nothing ever re-raises past it.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import logger
from app.schemas.generic_response import ErrorResponse


async def sqlalchemy_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Database error occurred: %s", exc, exc_info=True)
    body = ErrorResponse(status_code=400, status="DatabaseError", message=str(exc))
    return JSONResponse(status_code=400, content=body.model_dump())


async def unhandled_exception_response(exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception occurred: %s", exc, exc_info=True)
    body = ErrorResponse(status_code=500, status="InternalServerError", message=str(exc))
    return JSONResponse(status_code=500, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)

    @app.middleware("http")
    async def catch_all_exception_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ) -> JSONResponse:
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 -- intentional catch-all
            # SQLAlchemyError never reaches here: ExceptionMiddleware (nested
            # inside this middleware) already converts it to a response via
            # the add_exception_handler registration above.
            return await unhandled_exception_response(exc)
