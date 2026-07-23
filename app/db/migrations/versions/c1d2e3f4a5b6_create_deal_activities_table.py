"""create deal_activities table

Revision ID: c1d2e3f4a5b6
Revises: b1d0d8d8425f
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1d0d8d8425f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'deal_activities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column(
            'type',
            sa.Enum('note', 'meeting', 'call', 'comment', 'follow_up', name='deal_activity_type'),
            nullable=False,
        ),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_deal_activities_deal_id'), 'deal_activities', ['deal_id'], unique=False)

    # New permission: only Admin can delete another user's deal activity
    # (deal owners can edit but not delete), mirroring leads.delete_any_activity.
    op.execute(
        """
        INSERT INTO permissions (code, label, description, module)
        VALUES (
            'deals.delete_any_activity',
            'Delete Any Deal Activity',
            'Delete a logged activity on any deal, regardless of ownership',
            'Deals'
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'Admin' AND p.code = 'deals.delete_any_activity'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = "
        "(SELECT id FROM permissions WHERE code = 'deals.delete_any_activity')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'deals.delete_any_activity'")
    op.drop_index(op.f('ix_deal_activities_deal_id'), table_name='deal_activities')
    op.drop_table('deal_activities')
    op.execute('DROP TYPE deal_activity_type')
