"""add deal_created, account_created notification types

Revision ID: 8344fb92b26f
Revises: 3effac70e2bb
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8344fb92b26f'
down_revision: Union[str, Sequence[str], None] = '3effac70e2bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE notification_type ADD VALUE 'deal_created'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'account_created'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no DROP VALUE for enums; downgrading the type itself would
    # require recreating it, which isn't worth it for a dev-only rollback.
