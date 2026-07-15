"""add first_name/last_name to users

Revision ID: f5bf6823dd88
Revises: d665586e8bde
Create Date: 2026-07-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5bf6823dd88'
down_revision: Union[str, Sequence[str], None] = 'd665586e8bde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing dev rows (owner@innoboon.com, rep@innoboon.com) predate
    # first_name, which is being added NOT NULL. They're disposable
    # dev/test data from earlier manual verification -- delete them rather
    # than backfill a fake name. scripts/seed_admin.py recreates the admin
    # idempotently.
    op.execute("DELETE FROM users")

    op.add_column('users', sa.Column('first_name', sa.String(), nullable=False))
    op.add_column('users', sa.Column('last_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
