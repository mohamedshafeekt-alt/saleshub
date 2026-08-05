"""make lead_activities type nullable

Revision ID: 4ca3f3a68a3e
Revises: d720e4833c98
Create Date: 2026-08-05 18:18:19.920704

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4ca3f3a68a3e'
down_revision: Union[str, Sequence[str], None] = 'd720e4833c98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("lead_activities", "type", nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("lead_activities", "type", nullable=False)
