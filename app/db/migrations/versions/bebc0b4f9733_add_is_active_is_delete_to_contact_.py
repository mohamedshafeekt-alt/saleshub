"""add is_active is_delete to contact_accounts

Revision ID: bebc0b4f9733
Revises: 1d02f4ee2844
Create Date: 2026-07-23 15:33:09.743641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bebc0b4f9733'
down_revision: Union[str, Sequence[str], None] = '1d02f4ee2844'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'contact_accounts', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False)
    )
    op.add_column(
        'contact_accounts', sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contact_accounts', 'is_delete')
    op.drop_column('contact_accounts', 'is_active')
