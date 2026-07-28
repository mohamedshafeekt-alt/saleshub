"""touch account/deal updated_at on activity insert

Revision ID: a1b2c3d4e5f6
Revises: d9fc0463e4cb
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, Sequence[str], None] = 'd9fc0463e4cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Mirrors touch_lead_updated_at (see b0e8a5b118e9) for accounts/deals --
    # clock_timestamp(), not now(), for the same same-transaction reason.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION touch_account_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            UPDATE accounts SET updated_at = clock_timestamp() WHERE id = NEW.account_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_activities_touch_account_updated_at
        AFTER INSERT ON account_activities
        FOR EACH ROW EXECUTE FUNCTION touch_account_updated_at();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION touch_deal_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            UPDATE deals SET updated_at = clock_timestamp() WHERE id = NEW.deal_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER deal_activities_touch_deal_updated_at
        AFTER INSERT ON deal_activities
        FOR EACH ROW EXECUTE FUNCTION touch_deal_updated_at();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS deal_activities_touch_deal_updated_at ON deal_activities;")
    op.execute("DROP FUNCTION IF EXISTS touch_deal_updated_at();")
    op.execute("DROP TRIGGER IF EXISTS account_activities_touch_account_updated_at ON account_activities;")
    op.execute("DROP FUNCTION IF EXISTS touch_account_updated_at();")
