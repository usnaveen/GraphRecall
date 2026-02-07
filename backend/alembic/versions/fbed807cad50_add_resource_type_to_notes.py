"""add_resource_type_to_notes

Revision ID: fbed807cad50
Revises: 
Create Date: 2026-01-31 23:04:32.179843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbed807cad50'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add resource_type column and index to notes table."""
    # Add the column (nullable, defaulting to 'markdown')
    op.add_column(
        'notes',
        sa.Column('resource_type', sa.String(50), nullable=True, server_default='markdown')
    )
    # Create the index that was failing before
    op.create_index('idx_notes_resource_type', 'notes', ['resource_type'])


def downgrade() -> None:
    """Remove resource_type column and index from notes table."""
    op.drop_index('idx_notes_resource_type', table_name='notes')
    op.drop_column('notes', 'resource_type')
