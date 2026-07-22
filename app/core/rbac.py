"""Route-level RBAC declarations, read by app.core.rbac_middleware.

Permission codes are plain strings, not a Python enum: the catalog itself
(labels/descriptions, and which permissions a role has) lives in the
`permissions`/`roles` tables as admin-editable data. A route still has to
name, in code, which permission(s) it requires — that's a decision made by
whoever builds the endpoint, same as any authorization check would need.
"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def public(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a route as requiring no authentication at all."""
    fn.__is_public__ = True  # type: ignore[attr-defined]
    return fn


def requires_permission(*codes: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a route as requiring the caller's role to have at least one of `codes`."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__required_permissions__ = codes  # type: ignore[attr-defined]
        return fn

    return decorator


def tag_router_permissions(router: APIRouter, *codes: str) -> None:
    """Apply the same required-permission set to every route already added to `router`.

    Call this once at the bottom of a router module whose routes all share
    one gate, instead of decorating each endpoint function individually.
    """
    for route in router.routes:
        route.endpoint.__required_permissions__ = codes  # type: ignore[attr-defined]
