"""lead activity follow_up type and updated_by editor tracking

Revision ID: a1b2c3d4e5f6
Revises: 9f6c7e06841e
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f6c7e06841e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE lead_activity_type ADD VALUE 'follow_up'")
    op.add_column('lead_activities', sa.Column('updated_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_lead_activities_updated_by_users', 'lead_activities', 'users', ['updated_by'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_lead_activities_updated_by_users', 'lead_activities', type_='foreignkey')
    op.drop_column('lead_activities', 'updated_by')
    # Postgres has no DROP VALUE for enums; downgrading the type itself would
    # require recreating it, which isn't worth it for a dev-only rollback.
