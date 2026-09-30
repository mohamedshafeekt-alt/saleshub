"""add deals.scores (D1–D8 qualification scoring)

Revision ID: a7e1c3d5f9b2
Revises: 8344fb92b26f
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7e1c3d5f9b2'
down_revision: Union[str, Sequence[str], None] = '8344fb92b26f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('deals', sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('deals', 'scores')
