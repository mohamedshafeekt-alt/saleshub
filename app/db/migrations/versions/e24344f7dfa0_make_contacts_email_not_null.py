"""make contacts email not null

Revision ID: e24344f7dfa0
Revises: 466aea3dc2c0
Create Date: 2026-07-24 14:01:09.789419

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e24344f7dfa0'
down_revision: Union[str, Sequence[str], None] = '466aea3dc2c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("contacts", "email", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("contacts", "email", existing_type=sa.String(), nullable=True)
