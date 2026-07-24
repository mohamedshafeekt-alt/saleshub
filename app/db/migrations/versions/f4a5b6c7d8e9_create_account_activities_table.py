"""create account_activities table

Revision ID: f4a5b6c7d8e9
Revises: e24344f7dfa0
Create Date: 2026-07-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e24344f7dfa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'account_activities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column(
            'type',
            sa.Enum('note', 'meeting', 'call', 'comment', 'follow_up', name='account_activity_type'),
            nullable=False,
        ),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_account_activities_account_id'), 'account_activities', ['account_id'], unique=False
    )

    # New permission: only Admin can delete another user's account activity
    # (account owners can edit but not delete), mirroring deals.delete_any_activity.
    op.execute(
        """
        INSERT INTO permissions (code, label, description, module)
        VALUES (
            'accounts.delete_any_activity',
            'Delete Any Account Activity',
            'Delete a logged activity on any account, regardless of ownership',
            'Accounts'
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'Admin' AND p.code = 'accounts.delete_any_activity'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = "
        "(SELECT id FROM permissions WHERE code = 'accounts.delete_any_activity')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'accounts.delete_any_activity'")
    op.drop_index(op.f('ix_account_activities_account_id'), table_name='account_activities')
    op.drop_table('account_activities')
    op.execute('DROP TYPE account_activity_type')
