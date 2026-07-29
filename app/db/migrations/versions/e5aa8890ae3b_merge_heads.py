"""merge heads

Revision ID: e5aa8890ae3b
Revises: 466aea3dc2c0, a5b6c7d8e9f0
Create Date: 2026-07-26 22:32:57.430432

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'e5aa8890ae3b'
down_revision: Union[str, Sequence[str], None] = ('466aea3dc2c0', 'a5b6c7d8e9f0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
