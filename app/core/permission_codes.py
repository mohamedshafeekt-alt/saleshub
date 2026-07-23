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
DEALS_ACCESS = "deals.access"
DEALS_VIEW_ALL = "deals.view_all"
DEALS_DELETE_ANY_ACTIVITY = "deals.delete_any_activity"
CONTACTS_ACCESS = "contacts.access"
