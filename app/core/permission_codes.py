"""Permission code constants used by routes (see app.core.rbac). The
authoritative catalog — labels, descriptions, module grouping — lives in the
`permissions` table (seeded by scripts/seed_admin.py); these constants exist
so route files don't repeat string literals that have to match those rows."""

USERS_MANAGE = "users.manage"
USERS_VIEW = "users.view"
ROLES_MANAGE = "roles.manage"
LEADS_ACCESS = "leads.access"
LEADS_VIEW_ALL = "leads.view_all"
LEADS_NOTIFY_ON_CREATE = "leads.notify_on_create"
LEADS_DELETE_ANY_ACTIVITY = "leads.delete_any_activity"
ACCOUNTS_ACCESS = "accounts.access"
ACCOUNTS_VIEW_ALL = "accounts.view_all"
ACCOUNTS_NOTIFY_ON_CREATE = "accounts.notify_on_create"
ACCOUNTS_DELETE_ANY_ACTIVITY = "accounts.delete_any_activity"
DEALS_ACCESS = "deals.access"
DEALS_VIEW_ALL = "deals.view_all"
DEALS_NOTIFY_ON_CREATE = "deals.notify_on_create"
DEALS_DELETE_ANY_ACTIVITY = "deals.delete_any_activity"
CONTACTS_ACCESS = "contacts.access"
CONTACTS_VIEW_ALL = "contacts.view_all"
AUDIT_LOG_VIEW = "audit_log.view"
DASHBOARD_VIEW = "dashboard.view"

# A "view_all" permission only widens scope within a module a role can
# already access -- it's meaningless without the module's base "access"
# permission. Leads/Accounts/Deals access, in turn, requires users.view: the
# Owner dropdown on every one of those modules' create/edit forms calls
# GET /users, and a role with e.g. deals.access but not users.view could
# view/create Deals yet get a 403 the moment it tried to pick an owner.
# Enforced in app.services.role_service (transitively, via
# resolve_permission_dependencies below) so a role can never end up with one
# of these but not its dependency, regardless of how the permission set was
# assigned (admin UI or otherwise) -- and in app.core.rbac_seed, which
# backfills any already-existing role on every app startup.
PERMISSION_DEPENDENCIES: dict[str, str] = {
    LEADS_VIEW_ALL: LEADS_ACCESS,
    ACCOUNTS_VIEW_ALL: ACCOUNTS_ACCESS,
    DEALS_VIEW_ALL: DEALS_ACCESS,
    CONTACTS_VIEW_ALL: CONTACTS_ACCESS,
    LEADS_ACCESS: USERS_VIEW,
    ACCOUNTS_ACCESS: USERS_VIEW,
    DEALS_ACCESS: USERS_VIEW,
}


def resolve_permission_dependencies(codes: set[str]) -> set[str]:
    """`codes` plus the transitive closure of every PERMISSION_DEPENDENCIES
    entry they require -- e.g. {deals.view_all} resolves to
    {deals.view_all, deals.access, users.view}, not just the one direct
    dependency a single lookup would find."""
    resolved = set(codes)
    frontier = set(codes)
    while frontier:
        frontier = {
            PERMISSION_DEPENDENCIES[code] for code in frontier if code in PERMISSION_DEPENDENCIES
        } - resolved
        resolved |= frontier
    return resolved
