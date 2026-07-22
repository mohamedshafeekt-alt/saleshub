"""create contact_accounts table, add contact linkedin_url and alternate_phone

Revision ID: 60f33341f314
Revises: a4f7c1e9b2d6
Create Date: 2026-07-22 18:23:44.292272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60f33341f314'
down_revision: Union[str, Sequence[str], None] = 'a4f7c1e9b2d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('contacts', sa.Column('linkedin_url', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('alternate_phone', sa.String(), nullable=True))

    op.create_table(
        'contact_accounts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contact_id', 'account_id', name='uq_contact_accounts_contact_account'),
    )
    op.create_index(
        op.f('ix_contact_accounts_contact_id'), 'contact_accounts', ['contact_id'], unique=False
    )
    op.create_index(
        op.f('ix_contact_accounts_account_id'), 'contact_accounts', ['account_id'], unique=False
    )
    # At most one primary contact per account.
    op.create_index(
        'uq_contact_accounts_one_primary_per_account',
        'contact_accounts',
        ['account_id'],
        unique=True,
        postgresql_where=sa.text('is_primary = true'),
    )

    # Backfill: every existing contact's account_id becomes its (non-primary)
    # contact_accounts row, so no existing contact-account link is lost.
    op.execute(
        "INSERT INTO contact_accounts (contact_id, account_id, is_primary, created_at, updated_at) "
        "SELECT id, account_id, false, now(), now() FROM contacts"
    )

    op.drop_index('ix_contacts_account_id', table_name='contacts')
    op.drop_column('contacts', 'account_id')


def downgrade() -> None:
    """Downgrade schema.

    Lossy if any contact ended up linked to more than one account after this
    migration (the whole point of contact_accounts is allowing that) -- the
    UPDATE below picks an arbitrary one of that contact's accounts, since a
    single account_id column can't represent more than one.
    """
    op.add_column('contacts', sa.Column('account_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE contacts SET account_id = ca.account_id "
        "FROM contact_accounts ca WHERE ca.contact_id = contacts.id"
    )
    op.alter_column('contacts', 'account_id', nullable=False)
    op.create_index(op.f('ix_contacts_account_id'), 'contacts', ['account_id'], unique=False)

    op.drop_index('uq_contact_accounts_one_primary_per_account', table_name='contact_accounts')
    op.drop_index(op.f('ix_contact_accounts_account_id'), table_name='contact_accounts')
    op.drop_index(op.f('ix_contact_accounts_contact_id'), table_name='contact_accounts')
    op.drop_table('contact_accounts')

    op.drop_column('contacts', 'alternate_phone')
    op.drop_column('contacts', 'linkedin_url')
