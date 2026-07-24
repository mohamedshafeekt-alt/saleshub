"""Central RBAC enforcement: reads the `@public` / `@requires_permission(...)`
metadata set by app.core.rbac off the request's resolved route, and gates the
request before it reaches the endpoint body.

Implemented as a single FastAPI dependency applied to every route (via
`FastAPI(dependencies=[Depends(enforce_rbac)])` in app.main), not a raw ASGI
middleware: BaseHTTPMiddleware's dispatch() runs *before* routing resolves,
so `request.scope["route"]` (needed to read the endpoint's metadata) isn't
populated yet at that point — this FastAPI version also wraps included
routers in an internal object that doesn't expose `.endpoint` directly,
so manually re-matching `app.routes` ourselves is unreliable. A dependency
runs after FastAPI has already resolved the real route, so `request.scope`
is correctly populated regardless of that internal representation, while
still being one central function rather than one `Depends(require_role(...))`
list per router.
"""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

_UNAUTHENTICATED = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def enforce_rbac(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    route = request.scope.get("route")
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None or getattr(endpoint, "__is_public__", False):
        return

    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _UNAUTHENTICATED

    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError) as exc:
        raise _UNAUTHENTICATED from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    if user.password_changed_at is not None and "iat" in payload:
        issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC).replace(tzinfo=None)
        if issued_at < user.password_changed_at:
            raise _UNAUTHENTICATED

    required = getattr(endpoint, "__required_permissions__", None)
    if required and not (user.permission_codes & set(required)):
        raise _FORBIDDEN

    request.state.user = user
