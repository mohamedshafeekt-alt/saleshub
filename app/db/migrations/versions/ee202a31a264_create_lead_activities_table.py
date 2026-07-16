"""create lead_activities table

Revision ID: ee202a31a264
Revises: cd47adc7b537
Create Date: 2026-07-16 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee202a31a264'
down_revision: Union[str, Sequence[str], None] = 'cd47adc7b537'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'lead_activities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column(
            'type',
            sa.Enum('note', 'meeting', 'call', 'comment', name='lead_activity_type'),
            nullable=False,
        ),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_lead_activities_lead_id'), 'lead_activities', ['lead_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_lead_activities_lead_id'), table_name='lead_activities')
    op.drop_table('lead_activities')
    op.execute('DROP TYPE lead_activity_type')
