"""add unique index on contacts email

Revision ID: 42989a410b60
Revises: bebc0b4f9733
Create Date: 2026-07-24 13:19:30.136250

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '42989a410b60'
down_revision: Union[str, Sequence[str], None] = 'bebc0b4f9733'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f("ix_contacts_email"), "contacts", ["email"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_contacts_email"), table_name="contacts")
