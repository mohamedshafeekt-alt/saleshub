"""drop lead tier

Revision ID: d7d7a0c52605
Revises: c2d3e4f5a6b7
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7d7a0c52605'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('leads', 'tier')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'leads',
        sa.Column('tier', sa.Enum('diamond', 'gold', 'silver', 'bronze', name='lead_tier'), nullable=True),
    )
