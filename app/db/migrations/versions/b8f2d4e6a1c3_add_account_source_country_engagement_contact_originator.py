"""add accounts.source/country/engagement_type and contacts.is_originator

Revision ID: b8f2d4e6a1c3
Revises: a7e1c3d5f9b2
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8f2d4e6a1c3'
down_revision: Union[str, Sequence[str], None] = 'a7e1c3d5f9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # lead_source already exists (created for leads.source) -- reuse it.
    lead_source = postgresql.ENUM(
        'website', 'referral', 'cold_call', 'linkedin', 'email_campaign', 'other',
        name='lead_source', create_type=False,
    )
    op.add_column('accounts', sa.Column('source', lead_source, nullable=True))
    op.add_column('accounts', sa.Column('country', sa.String(), nullable=True))
    op.add_column('accounts', sa.Column('engagement_type', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('is_originator', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contacts', 'is_originator')
    op.drop_column('accounts', 'engagement_type')
    op.drop_column('accounts', 'country')
    op.drop_column('accounts', 'source')
