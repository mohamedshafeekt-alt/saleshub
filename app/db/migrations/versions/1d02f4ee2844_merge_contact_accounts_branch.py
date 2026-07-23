"""merge contact_accounts branch

Revision ID: 1d02f4ee2844
Revises: 60f33341f314, d3e4f5a6b7c8
Create Date: 2026-07-23 15:16:51.370343

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '1d02f4ee2844'
down_revision: Union[str, Sequence[str], None] = ('60f33341f314', 'd3e4f5a6b7c8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
