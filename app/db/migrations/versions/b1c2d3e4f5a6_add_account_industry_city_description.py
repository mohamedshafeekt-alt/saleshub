"""add industry/city/description to accounts

Revision ID: b1c2d3e4f5a6
Revises: 9fe2cb108395
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '9fe2cb108395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('accounts', sa.Column('industry', sa.String(), nullable=True))
    op.add_column('accounts', sa.Column('city', sa.String(), nullable=True))
    op.add_column('accounts', sa.Column('description', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('accounts', 'description')
    op.drop_column('accounts', 'city')
    op.drop_column('accounts', 'industry')
