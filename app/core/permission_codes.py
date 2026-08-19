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
ACCOUNTS_DELETE_ANY_ACTIVITY = "accounts.delete_any_activity"
DEALS_ACCESS = "deals.access"
DEALS_VIEW_ALL = "deals.view_all"
DEALS_DELETE_ANY_ACTIVITY = "deals.delete_any_activity"
CONTACTS_ACCESS = "contacts.access"
CONTACTS_VIEW_ALL = "contacts.view_all"
AUDIT_LOG_VIEW = "audit_log.view"
DASHBOARD_VIEW = "dashboard.view"

# A "view_all" permission only widens scope within a module a role can
# already access -- it's meaningless without the module's base "access"
# permission. Enforced in app.services.role_service so a role can never end
# up with one of these but not its dependency, regardless of how the
# permission set was assigned (admin UI or otherwise).
PERMISSION_DEPENDENCIES: dict[str, str] = {
    LEADS_VIEW_ALL: LEADS_ACCESS,
    ACCOUNTS_VIEW_ALL: ACCOUNTS_ACCESS,
    DEALS_VIEW_ALL: DEALS_ACCESS,
    CONTACTS_VIEW_ALL: CONTACTS_ACCESS,
}
