"""make lead tier/owner_id nullable, add lead status

Revision ID: e565b559a432
Revises: b1c2d3e4f5a6
Create Date: 2026-07-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e565b559a432'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

lead_status_enum = postgresql.ENUM(
    'not_contacted', 'attempted_to_contact', 'contacted',
    'contact_in_future', 'junk_lead', 'lost_lead', name='lead_status',
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'leads', 'tier',
        existing_type=sa.Enum('diamond', 'gold', 'silver', 'bronze', name='lead_tier'),
        nullable=True,
    )
    op.alter_column(
        'leads', 'owner_id',
        existing_type=sa.Integer(),
        nullable=True,
    )
    lead_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'leads',
        sa.Column('status', lead_status_enum, server_default='not_contacted', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leads', 'status')
    lead_status_enum.drop(op.get_bind(), checkfirst=True)
    op.alter_column(
        'leads', 'owner_id',
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        'leads', 'tier',
        existing_type=sa.Enum('diamond', 'gold', 'silver', 'bronze', name='lead_tier'),
        nullable=False,
    )
