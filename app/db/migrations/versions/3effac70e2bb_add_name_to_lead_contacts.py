"""add first_name/last_name to lead_contacts

Revision ID: 3effac70e2bb
Revises: 535fddade94a
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3effac70e2bb'
down_revision: Union[str, Sequence[str], None] = '535fddade94a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('lead_contacts', sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('lead_contacts', sa.Column('last_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('lead_contacts', 'last_name')
    op.drop_column('lead_contacts', 'first_name')
