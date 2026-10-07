"""create account_source_members (account Source Detail chain)

Revision ID: c9a3e5f7b2d4
Revises: b8f2d4e6a1c3
Create Date: 2026-10-06 00:00:01.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9a3e5f7b2d4'
down_revision: Union[str, Sequence[str], None] = 'b8f2d4e6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'account_source_members',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.CheckConstraint('(user_id IS NOT NULL) <> (contact_id IS NOT NULL)', name='ck_account_source_members_one_person'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'user_id', name='uq_account_source_members_user'),
        sa.UniqueConstraint('account_id', 'contact_id', name='uq_account_source_members_contact'),
    )
    op.create_index('ix_account_source_members_account_id', 'account_source_members', ['account_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_account_source_members_account_id', table_name='account_source_members')
    op.drop_table('account_source_members')
