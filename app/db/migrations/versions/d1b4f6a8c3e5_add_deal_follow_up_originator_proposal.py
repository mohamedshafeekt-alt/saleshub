"""add deal follow_up_date, originator, proposal status/sent date/SLA due

Revision ID: d1b4f6a8c3e5
Revises: c9a3e5f7b2d4
Create Date: 2026-10-06 00:00:02.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.deal_scoring import proposal_sla_due, total_score

# revision identifiers, used by Alembic.
revision: str = 'd1b4f6a8c3e5'
down_revision: Union[str, Sequence[str], None] = 'c9a3e5f7b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('deals', sa.Column('follow_up_date', sa.Date(), nullable=True))
    op.add_column('deals', sa.Column('originator_user_id', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('originator_contact_id', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('proposal_status', sa.String(), server_default='not_sent', nullable=False))
    op.add_column('deals', sa.Column('proposal_sent_at', sa.Date(), nullable=True))
    op.add_column('deals', sa.Column('proposal_sla_due_at', sa.DateTime(), nullable=True))
    op.create_foreign_key('fk_deals_originator_user', 'deals', 'users', ['originator_user_id'], ['id'])
    op.create_foreign_key('fk_deals_originator_contact', 'deals', 'contacts', ['originator_contact_id'], ['id'])
    op.create_check_constraint(
        'ck_deals_one_originator', 'deals', 'originator_user_id IS NULL OR originator_contact_id IS NULL'
    )
    op.create_index('ix_deals_follow_up_date', 'deals', ['follow_up_date'])
    op.create_index('ix_deals_proposal_sla_due_at', 'deals', ['proposal_sla_due_at'])

    # Backfill the SLA due date for already-scored deals.
    bind = op.get_bind()
    for deal_id, created_at, scores in bind.execute(sa.text("SELECT id, created_at, scores FROM deals WHERE scores IS NOT NULL")):
        due = proposal_sla_due(created_at, total_score(scores))
        if due is not None:
            bind.execute(sa.text("UPDATE deals SET proposal_sla_due_at = :due WHERE id = :id"), {"due": due, "id": deal_id})


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_deals_proposal_sla_due_at', table_name='deals')
    op.drop_index('ix_deals_follow_up_date', table_name='deals')
    op.drop_constraint('ck_deals_one_originator', 'deals', type_='check')
    op.drop_constraint('fk_deals_originator_contact', 'deals', type_='foreignkey')
    op.drop_constraint('fk_deals_originator_user', 'deals', type_='foreignkey')
    op.drop_column('deals', 'proposal_sla_due_at')
    op.drop_column('deals', 'proposal_sent_at')
    op.drop_column('deals', 'proposal_status')
    op.drop_column('deals', 'originator_contact_id')
    op.drop_column('deals', 'originator_user_id')
    op.drop_column('deals', 'follow_up_date')
