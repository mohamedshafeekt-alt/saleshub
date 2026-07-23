"""dynamic deal stages, company scaffold, deal contact_id/tier

Revision ID: b1d0d8d8425f
Revises: f1a2b3c4d5e6
Create Date: 2026-07-22 00:00:00.000000

Replaces the fixed `deal_stage` Postgres enum with a real `deal_stages`
table (per-company, admin-configurable pipeline stages) and adds the
minimal `companies` table it hangs off of -- no other table gets a
company_id, this is not a full tenancy migration. Also adds `deals.tier`
(nullable, reuses the existing `lead_tier` enum type) and a `deal_contacts`
join table (many-to-many deals<->contacts).

The new 8 seeded stages are a 1:1 rename of the old enum's 8 values (matching
the kanban board mockup's column names exactly), so the backfill below is a
straight name mapping, not a lossy collapse.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1d0d8d8425f'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAGE_SEED = [
    ("Received Requirements", 0, False),
    ("Qualified to Buy", 1, False),
    ("Evaluation", 2, False),
    ("Proposals", 3, False),
    ("Contracts", 4, False),
    ("Closed Won", 5, False),
    ("Closed Lost", 6, False),
    ("Cold Deals", 7, True),
]

_OLD_STAGE_TO_NEW_NAME = {
    "received_requirements": "Received Requirements",
    "qualified_to_buy": "Qualified to Buy",
    "evaluation": "Evaluation",
    "proposals": "Proposals",
    "contracts": "Contracts",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
    "cold_deals": "Cold Deals",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'companies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deal_stages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_cold', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'name', name='uq_deal_stages_company_id_name'),
    )
    op.create_index(op.f('ix_deal_stages_company_id'), 'deal_stages', ['company_id'], unique=False)

    # Seed exactly one company + the 6 default stages, referenced by name
    # during the deals/deal_stage_history backfill below.
    conn = op.get_bind()
    company_id = conn.execute(
        sa.text("INSERT INTO companies (name) VALUES ('Default') RETURNING id")
    ).scalar_one()
    for name, sort_order, is_cold in _STAGE_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO deal_stages (company_id, name, sort_order, is_cold) "
                "VALUES (:company_id, :name, :sort_order, :is_cold)"
            ),
            {"company_id": company_id, "name": name, "sort_order": sort_order, "is_cold": is_cold},
        )

    # --- deals: stage (enum) -> stage_id (FK), plus tier -------------------
    op.add_column('deals', sa.Column('stage_id', sa.Integer(), nullable=True))
    op.add_column(
        'deals',
        sa.Column(
            'tier',
            postgresql.ENUM('diamond', 'gold', 'silver', 'bronze', name='lead_tier', create_type=False),
            nullable=True,
        ),
    )

    for old_stage, new_name in _OLD_STAGE_TO_NEW_NAME.items():
        conn.execute(
            sa.text(
                "UPDATE deals SET stage_id = ("
                "  SELECT id FROM deal_stages WHERE company_id = :company_id AND name = :new_name"
                ") WHERE stage = :old_stage"
            ),
            {"company_id": company_id, "new_name": new_name, "old_stage": old_stage},
        )

    op.alter_column('deals', 'stage_id', nullable=False)
    op.create_foreign_key('fk_deals_stage_id_deal_stages', 'deals', 'deal_stages', ['stage_id'], ['id'])
    op.create_index(op.f('ix_deals_stage_id'), 'deals', ['stage_id'], unique=False)
    op.drop_column('deals', 'stage')

    # --- deal_stage_history: from_stage/to_stage (enum) -> *_id (FK) ------
    op.add_column('deal_stage_history', sa.Column('from_stage_id', sa.Integer(), nullable=True))
    op.add_column('deal_stage_history', sa.Column('to_stage_id', sa.Integer(), nullable=True))

    for old_stage, new_name in _OLD_STAGE_TO_NEW_NAME.items():
        conn.execute(
            sa.text(
                "UPDATE deal_stage_history SET from_stage_id = ("
                "  SELECT id FROM deal_stages WHERE company_id = :company_id AND name = :new_name"
                ") WHERE from_stage = :old_stage"
            ),
            {"company_id": company_id, "new_name": new_name, "old_stage": old_stage},
        )
        conn.execute(
            sa.text(
                "UPDATE deal_stage_history SET to_stage_id = ("
                "  SELECT id FROM deal_stages WHERE company_id = :company_id AND name = :new_name"
                ") WHERE to_stage = :old_stage"
            ),
            {"company_id": company_id, "new_name": new_name, "old_stage": old_stage},
        )

    op.alter_column('deal_stage_history', 'to_stage_id', nullable=False)
    op.create_foreign_key(
        'fk_dsh_from_stage_id_deal_stages', 'deal_stage_history', 'deal_stages', ['from_stage_id'], ['id']
    )
    op.create_foreign_key(
        'fk_dsh_to_stage_id_deal_stages', 'deal_stage_history', 'deal_stages', ['to_stage_id'], ['id']
    )
    op.drop_column('deal_stage_history', 'from_stage')
    op.drop_column('deal_stage_history', 'to_stage')

    # The deal_stage enum type is no longer referenced by any column.
    sa.Enum(name='deal_stage').drop(conn, checkfirst=True)

    # --- deal_contacts: many-to-many deals <-> contacts --------------------
    op.create_table(
        'deal_contacts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('deal_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('deal_id', 'contact_id', name='uq_deal_contacts_deal_id_contact_id'),
    )
    op.create_index(op.f('ix_deal_contacts_deal_id'), 'deal_contacts', ['deal_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_deal_contacts_deal_id'), table_name='deal_contacts')
    op.drop_table('deal_contacts')

    deal_stage_enum = postgresql.ENUM(
        'received_requirements', 'qualified_to_buy', 'evaluation', 'proposals', 'contracts',
        'closed_won', 'closed_lost', 'cold_deals', name='deal_stage',
    )
    conn = op.get_bind()
    deal_stage_enum.create(conn, checkfirst=True)

    op.add_column(
        'deal_stage_history',
        sa.Column('to_stage', postgresql.ENUM(name='deal_stage', create_type=False), nullable=True),
    )
    op.add_column(
        'deal_stage_history',
        sa.Column('from_stage', postgresql.ENUM(name='deal_stage', create_type=False), nullable=True),
    )
    op.drop_constraint('fk_dsh_to_stage_id_deal_stages', 'deal_stage_history', type_='foreignkey')
    op.drop_constraint('fk_dsh_from_stage_id_deal_stages', 'deal_stage_history', type_='foreignkey')
    op.drop_column('deal_stage_history', 'to_stage_id')
    op.drop_column('deal_stage_history', 'from_stage_id')

    op.add_column(
        'deals', sa.Column('stage', postgresql.ENUM(name='deal_stage', create_type=False), nullable=True)
    )
    op.drop_index(op.f('ix_deals_stage_id'), table_name='deals')
    op.drop_constraint('fk_deals_stage_id_deal_stages', 'deals', type_='foreignkey')
    op.drop_column('deals', 'stage_id')
    op.drop_column('deals', 'tier')

    op.drop_index(op.f('ix_deal_stages_company_id'), table_name='deal_stages')
    op.drop_table('deal_stages')
    op.drop_table('companies')
