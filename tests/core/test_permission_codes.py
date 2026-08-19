"""app.core.permission_codes.resolve_permission_dependencies: transitive
closure over PERMISSION_DEPENDENCIES (e.g. deals.view_all -> deals.access ->
users.view, not just the one direct dependency a single lookup would find)."""

from app.core.permission_codes import (
    ACCOUNTS_ACCESS,
    DEALS_ACCESS,
    DEALS_VIEW_ALL,
    USERS_VIEW,
    resolve_permission_dependencies,
)


def test_resolve_permission_dependencies_is_transitive():
    resolved = resolve_permission_dependencies({DEALS_VIEW_ALL})

    assert resolved == {DEALS_VIEW_ALL, DEALS_ACCESS, USERS_VIEW}


def test_resolve_permission_dependencies_no_op_when_already_satisfied():
    codes = {ACCOUNTS_ACCESS, USERS_VIEW}

    assert resolve_permission_dependencies(codes) == codes


def test_resolve_permission_dependencies_empty_input_returns_empty():
    assert resolve_permission_dependencies(set()) == set()
