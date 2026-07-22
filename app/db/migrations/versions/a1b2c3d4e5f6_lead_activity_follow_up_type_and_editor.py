"""lead activity follow_up type and updated_by editor tracking

Revision ID: a1b2c3d4e5f6
Revises: 9f6c7e06841e
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f6c7e06841e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE lead_activity_type ADD VALUE 'follow_up'")
    op.add_column('lead_activities', sa.Column('updated_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_lead_activities_updated_by_users', 'lead_activities', 'users', ['updated_by'], ['id']
    )

    # New permission: only Admin can delete another user's lead activity
    # (lead owners can edit but not delete). seed_permissions_and_roles()
    # only back-fills brand-new roles, not new permissions on roles that
    # already exist, so an already-seeded Admin role needs this data fix too.
    op.execute(
        """
        INSERT INTO permissions (code, label, description, module)
        VALUES (
            'leads.delete_any_activity',
            'Delete Any Lead Activity',
            'Delete a logged activity on any lead, regardless of ownership',
            'Leads'
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'Admin' AND p.code = 'leads.delete_any_activity'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = "
        "(SELECT id FROM permissions WHERE code = 'leads.delete_any_activity')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'leads.delete_any_activity'")
    op.drop_constraint('fk_lead_activities_updated_by_users', 'lead_activities', type_='foreignkey')
    op.drop_column('lead_activities', 'updated_by')
    # Postgres has no DROP VALUE for enums; downgrading the type itself would
    # require recreating it, which isn't worth it for a dev-only rollback.
