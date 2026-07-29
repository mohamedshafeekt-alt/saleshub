"""Fixed permission catalog + starter roles, seeded as ordinary editable data.

The catalog (what permissions exist) has to be seeded once per environment
so route checks have something to match against; the roles seeded here are
just a starting point that replicates today's access exactly — admins can
rename, delete, or add to them afterward via /roles.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permission_codes import (
    ACCOUNTS_ACCESS,
    ACCOUNTS_DELETE_ANY_ACTIVITY,
    ACCOUNTS_VIEW_ALL,
    AUDIT_LOG_VIEW,
    CONTACTS_ACCESS,
    DEALS_ACCESS,
    DEALS_DELETE_ANY_ACTIVITY,
    DEALS_VIEW_ALL,
    LEADS_ACCESS,
    LEADS_DELETE_ANY_ACTIVITY,
    LEADS_NOTIFY_ON_CREATE,
    LEADS_VIEW_ALL,
    ROLES_MANAGE,
    USERS_MANAGE,
    USERS_VIEW,
)
from app.models.permission import Permission
from app.models.role import Role

_PERMISSIONS = [
    (USERS_MANAGE, "Manage Users", "Create, edit, and deactivate users", "Users"),
    (USERS_VIEW, "View Users", "View the list of users", "Users"),
    (ROLES_MANAGE, "Manage Roles", "Create and edit roles and their permissions", "Roles"),
    (LEADS_ACCESS, "Access Leads", "View and manage leads", "Leads"),
    (LEADS_VIEW_ALL, "View All Leads", "See all leads, not just assigned ones", "Leads"),
    (
        LEADS_NOTIFY_ON_CREATE,
        "New Lead Notifications",
        "Receive a notification when a new lead is created",
        "Leads",
    ),
    (
        LEADS_DELETE_ANY_ACTIVITY,
        "Delete Any Lead Activity",
        "Delete a logged activity on any lead, regardless of ownership",
        "Leads",
    ),
    (ACCOUNTS_ACCESS, "Access Accounts", "View and manage accounts", "Accounts"),
    (ACCOUNTS_VIEW_ALL, "View All Accounts", "See all accounts, not just owned ones", "Accounts"),
    (
        ACCOUNTS_DELETE_ANY_ACTIVITY,
        "Delete Any Account Activity",
        "Delete a logged activity on any account, regardless of ownership",
        "Accounts",
    ),
    (DEALS_ACCESS, "Access Deals", "View and manage deals", "Deals"),
    (DEALS_VIEW_ALL, "View All Deals", "See all deals, not just owned ones", "Deals"),
    (
        DEALS_DELETE_ANY_ACTIVITY,
        "Delete Any Deal Activity",
        "Delete a logged activity on any deal, regardless of ownership",
        "Deals",
    ),
    (CONTACTS_ACCESS, "Access Contacts", "View and manage contacts", "Contacts"),
    (AUDIT_LOG_VIEW, "View Audit Log", "View the system-wide audit log", "Audit Log"),
]

STARTER_ROLES = {
    "Admin": [code for code, *_ in _PERMISSIONS],
    "Sales Manager": [
        LEADS_ACCESS,
        LEADS_VIEW_ALL,
        ACCOUNTS_ACCESS,
        ACCOUNTS_VIEW_ALL,
        DEALS_ACCESS,
        DEALS_VIEW_ALL,
        CONTACTS_ACCESS,
        USERS_VIEW,
    ],
    "Sales Rep": [LEADS_ACCESS, ACCOUNTS_ACCESS, DEALS_ACCESS, CONTACTS_ACCESS, USERS_VIEW],
    "Delivery SME": [LEADS_ACCESS, USERS_VIEW],
}


async def seed_permissions_and_roles(db: AsyncSession) -> dict[str, Role]:
    """Idempotent: safe to call on every startup/test-session setup. Returns
    the starter roles by name, for callers (e.g. seed_admin.py) that need a
    role id right after seeding."""
    existing_permissions = (await db.execute(select(Permission))).scalars().all()
    by_code = {permission.code: permission for permission in existing_permissions}

    newly_inserted_codes: set[str] = set()
    for code, label, description, module in _PERMISSIONS:
        if code not in by_code:
            permission = Permission(code=code, label=label, description=description, module=module)
            db.add(permission)
            by_code[code] = permission
            newly_inserted_codes.add(code)
    await db.flush()

    existing_roles = (await db.execute(select(Role).options(selectinload(Role.permissions)))).scalars().all()
    roles_by_name = {role.name: role for role in existing_roles}

    for name, codes in STARTER_ROLES.items():
        role = roles_by_name.get(name)
        if role is None:
            role = Role(
                name=name,
                description=f"Starter role: {name}",
                permissions=[by_code[code] for code in codes],
            )
            db.add(role)
            roles_by_name[name] = role
        else:
            # Existing role: only grant permission codes that are brand-new
            # to the whole permissions table in this run (i.e. just added to
            # _PERMISSIONS in code and never seeded before). A code that
            # already existed before this run but is missing from this
            # role's current assignment is left alone -- that's assumed to
            # be a deliberate admin removal via /roles, not a gap to backfill.
            role_codes = {permission.code for permission in role.permissions}
            for code in codes:
                if code not in role_codes and code in newly_inserted_codes:
                    role.permissions.append(by_code[code])
    await db.flush()

    return roles_by_name
