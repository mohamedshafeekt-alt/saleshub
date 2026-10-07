"""backfill account source from the lead it was converted from

Revision ID: e2c5a7b9d4f6
Revises: d1b4f6a8c3e5
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2c5a7b9d4f6'
down_revision: Union[str, Sequence[str], None] = 'd1b4f6a8c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Converted accounts used to drop the lead's source; copy it over where
    the account still has none (never overwrites one set by hand)."""
    op.execute(
        """
        UPDATE accounts SET source = leads.source
        FROM leads
        WHERE accounts.source_lead_id = leads.id AND accounts.source IS NULL
        """
    )


def downgrade() -> None:
    """Data-only backfill: nothing to undo (we can't tell backfilled rows
    from ones set by hand afterwards)."""
