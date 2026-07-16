"""touch lead updated_at on activity insert

Revision ID: b0e8a5b118e9
Revises: ee202a31a264
Create Date: 2026-07-16 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b0e8a5b118e9'
down_revision: Union[str, Sequence[str], None] = 'ee202a31a264'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # clock_timestamp() (not now()) so this reflects the actual insert time --
    # now()/CURRENT_TIMESTAMP is fixed for the whole transaction, which would
    # make a lead_activities insert in the same transaction as an earlier
    # lead write appear to not touch updated_at at all.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION touch_lead_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            UPDATE leads SET updated_at = clock_timestamp() WHERE id = NEW.lead_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER lead_activities_touch_lead_updated_at
        AFTER INSERT ON lead_activities
        FOR EACH ROW EXECUTE FUNCTION touch_lead_updated_at();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS lead_activities_touch_lead_updated_at ON lead_activities;")
    op.execute("DROP FUNCTION IF EXISTS touch_lead_updated_at();")
