"""add lead_converted notification type

Revision ID: 535fddade94a
Revises: 4ca3f3a68a3e
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '535fddade94a'
down_revision: Union[str, Sequence[str], None] = '4ca3f3a68a3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE notification_type ADD VALUE 'lead_converted'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no DROP VALUE for enums; downgrading the type itself would
    # require recreating it, which isn't worth it for a dev-only rollback.
